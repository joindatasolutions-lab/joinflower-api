from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.core.security import assert_same_empresa, get_current_auth_context, is_empresa_admin_context, is_super_admin_context, require_module_access
from app.database import get_db
from app.models.cliente import Cliente
from app.schemas.cliente import ClientePayload, ClienteUpdatePayload

router = APIRouter()

CUSTOMER_INACTIVE_DAYS = 90
CUSTOMER_ACTIVE_DAYS = 90
CUSTOMER_AT_RISK_MULTIPLIER = Decimal("1.5")
CUSTOMER_CHURN_HIGH_RISK_THRESHOLD = Decimal("70")
CUSTOMER_REPURCHASE_HIGH_PROBABILITY_THRESHOLD = Decimal("60")
CUSTOMER_VIP_TOP_PERCENT = Decimal("10")
CUSTOMER_HIGH_VALUE_TOP_PERCENT = Decimal("20")
CUSTOMER_PRICE_RANGE_LOW_MAX = Decimal("120000")
CUSTOMER_PRICE_RANGE_MID_MAX = Decimal("250000")
CUSTOMER_SEGMENTS = {"NEW", "ACTIVE", "RECURRING", "VIP", "INACTIVE", "AT_RISK", "HIGH_VALUE"}
CUSTOMER_METRIC_SORTS = {
    "name",
    "last_purchase_at",
    "first_purchase_at",
    "purchase_count",
    "total_spent",
    "average_order_value",
    "lifetime_value",
    "days_since_last_purchase",
    "average_days_between_purchases",
    "favorite_product",
    "favorite_category",
    "preferred_channel",
    "average_price_range",
}


def _resolve_empresa_id(auth, empresa_id: int | None) -> int:
    if empresa_id is None:
        if auth.empresaID in (None, 0):
            raise HTTPException(status_code=400, detail="empresaID es obligatorio para este usuario")
        return int(auth.empresaID)
    assert_same_empresa(auth, int(empresa_id))
    return int(empresa_id)


def _cliente_to_dict(cliente: Cliente) -> dict:
    return {
        "clienteID": int(cliente.idCliente),
        "empresaID": int(cliente.empresaID or 0),
        "tipoIdent": str(cliente.tipoIdent or "").strip() or None,
        "identificacion": str(cliente.identificacion or "").strip() or None,
        "indicativo": str(cliente.indicativo or "").strip() or None,
        "nombreCompleto": str(cliente.nombreCompleto or "").strip(),
        "telefono": str(cliente.telefono or "").strip() or None,
        "telefonoCompleto": str(cliente.telefonoCompleto or "").strip() or None,
        "email": str(cliente.email or "").strip() or None,
        "fechaCumpleanos": cliente.fechaCumpleanos.isoformat() if cliente.fechaCumpleanos else None,
        "fechaAniversario": cliente.fechaAniversario.isoformat() if cliente.fechaAniversario else None,
        "activo": bool(cliente.activo),
        "createdAt": cliente.createdAt.isoformat() if cliente.createdAt else None,
        "updatedAt": cliente.updatedAt.isoformat() if cliente.updatedAt else None,
    }


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _pct(numerator: Decimal | int | float, denominator: Decimal | int | float) -> float:
    denominator_decimal = Decimal(str(denominator or 0))
    if denominator_decimal <= 0:
        return 0.0
    return float((Decimal(str(numerator or 0)) / denominator_decimal * Decimal("100")).quantize(Decimal("0.01")))


def _average_price_range(value) -> str | None:
    amount = _money(value)
    if amount <= 0:
        return None
    if amount <= CUSTOMER_PRICE_RANGE_LOW_MAX:
        return "LOW"
    if amount <= CUSTOMER_PRICE_RANGE_MID_MAX:
        return "MID"
    return "HIGH"


def _clamp_decimal(value: Decimal | int | float, minimum: Decimal = Decimal("0"), maximum: Decimal = Decimal("100")) -> Decimal:
    decimal_value = Decimal(str(value or 0))
    return min(max(decimal_value, minimum), maximum).quantize(Decimal("0.01"))


def _date_or_none(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _metric_date(value) -> str | None:
    parsed = _date_or_none(value)
    return parsed.isoformat() if parsed else None


def _days_since(value: date | datetime | None, today: date) -> int | None:
    parsed = _date_or_none(value)
    if not parsed:
        return None
    return max((today - parsed).days, 0)


def _next_annual_occurrence(value: date | datetime | None, today: date) -> date | None:
    parsed = _date_or_none(value)
    if not parsed:
        return None
    year = today.year
    try:
        candidate = date(year, parsed.month, parsed.day)
    except ValueError:
        candidate = date(year, 2, 28)
    if candidate < today:
        try:
            candidate = date(year + 1, parsed.month, parsed.day)
        except ValueError:
            candidate = date(year + 1, 2, 28)
    return candidate


def _customer_special_date_opportunities(rows: list[dict], *, today: date, max_days: int = 60) -> list[dict]:
    opportunities = []
    for row in rows:
        for field_name, occasion in (("fecha_cumpleanos", "BIRTHDAY"), ("fecha_aniversario", "ANNIVERSARY")):
            next_date = _next_annual_occurrence(row.get(field_name), today)
            if not next_date:
                continue
            days_remaining = (next_date - today).days
            if days_remaining < 0 or days_remaining > max_days:
                continue
            opportunities.append(
                {
                    "customer_id": str(row["customer_id"]),
                    "clienteID": int(row["customer_id"]),
                    "name": row.get("name") or "",
                    "nombreCompleto": row.get("name") or "",
                    "occasion": occasion,
                    "date": next_date.isoformat(),
                    "days_remaining": days_remaining,
                    "last_purchase_at": _metric_date(row.get("last_purchase_at")),
                    "total_spent": float(_money(row.get("total_spent"))),
                    "lifetime_value": float(_money(row.get("total_spent"))),
                    "favorite_product": row.get("favorite_product"),
                    "favorite_category": row.get("favorite_category"),
                    "average_price_range": _average_price_range(row.get("average_order_value")),
                    "preferred_occasion": None,
                    "preferred_channel": row.get("preferred_channel"),
                    "segments": row.get("segments", []),
                }
            )
    opportunities.sort(key=lambda item: (int(item["days_remaining"]), item["name"]))
    return opportunities


def _next_special_date_summary(row: dict, *, today: date) -> dict | None:
    candidates = []
    for field_name, occasion in (("fecha_cumpleanos", "BIRTHDAY"), ("fecha_aniversario", "ANNIVERSARY")):
        next_date = _next_annual_occurrence(row.get(field_name), today)
        if not next_date:
            continue
        candidates.append(
            {
                "occasion": occasion,
                "date": next_date.isoformat(),
                "days_remaining": (next_date - today).days,
            }
        )
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (int(item["days_remaining"]), item["occasion"]))[0]


def _customer_action_recommendation(row: dict, *, today: date) -> dict:
    segments = set(row.get("segments") or [])
    purchase_count = int(row.get("purchase_count") or 0)
    next_special_date = _next_special_date_summary(row, today=today)
    favorite_product = row.get("favorite_product")
    favorite_category = row.get("favorite_category")
    preferred_channel = row.get("preferred_channel")

    if purchase_count <= 0:
        action = "ACQUIRE_FIRST_PURCHASE"
        message = "Cliente registrado sin compras. Activar campana de primera compra."
    elif next_special_date and int(next_special_date["days_remaining"]) <= 30:
        action = "SPECIAL_DATE_CAMPAIGN"
        message = "Cliente con fecha especial proxima. Ofrecer arreglo recomendado."
    elif "AT_RISK" in segments or "INACTIVE" in segments:
        action = "REACTIVATE"
        message = "Cliente con senales de abandono. Enviar incentivo o contacto personalizado."
    elif "VIP" in segments:
        action = "VIP_CARE"
        message = "Cliente VIP. Priorizar atencion personalizada y oferta premium."
    elif "RECURRING" in segments:
        action = "REORDER_FAVORITE"
        message = "Cliente recurrente. Sugerir recompra segun preferencias historicas."
    elif "NEW" in segments:
        action = "WELCOME_SECOND_PURCHASE"
        message = "Cliente nuevo. Impulsar segunda compra."
    else:
        action = "NURTURE"
        message = "Cliente comprador. Mantener comunicacion comercial regular."

    return {
        "action": action,
        "message": message,
        "recommended_product": favorite_product,
        "recommended_category": favorite_category,
        "preferred_channel": preferred_channel,
        "next_special_date": next_special_date,
    }


def _customer_intelligence(row: dict, *, today: date) -> dict:
    purchase_count = int(row.get("purchase_count") or 0)
    days_since = row.get("days_since_last_purchase")
    avg_days = row.get("average_days_between_purchases")
    segments = set(row.get("segments") or [])

    if purchase_count <= 0:
        churn_probability = Decimal("0")
        repurchase_probability = Decimal("15")
        health_score = Decimal("20")
    else:
        if days_since is None:
            recency_score = Decimal("0")
        elif int(days_since) <= 30:
            recency_score = Decimal("100")
        elif int(days_since) <= 60:
            recency_score = Decimal("80")
        elif int(days_since) <= 90:
            recency_score = Decimal("65")
        elif int(days_since) <= 180:
            recency_score = Decimal("35")
        else:
            recency_score = Decimal("15")

        frequency_score = _clamp_decimal(Decimal(purchase_count) * Decimal("20"))
        value_score = Decimal("100") if "VIP" in segments else Decimal("80") if "HIGH_VALUE" in segments else Decimal("45")
        health_score = _clamp_decimal((recency_score * Decimal("0.45")) + (frequency_score * Decimal("0.25")) + (value_score * Decimal("0.30")))
        if "AT_RISK" in segments:
            health_score = _clamp_decimal(health_score - Decimal("20"))

        if avg_days is not None and Decimal(str(avg_days)) > 0 and days_since is not None:
            ratio = Decimal(str(days_since)) / Decimal(str(avg_days))
            if ratio <= Decimal("1"):
                churn_probability = Decimal("15")
            elif ratio <= Decimal("1.5"):
                churn_probability = Decimal("35")
            elif ratio <= Decimal("2"):
                churn_probability = Decimal("60")
            else:
                churn_probability = Decimal("85")
        elif days_since is not None and int(days_since) <= 90:
            churn_probability = Decimal("20")
        elif days_since is not None and int(days_since) <= 180:
            churn_probability = Decimal("55")
        else:
            churn_probability = Decimal("80")

        if "INACTIVE" in segments:
            churn_probability = max(churn_probability, Decimal("70"))
        if "AT_RISK" in segments:
            churn_probability = max(churn_probability, Decimal("85"))
        churn_probability = _clamp_decimal(churn_probability)

        repurchase_probability = _clamp_decimal(Decimal("100") - churn_probability)
        if "ACTIVE" in segments:
            repurchase_probability = _clamp_decimal(repurchase_probability + Decimal("10"))
        if "RECURRING" in segments:
            repurchase_probability = _clamp_decimal(repurchase_probability + Decimal("10"))

    return {
        "customer_health_score": float(health_score),
        "churn_risk_probability": float(churn_probability),
        "repurchase_probability": float(repurchase_probability),
        "next_best_action": _customer_action_recommendation(row, today=today),
    }


def _period_params(start_date: date | None, end_date: date | None, today: date) -> tuple[date | None, date | None]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date no puede ser mayor que end_date")
    if start_date or end_date:
        return start_date, end_date
    return None, today


def _previous_period(start_date: date | None, end_date: date | None) -> tuple[date | None, date | None]:
    if not start_date or not end_date:
        return None, None
    days = (end_date - start_date).days + 1
    previous_end = start_date - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    return previous_start, previous_end


def _rank_top_ids(rows: list[dict], *, percent: Decimal, key: str) -> set[int]:
    valued = [row for row in rows if _money(row.get(key)) > 0]
    if not valued:
        return set()
    count = max(int((Decimal(len(valued)) * percent / Decimal("100")).to_integral_value(rounding=ROUND_CEILING)), 1)
    sorted_rows = sorted(valued, key=lambda row: (_money(row.get(key)), int(row["customer_id"])), reverse=True)
    return {int(row["customer_id"]) for row in sorted_rows[:count]}


def _customer_metric_rows(
    db: Session,
    *,
    empresa_id: int,
    start_date: date | None,
    end_date: date | None,
    today: date,
) -> list[dict]:
    rows = db.execute(
        text(
            """
            WITH valid_orders AS (
                SELECT
                    p.id_pedido,
                    p.cliente_id,
                    p.fecha_pedido,
                    COALESCE(p.total_neto, p.total_bruto, 0)::numeric AS total_amount
                FROM petalops.pedido p
                LEFT JOIN petalops.estado_pedido ep
                  ON ep.id_estado_pedido = p.estado_pedido_id
                WHERE p.empresa_id = :empresa_id
                  AND p.cliente_id IS NOT NULL
                  AND (
                    ep.nombre_estado IS NULL
                    OR UPPER(TRIM(ep.nombre_estado)) NOT IN (
                        'CANCELADO', 'CANCELLED', 'RECHAZADO', 'REFUNDED', 'VOID', 'ANULADO'
                    )
                  )
            ),
            ordered_orders AS (
                SELECT
                    vo.*,
                    LAG(vo.fecha_pedido) OVER (
                        PARTITION BY vo.cliente_id
                        ORDER BY vo.fecha_pedido ASC, vo.id_pedido ASC
                    ) AS previous_purchase_at
                FROM valid_orders vo
            ),
            history AS (
                SELECT
                    cliente_id,
                    COUNT(*)::int AS purchase_count,
                    COALESCE(SUM(total_amount), 0)::numeric AS total_spent,
                    COALESCE(AVG(total_amount), 0)::numeric AS average_order_value,
                    MIN(fecha_pedido) AS first_purchase_at,
                    MAX(fecha_pedido) AS last_purchase_at
                FROM valid_orders
                GROUP BY cliente_id
            ),
            intervals AS (
                SELECT
                    cliente_id,
                    AVG(EXTRACT(EPOCH FROM (fecha_pedido - previous_purchase_at)) / 86400.0)::numeric
                        AS average_days_between_purchases
                FROM ordered_orders
                WHERE previous_purchase_at IS NOT NULL
                GROUP BY cliente_id
            ),
            period_orders AS (
                SELECT *
                FROM valid_orders
                WHERE (:start_date IS NULL OR fecha_pedido::date >= :start_date)
                  AND (:end_date IS NULL OR fecha_pedido::date <= :end_date)
            ),
            period_history AS (
                SELECT
                    cliente_id,
                    COUNT(*)::int AS period_purchase_count,
                    COALESCE(SUM(total_amount), 0)::numeric AS period_total_spent,
                    COALESCE(AVG(total_amount), 0)::numeric AS period_average_order_value
                FROM period_orders
                GROUP BY cliente_id
            ),
            product_preferences AS (
                SELECT cliente_id, nombre_producto AS favorite_product
                FROM (
                    SELECT
                        vo.cliente_id,
                        pr.nombre_producto,
                        ROW_NUMBER() OVER (
                            PARTITION BY vo.cliente_id
                            ORDER BY COALESCE(SUM(pd.subtotal), 0) DESC,
                                     COALESCE(SUM(pd.cantidad), 0) DESC,
                                     pr.nombre_producto ASC
                        ) AS rn
                    FROM valid_orders vo
                    JOIN petalops.pedido_detalle pd
                      ON pd.pedido_id = vo.id_pedido
                    JOIN petalops.producto pr
                      ON pr.id_producto = pd.producto_id
                     AND pr.empresa_id = :empresa_id
                    WHERE pd.empresa_id = :empresa_id
                    GROUP BY vo.cliente_id, pr.nombre_producto
                ) ranked
                WHERE rn = 1
            ),
            category_preferences AS (
                SELECT cliente_id, nombre AS favorite_category
                FROM (
                    SELECT
                        vo.cliente_id,
                        cat.nombre,
                        ROW_NUMBER() OVER (
                            PARTITION BY vo.cliente_id
                            ORDER BY COALESCE(SUM(pd.subtotal), 0) DESC,
                                     COALESCE(SUM(pd.cantidad), 0) DESC,
                                     cat.nombre ASC
                        ) AS rn
                    FROM valid_orders vo
                    JOIN petalops.pedido_detalle pd
                      ON pd.pedido_id = vo.id_pedido
                    JOIN petalops.producto pr
                      ON pr.id_producto = pd.producto_id
                     AND pr.empresa_id = :empresa_id
                    JOIN petalops.categoria cat
                      ON cat.id_categoria = pr.categoria_id
                     AND cat.empresa_id = :empresa_id
                    WHERE pd.empresa_id = :empresa_id
                    GROUP BY vo.cliente_id, cat.nombre
                ) ranked
                WHERE rn = 1
            ),
            channel_preferences AS (
                SELECT cliente_id, nombre AS preferred_channel
                FROM (
                    SELECT
                        vo.cliente_id,
                        cv.nombre,
                        ROW_NUMBER() OVER (
                            PARTITION BY vo.cliente_id
                            ORDER BY COUNT(*) DESC,
                                     COALESCE(SUM(vo.total_amount), 0) DESC,
                                     cv.nombre ASC
                        ) AS rn
                    FROM valid_orders vo
                    JOIN petalops.pedido_canal_venta pcv
                      ON pcv.pedido_id = vo.id_pedido
                     AND pcv.empresa_id = :empresa_id
                    JOIN petalops.canal_venta cv
                      ON cv.id_canal_venta = pcv.canal_venta_id
                     AND cv.empresa_id = :empresa_id
                    GROUP BY vo.cliente_id, cv.nombre
                ) ranked
                WHERE rn = 1
            )
            SELECT
                c.cliente_id,
                c.empresa_id,
                c.nombre_completo,
                c.identificacion,
                c.telefono,
                c.telefono_completo,
                c.email,
                c.fecha_cumpleanos,
                c.fecha_aniversario,
                COALESCE(h.purchase_count, 0)::int AS purchase_count,
                COALESCE(h.total_spent, 0)::numeric AS total_spent,
                COALESCE(h.average_order_value, 0)::numeric AS average_order_value,
                h.first_purchase_at,
                h.last_purchase_at,
                i.average_days_between_purchases,
                COALESCE(ph.period_purchase_count, 0)::int AS period_purchase_count,
                COALESCE(ph.period_total_spent, 0)::numeric AS period_total_spent,
                COALESCE(ph.period_average_order_value, 0)::numeric AS period_average_order_value,
                pp.favorite_product,
                cp.favorite_category,
                chp.preferred_channel
            FROM petalops.cliente c
            LEFT JOIN history h ON h.cliente_id = c.cliente_id
            LEFT JOIN intervals i ON i.cliente_id = c.cliente_id
            LEFT JOIN period_history ph ON ph.cliente_id = c.cliente_id
            LEFT JOIN product_preferences pp ON pp.cliente_id = c.cliente_id
            LEFT JOIN category_preferences cp ON cp.cliente_id = c.cliente_id
            LEFT JOIN channel_preferences chp ON chp.cliente_id = c.cliente_id
            WHERE c.empresa_id = :empresa_id
            """
        ),
        {
            "empresa_id": int(empresa_id),
            "start_date": start_date,
            "end_date": end_date,
        },
    ).mappings().all()

    metric_rows = []
    for row in rows:
        item = dict(row)
        item["customer_id"] = int(item.pop("cliente_id"))
        item["name"] = str(item.pop("nombre_completo") or "").strip()
        item["days_since_last_purchase"] = _days_since(item.get("last_purchase_at"), today)
        item["average_price_range"] = _average_price_range(item.get("average_order_value"))
        item["preferred_occasion"] = None
        metric_rows.append(item)
    return metric_rows


def _decorate_customer_segments(
    rows: list[dict],
    *,
    start_date: date | None,
    end_date: date | None,
    today: date,
) -> list[dict]:
    vip_ids = _rank_top_ids(rows, percent=CUSTOMER_VIP_TOP_PERCENT, key="total_spent")
    high_value_ids = _rank_top_ids(rows, percent=CUSTOMER_HIGH_VALUE_TOP_PERCENT, key="total_spent")
    active_cutoff = today - timedelta(days=CUSTOMER_ACTIVE_DAYS)
    inactive_cutoff = today - timedelta(days=CUSTOMER_INACTIVE_DAYS)

    for row in rows:
        segments = []
        first_purchase = _date_or_none(row.get("first_purchase_at"))
        last_purchase = _date_or_none(row.get("last_purchase_at"))
        purchase_count = int(row.get("purchase_count") or 0)
        customer_id = int(row["customer_id"])

        if first_purchase and (start_date is None or first_purchase >= start_date) and (end_date is None or first_purchase <= end_date):
            segments.append("NEW")
        if last_purchase and last_purchase >= active_cutoff:
            segments.append("ACTIVE")
        if purchase_count >= 2:
            segments.append("RECURRING")
        if customer_id in vip_ids:
            segments.append("VIP")
        if purchase_count > 0 and (not last_purchase or last_purchase < inactive_cutoff):
            segments.append("INACTIVE")

        avg_days = row.get("average_days_between_purchases")
        days_since = row.get("days_since_last_purchase")
        if purchase_count >= 2 and avg_days is not None and days_since is not None:
            if Decimal(str(days_since)) > Decimal(str(avg_days)) * CUSTOMER_AT_RISK_MULTIPLIER:
                segments.append("AT_RISK")
        if customer_id in high_value_ids:
            segments.append("HIGH_VALUE")

        row["segments"] = segments
        row["intelligence"] = _customer_intelligence(row, today=today)
    return rows


def _customer_metrics_payload(
    db: Session,
    *,
    empresa_id: int,
    start_date: date | None,
    end_date: date | None,
    today: date,
) -> dict:
    period_start, period_end = _period_params(start_date, end_date, today)
    rows = _decorate_customer_segments(
        _customer_metric_rows(
            db,
            empresa_id=empresa_id,
            start_date=period_start,
            end_date=period_end,
            today=today,
        ),
        start_date=period_start,
        end_date=period_end,
        today=today,
    )

    total_clients = len(rows)
    buyers = sum(1 for row in rows if int(row.get("purchase_count") or 0) > 0)
    recurring = sum(1 for row in rows if "RECURRING" in row["segments"])
    period_orders = sum(int(row.get("period_purchase_count") or 0) for row in rows)
    total_revenue = sum((_money(row.get("period_total_spent")) for row in rows), Decimal("0.00"))
    recurring_revenue = sum(
        (_money(row.get("period_total_spent")) for row in rows if "RECURRING" in row["segments"]),
        Decimal("0.00"),
    )
    lifetime_revenue = sum((_money(row.get("total_spent")) for row in rows), Decimal("0.00"))
    buyers_rows = [row for row in rows if int(row.get("purchase_count") or 0) > 0]
    health_values = [Decimal(str(row.get("intelligence", {}).get("customer_health_score", 0))) for row in buyers_rows]
    churn_values = [Decimal(str(row.get("intelligence", {}).get("churn_risk_probability", 0))) for row in buyers_rows]
    repurchase_values = [Decimal(str(row.get("intelligence", {}).get("repurchase_probability", 0))) for row in buyers_rows]

    payload = {
        "period": {
            "start_date": period_start.isoformat() if period_start else None,
            "end_date": period_end.isoformat() if period_end else None,
        },
        "customers": {
            "total": total_clients,
            "buyers": buyers,
            "non_buyers": max(total_clients - buyers, 0),
            "new": sum(1 for row in rows if "NEW" in row["segments"]),
            "recurring": recurring,
            "repeat_rate": _pct(recurring, buyers),
        },
        "activity": {
            "active_30d": sum(1 for row in rows if (row.get("days_since_last_purchase") is not None and row["days_since_last_purchase"] <= 30)),
            "active_60d": sum(1 for row in rows if (row.get("days_since_last_purchase") is not None and row["days_since_last_purchase"] <= 60)),
            "active_90d": sum(1 for row in rows if "ACTIVE" in row["segments"]),
            "inactive": sum(1 for row in rows if "INACTIVE" in row["segments"]),
            "at_risk": sum(1 for row in rows if "AT_RISK" in row["segments"]),
        },
        "value": {
            "total_revenue": float(total_revenue),
            "lifetime_revenue": float(lifetime_revenue),
            "average_order_value": float(_money(total_revenue / Decimal(period_orders))) if period_orders else 0.0,
            "average_customer_value": float(_money(total_revenue / Decimal(buyers))) if buyers else 0.0,
            "average_lifetime_value": float(_money(lifetime_revenue / Decimal(buyers))) if buyers else 0.0,
            "vip_customers": sum(1 for row in rows if "VIP" in row["segments"]),
            "recurring_revenue_percentage": _pct(recurring_revenue, total_revenue),
        },
        "frequency": {
            "average_purchases_per_customer": float((Decimal(period_orders) / Decimal(buyers)).quantize(Decimal("0.01"))) if buyers else 0.0,
            "average_days_between_purchases": float(
                (
                    sum((Decimal(str(row["average_days_between_purchases"])) for row in rows if row.get("average_days_between_purchases") is not None), Decimal("0.00"))
                    / Decimal(sum(1 for row in rows if row.get("average_days_between_purchases") is not None))
                ).quantize(Decimal("0.01"))
            )
            if any(row.get("average_days_between_purchases") is not None for row in rows)
            else 0.0,
        },
        "special_dates": {
            "customers_with_special_dates": sum(1 for row in rows if row.get("fecha_cumpleanos") or row.get("fecha_aniversario")),
            "special_dates_next_7d": len(_customer_special_date_opportunities(rows, today=today, max_days=7)),
            "special_dates_next_30d": len(_customer_special_date_opportunities(rows, today=today, max_days=30)),
            "special_dates_next_60d": len(_customer_special_date_opportunities(rows, today=today, max_days=60)),
            "customers_without_special_date": sum(1 for row in rows if not row.get("fecha_cumpleanos") and not row.get("fecha_aniversario")),
        },
        "intelligence": {
            "average_customer_health_score": float((sum(health_values, Decimal("0")) / Decimal(len(health_values))).quantize(Decimal("0.01"))) if health_values else 0.0,
            "average_churn_risk_probability": float((sum(churn_values, Decimal("0")) / Decimal(len(churn_values))).quantize(Decimal("0.01"))) if churn_values else 0.0,
            "average_repurchase_probability": float((sum(repurchase_values, Decimal("0")) / Decimal(len(repurchase_values))).quantize(Decimal("0.01"))) if repurchase_values else 0.0,
            "high_churn_risk_customers": sum(1 for row in buyers_rows if Decimal(str(row.get("intelligence", {}).get("churn_risk_probability", 0))) >= CUSTOMER_CHURN_HIGH_RISK_THRESHOLD),
            "likely_to_repurchase_customers": sum(1 for row in buyers_rows if Decimal(str(row.get("intelligence", {}).get("repurchase_probability", 0))) >= CUSTOMER_REPURCHASE_HIGH_PROBABILITY_THRESHOLD),
            "recommended_reactivation_customers": sum(1 for row in rows if row.get("intelligence", {}).get("next_best_action", {}).get("action") == "REACTIVATE"),
            "recommended_special_date_campaigns": sum(1 for row in rows if row.get("intelligence", {}).get("next_best_action", {}).get("action") == "SPECIAL_DATE_CAMPAIGN"),
            "recommended_vip_care_customers": sum(1 for row in rows if row.get("intelligence", {}).get("next_best_action", {}).get("action") == "VIP_CARE"),
        },
    }
    payload["insights"] = _customer_insights(payload)
    return payload


def _customer_insights(payload: dict) -> list[dict]:
    activity = payload.get("activity") or {}
    customers = payload.get("customers") or {}
    value = payload.get("value") or {}
    special_dates = payload.get("special_dates") or {}
    intelligence = payload.get("intelligence") or {}
    insights = []

    at_risk = int(activity.get("at_risk") or 0)
    if at_risk > 0:
        insights.append(
            {
                "code": "CUSTOMERS_AT_RISK",
                "message": f"{at_risk} clientes estan en riesgo de abandono.",
                "metric": "activity.at_risk",
                "value": at_risk,
                "segment": "AT_RISK",
            }
        )

    special_next_30d = int(special_dates.get("special_dates_next_30d") or 0)
    if special_next_30d > 0:
        insights.append(
            {
                "code": "SPECIAL_DATES_NEXT_30D",
                "message": f"{special_next_30d} fechas especiales ocurren en los proximos 30 dias.",
                "metric": "special_dates.special_dates_next_30d",
                "value": special_next_30d,
                "segment": None,
            }
        )

    recurring = int(customers.get("recurring") or 0)
    if recurring > 0:
        insights.append(
            {
                "code": "RECURRING_CUSTOMERS",
                "message": f"{recurring} clientes han comprado mas de una vez.",
                "metric": "customers.recurring",
                "value": recurring,
                "segment": "RECURRING",
            }
        )

    recurring_revenue_percentage = float(value.get("recurring_revenue_percentage") or 0)
    if recurring_revenue_percentage > 0:
        insights.append(
            {
                "code": "RECURRING_REVENUE",
                "message": f"El {recurring_revenue_percentage:.0f}% de la facturacion proviene de clientes recurrentes.",
                "metric": "value.recurring_revenue_percentage",
                "value": recurring_revenue_percentage,
                "segment": "RECURRING",
            }
        )

    vip_customers = int(value.get("vip_customers") or 0)
    if vip_customers > 0:
        insights.append(
            {
                "code": "VIP_CUSTOMERS",
                "message": f"{vip_customers} clientes representan el grupo de mayor valor.",
                "metric": "value.vip_customers",
                "value": vip_customers,
                "segment": "VIP",
            }
        )

    reactivation = int(intelligence.get("recommended_reactivation_customers") or 0)
    if reactivation > 0:
        insights.append(
            {
                "code": "REACTIVATION_RECOMMENDED",
                "message": f"{reactivation} clientes deberian priorizarse para reactivacion.",
                "metric": "intelligence.recommended_reactivation_customers",
                "value": reactivation,
                "segment": "AT_RISK",
            }
        )
    return insights


def _comparison_value(current, previous) -> dict:
    current_decimal = Decimal(str(current or 0))
    previous_decimal = Decimal(str(previous or 0))
    if previous_decimal == 0:
        change = Decimal("0.00") if current_decimal == 0 else Decimal("100.00")
    else:
        change = ((current_decimal - previous_decimal) / previous_decimal * Decimal("100")).quantize(Decimal("0.01"))
    direction = "flat"
    if current_decimal > previous_decimal:
        direction = "up"
    elif current_decimal < previous_decimal:
        direction = "down"
    return {
        "current": float(current_decimal) if isinstance(current, float) else int(current_decimal) if current_decimal == current_decimal.to_integral_value() else float(current_decimal),
        "previous": float(previous_decimal) if isinstance(previous, float) else int(previous_decimal) if previous_decimal == previous_decimal.to_integral_value() else float(previous_decimal),
        "change": float(change),
        "direction": direction,
    }


def _with_comparison(current_payload: dict, previous_payload: dict) -> dict:
    comparison = {}
    for section in ("customers", "activity", "value", "frequency", "special_dates", "intelligence"):
        comparison[section] = {
            key: _comparison_value(value, previous_payload.get(section, {}).get(key, 0))
            for key, value in current_payload.get(section, {}).items()
        }
    return {**current_payload, "comparison": comparison}


def _customer_metric_item(row: dict) -> dict:
    purchase_count = int(row.get("purchase_count") or 0)
    total_spent = _money(row.get("total_spent"))
    return {
        "customer_id": str(row["customer_id"]),
        "clienteID": int(row["customer_id"]),
        "name": row.get("name") or "",
        "nombreCompleto": row.get("name") or "",
        "identificacion": row.get("identificacion"),
        "telefono": row.get("telefono"),
        "telefonoCompleto": row.get("telefono_completo"),
        "email": row.get("email"),
        "purchase_count": purchase_count,
        "total_spent": float(total_spent),
        "lifetime_value": float(total_spent),
        "average_order_value": float(_money(row.get("average_order_value"))),
        "average_price_range": _average_price_range(row.get("average_order_value")),
        "first_purchase_at": _metric_date(row.get("first_purchase_at")),
        "last_purchase_at": _metric_date(row.get("last_purchase_at")),
        "days_since_last_purchase": row.get("days_since_last_purchase"),
        "average_days_between_purchases": (
            float(Decimal(str(row["average_days_between_purchases"])).quantize(Decimal("0.01")))
            if row.get("average_days_between_purchases") is not None
            else None
        ),
        "customer_segment": row.get("segments", []),
        "segments": row.get("segments", []),
        "favorite_product": row.get("favorite_product"),
        "favorite_category": row.get("favorite_category"),
        "preferred_occasion": None,
        "preferred_channel": row.get("preferred_channel"),
        "intelligence": row.get("intelligence") or {},
    }


@router.get("/cliente/buscar/{empresaID}/{identificacion}", dependencies=[Depends(require_module_access("pedidos", "puedeVer"))])
def buscar_cliente(
    empresa_id: int = Path(alias="empresaID"),
    identificacion: str = Path(...),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    cliente = (
        db.query(Cliente)
        .filter(
            Cliente.empresaID == empresa_id,
            Cliente.identificacion == identificacion,
        )
        .first()
    )

    if not cliente:
        return {"existe": False}

    return {
        "existe": True,
        "cliente": {
            "tipoIdent": cliente.tipoIdent,
            "nombreCompleto": cliente.nombreCompleto,
            "indicativo": cliente.indicativo,
            "telefono": cliente.telefono,
            "telefonoCompleto": cliente.telefonoCompleto,
            "email": cliente.email,
            "fechaCumpleanos": cliente.fechaCumpleanos.isoformat() if cliente.fechaCumpleanos else None,
            "fechaAniversario": cliente.fechaAniversario.isoformat() if cliente.fechaAniversario else None,
        },
    }


@router.get("/tenants/{tenant_id}/customers/metrics", dependencies=[Depends(require_module_access("pedidos", "puedeVer"))])
def obtener_metricas_clientes_tenant(
    tenant_id: int,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    comparison: bool = Query(default=False),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    empresa_id = _resolve_empresa_id(auth, int(tenant_id))
    today = datetime.now(timezone.utc).date()
    payload = _customer_metrics_payload(
        db,
        empresa_id=empresa_id,
        start_date=start_date,
        end_date=end_date,
        today=today,
    )
    if not comparison:
        return payload

    period_start, period_end = _period_params(start_date, end_date, today)
    previous_start, previous_end = _previous_period(period_start, period_end)
    if previous_start is None or previous_end is None:
        return {**payload, "comparison": None}

    previous_payload = _customer_metrics_payload(
        db,
        empresa_id=empresa_id,
        start_date=previous_start,
        end_date=previous_end,
        today=today,
    )
    return _with_comparison(payload, previous_payload)


@router.get("/tenants/{tenant_id}/customers/segments", dependencies=[Depends(require_module_access("pedidos", "puedeVer"))])
def listar_clientes_por_segmento_tenant(
    tenant_id: int,
    segment: str = Query(...),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=500),
    search: str = Query(default=""),
    sort: str = Query(default="total_spent"),
    order: str = Query(default="desc"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    empresa_id = _resolve_empresa_id(auth, int(tenant_id))
    requested_segment = str(segment or "").strip().upper()
    if requested_segment not in CUSTOMER_SEGMENTS:
        raise HTTPException(status_code=400, detail=f"Segmento inválido: {segment}")

    today = datetime.now(timezone.utc).date()
    period_start, period_end = _period_params(start_date, end_date, today)
    rows = _decorate_customer_segments(
        _customer_metric_rows(
            db,
            empresa_id=empresa_id,
            start_date=period_start,
            end_date=period_end,
            today=today,
        ),
        start_date=period_start,
        end_date=period_end,
        today=today,
    )

    filtered = [row for row in rows if requested_segment in row.get("segments", [])]
    search_text = str(search or "").strip().lower()
    if search_text:
        filtered = [
            row
            for row in filtered
            if search_text in str(row.get("name") or "").lower()
            or search_text in str(row.get("identificacion") or "").lower()
            or search_text in str(row.get("telefono") or "").lower()
            or search_text in str(row.get("telefono_completo") or "").lower()
            or search_text in str(row.get("email") or "").lower()
        ]

    sort_key = sort if sort in CUSTOMER_METRIC_SORTS else "total_spent"
    reverse = str(order or "desc").lower() != "asc"

    def _segment_sort_value(row: dict):
        value_key = "total_spent" if sort_key == "lifetime_value" else sort_key
        value = row.get(value_key)
        if sort_key == "name":
            return str(value or "").lower()
        if sort_key in {"total_spent", "average_order_value", "lifetime_value"}:
            return _money(value)
        return value

    filtered.sort(
        key=lambda row: (
            _segment_sort_value(row) is None,
            _segment_sort_value(row),
        ),
        reverse=reverse,
    )
    total = len(filtered)
    start = (page - 1) * limit
    items = filtered[start : start + limit]
    return {
        "segment": requested_segment,
        "total": total,
        "page": page,
        "limit": limit,
        "data": [_customer_metric_item(row) for row in items],
    }


@router.get("/tenants/{tenant_id}/customers/opportunities", dependencies=[Depends(require_module_access("pedidos", "puedeVer"))])
def listar_oportunidades_clientes_tenant(
    tenant_id: int,
    days: int = Query(default=60, ge=1, le=365),
    occasion: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=500),
    search: str = Query(default=""),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    empresa_id = _resolve_empresa_id(auth, int(tenant_id))
    today = datetime.now(timezone.utc).date()
    rows = _decorate_customer_segments(
        _customer_metric_rows(
            db,
            empresa_id=empresa_id,
            start_date=None,
            end_date=today,
            today=today,
        ),
        start_date=None,
        end_date=today,
        today=today,
    )
    opportunities = _customer_special_date_opportunities(rows, today=today, max_days=int(days))

    requested_occasion = str(occasion or "").strip().upper()
    if requested_occasion:
        opportunities = [item for item in opportunities if item["occasion"] == requested_occasion]

    search_text = str(search or "").strip().lower()
    if search_text:
        opportunities = [
            item
            for item in opportunities
            if search_text in str(item.get("name") or "").lower()
            or search_text in str(item.get("customer_id") or "").lower()
        ]

    total = len(opportunities)
    start = (page - 1) * limit
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "days": int(days),
        "data": opportunities[start : start + limit],
    }


@router.get("/tenants/{tenant_id}/customers/{customer_id}/metrics", dependencies=[Depends(require_module_access("pedidos", "puedeVer"))])
def obtener_metricas_cliente_tenant(
    tenant_id: int,
    customer_id: int,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    empresa_id = _resolve_empresa_id(auth, int(tenant_id))
    today = datetime.now(timezone.utc).date()
    period_start, period_end = _period_params(start_date, end_date, today)
    rows = _decorate_customer_segments(
        _customer_metric_rows(
            db,
            empresa_id=empresa_id,
            start_date=period_start,
            end_date=period_end,
            today=today,
        ),
        start_date=period_start,
        end_date=period_end,
        today=today,
    )
    item = next((row for row in rows if int(row["customer_id"]) == int(customer_id)), None)
    if not item:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return {
        "period": {
            "start_date": period_start.isoformat() if period_start else None,
            "end_date": period_end.isoformat() if period_end else None,
        },
        "customer": _customer_metric_item(item),
    }


@router.get("/tenants/{tenant_id}/customers/intelligence", dependencies=[Depends(require_module_access("pedidos", "puedeVer"))])
def listar_inteligencia_clientes_tenant(
    tenant_id: int,
    action: str | None = Query(default=None),
    risk: str | None = Query(default=None),
    min_health_score: float | None = Query(default=None, ge=0, le=100),
    max_health_score: float | None = Query(default=None, ge=0, le=100),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=500),
    search: str = Query(default=""),
    sort: str = Query(default="churn_risk_probability"),
    order: str = Query(default="desc"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    empresa_id = _resolve_empresa_id(auth, int(tenant_id))
    today = datetime.now(timezone.utc).date()
    rows = _decorate_customer_segments(
        _customer_metric_rows(
            db,
            empresa_id=empresa_id,
            start_date=None,
            end_date=today,
            today=today,
        ),
        start_date=None,
        end_date=today,
        today=today,
    )

    requested_action = str(action or "").strip().upper()
    if requested_action:
        rows = [
            row
            for row in rows
            if row.get("intelligence", {}).get("next_best_action", {}).get("action") == requested_action
        ]

    requested_risk = str(risk or "").strip().upper()
    if requested_risk == "HIGH":
        rows = [
            row
            for row in rows
            if Decimal(str(row.get("intelligence", {}).get("churn_risk_probability", 0))) >= CUSTOMER_CHURN_HIGH_RISK_THRESHOLD
        ]
    elif requested_risk == "LOW":
        rows = [
            row
            for row in rows
            if Decimal(str(row.get("intelligence", {}).get("churn_risk_probability", 0))) < CUSTOMER_CHURN_HIGH_RISK_THRESHOLD
        ]
    elif requested_risk:
        raise HTTPException(status_code=400, detail="risk debe ser HIGH o LOW")

    if min_health_score is not None:
        rows = [
            row
            for row in rows
            if Decimal(str(row.get("intelligence", {}).get("customer_health_score", 0))) >= Decimal(str(min_health_score))
        ]
    if max_health_score is not None:
        rows = [
            row
            for row in rows
            if Decimal(str(row.get("intelligence", {}).get("customer_health_score", 0))) <= Decimal(str(max_health_score))
        ]

    search_text = str(search or "").strip().lower()
    if search_text:
        rows = [
            row
            for row in rows
            if search_text in str(row.get("name") or "").lower()
            or search_text in str(row.get("identificacion") or "").lower()
            or search_text in str(row.get("telefono") or "").lower()
            or search_text in str(row.get("telefono_completo") or "").lower()
            or search_text in str(row.get("email") or "").lower()
        ]

    intelligence_sorts = {
        "customer_health_score",
        "churn_risk_probability",
        "repurchase_probability",
        "total_spent",
        "last_purchase_at",
        "name",
    }
    sort_key = sort if sort in intelligence_sorts else "churn_risk_probability"
    reverse = str(order or "desc").lower() != "asc"

    def _intelligence_sort_value(row: dict):
        if sort_key in {"customer_health_score", "churn_risk_probability", "repurchase_probability"}:
            return Decimal(str(row.get("intelligence", {}).get(sort_key, 0)))
        if sort_key == "total_spent":
            return _money(row.get("total_spent"))
        if sort_key == "name":
            return str(row.get("name") or "").lower()
        return row.get(sort_key)

    rows.sort(key=lambda row: (_intelligence_sort_value(row) is None, _intelligence_sort_value(row)), reverse=reverse)
    total = len(rows)
    start = (page - 1) * limit
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "data": [_customer_metric_item(row) for row in rows[start : start + limit]],
    }


@router.get("/clientes", dependencies=[Depends(require_module_access("pedidos", "puedeVer"))])
def list_clientes(
    empresa_id: int | None = Query(default=None, alias="empresaID"),
    q: str = Query(default=""),
    solo_activos: bool = Query(default=False, alias="soloActivos"),
    include_metrics: bool = Query(default=False, alias="includeMetrics"),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=3000, ge=1, le=5000, alias="pageSize"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    scoped_empresa_id = _resolve_empresa_id(auth, empresa_id)
    texto = str(q or "").strip()

    query = db.query(Cliente).filter(Cliente.empresaID == scoped_empresa_id)

    if solo_activos:
        query = query.filter(Cliente.activo.is_(True))

    if texto:
        like = f"%{texto}%"
        query = query.filter(
            or_(
                Cliente.nombreCompleto.ilike(like),
                Cliente.identificacion.ilike(like),
                Cliente.telefono.ilike(like),
                Cliente.telefonoCompleto.ilike(like),
                Cliente.email.ilike(like),
            )
        )

    total = query.count()
    clientes = (
        query
        .order_by(Cliente.updatedAt.desc().nullslast(), Cliente.idCliente.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [_cliente_to_dict(cliente) for cliente in clientes]
    if include_metrics and items:
        today = datetime.now(timezone.utc).date()
        period_start, period_end = _period_params(start_date, end_date, today)
        metric_rows = _decorate_customer_segments(
            _customer_metric_rows(
                db,
                empresa_id=scoped_empresa_id,
                start_date=period_start,
                end_date=period_end,
                today=today,
            ),
            start_date=period_start,
            end_date=period_end,
            today=today,
        )
        metrics_by_id = {int(row["customer_id"]): _customer_metric_item(row) for row in metric_rows}
        for item in items:
            item["metrics"] = metrics_by_id.get(int(item["clienteID"]))

    return {
        "items": items,
        "total": total,
        "page": page,
        "pageSize": page_size,
    }


@router.post("/clientes", dependencies=[Depends(require_module_access("pedidos", "puedeCrear"))])
def create_cliente(
    payload: ClientePayload,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    scoped_empresa_id = _resolve_empresa_id(auth, int(payload.empresaID))

    identificacion = str(payload.identificacion or "").strip()
    telefono_completo = str(payload.telefonoCompleto or "").strip() or None
    email = str(payload.email or "").strip().lower() or None

    existing = None
    if identificacion:
        existing = (
            db.query(Cliente)
            .filter(
                Cliente.empresaID == scoped_empresa_id,
                Cliente.identificacion == identificacion,
            )
            .first()
        )
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe un cliente con esa identificación")

    now = datetime.now(timezone.utc)
    cliente = Cliente(
        empresaID=scoped_empresa_id,
        tipoIdent=str(payload.tipoIdent or "").strip() or None,
        identificacion=identificacion or None,
        indicativo=str(payload.indicativo or "").strip() or None,
        nombreCompleto=str(payload.nombreCompleto or "").strip(),
        telefono=str(payload.telefono or "").strip() or None,
        telefonoCompleto=telefono_completo,
        email=email,
        fechaCumpleanos=payload.fechaCumpleanos,
        fechaAniversario=payload.fechaAniversario,
        activo=1 if bool(payload.activo) else 0,
        createdAt=now,
        updatedAt=now,
    )
    db.add(cliente)
    db.commit()
    db.refresh(cliente)

    return {"status": "ok", "cliente": _cliente_to_dict(cliente)}


@router.put("/clientes/{cliente_id}", dependencies=[Depends(require_module_access("pedidos", "puedeEditar"))])
def update_cliente(
    cliente_id: int,
    payload: ClienteUpdatePayload,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    if not is_empresa_admin_context(auth) and not is_super_admin_context(auth):
        raise HTTPException(status_code=403, detail="Solo administradores pueden editar clientes")

    scoped_empresa_id = _resolve_empresa_id(auth, int(payload.empresaID))

    cliente = (
        db.query(Cliente)
        .filter(
            Cliente.idCliente == int(cliente_id),
            Cliente.empresaID == scoped_empresa_id,
        )
        .first()
    )
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    identificacion = str(payload.identificacion or "").strip() or None
    if identificacion:
        existing = (
            db.query(Cliente)
            .filter(
                Cliente.empresaID == scoped_empresa_id,
                Cliente.identificacion == identificacion,
                Cliente.idCliente != int(cliente_id),
            )
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="Ya existe otro cliente con esa identificación")

    cliente.tipoIdent = str(payload.tipoIdent or "").strip() or None
    cliente.identificacion = identificacion
    cliente.indicativo = str(payload.indicativo or "").strip() or None
    cliente.nombreCompleto = str(payload.nombreCompleto or "").strip()
    cliente.telefono = str(payload.telefono or "").strip() or None
    cliente.telefonoCompleto = str(payload.telefonoCompleto or "").strip() or None
    cliente.email = str(payload.email or "").strip().lower() or None
    cliente.fechaCumpleanos = payload.fechaCumpleanos
    cliente.fechaAniversario = payload.fechaAniversario
    cliente.activo = 1 if bool(payload.activo) else 0
    cliente.updatedAt = datetime.now(timezone.utc)
    db.commit()
    db.refresh(cliente)

    return {"status": "ok", "cliente": _cliente_to_dict(cliente)}
