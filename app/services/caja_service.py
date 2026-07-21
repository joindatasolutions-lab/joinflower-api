from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session


def money(value) -> Decimal:
    return Decimal(str(value or 0))


def calculate_nueva_base(
    *,
    base_inicial: Decimal,
    efectivo_ventas: Decimal,
    total_gastos: Decimal,
    monto_guardado: Decimal,
) -> Decimal:
    return base_inicial + efectivo_ventas - total_gastos - monto_guardado


def relation_exists(db: Session, relation_name: str) -> bool:
    row = db.execute(
        text("SELECT to_regclass(:relation_name) IS NOT NULL"),
        {"relation_name": f"petalops.{relation_name}"},
    ).first()
    return bool(row and row[0])


def column_exists(db: Session, table_name: str, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'petalops'
              AND table_name = :table_name
              AND column_name = :column_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    return bool(row)


def caja_totales_sql(*, single_day: bool) -> str:
    date_filter = (
        "AND fecha = :fecha_operacion" if single_day else "AND fecha BETWEEN :fecha_desde AND :fecha_hasta"
    )
    return f"""
        SELECT fecha,
               base,
               efectivo,
               gasto,
               total_efectivo,
               guardado,
               nueva_base,
               observacion
        FROM petalops.caja
        WHERE empresa_id = :empresa_id
          AND sucursal_id = :sucursal_id
          {date_filter}
        ORDER BY fecha DESC
    """


def load_efectivo_ventas(db: Session, *, empresa_id: int, sucursal_id: int, fecha_operacion: date) -> Decimal:
    total = Decimal("0")

    has_phase2_amounts = (
        relation_exists(db, "pago_metodo")
        and relation_exists(db, "metodo_pago_catalogo")
        and column_exists(db, "pago_metodo", "monto")
    )

    if has_phase2_amounts:
        row = db.execute(
            text(
                """
                SELECT COALESCE(SUM(pm.monto), 0)
                FROM petalops.pago_metodo pm
                JOIN petalops.metodo_pago_catalogo mpc
                  ON mpc.id_metodo_pago = pm.metodo_pago_id
                 AND mpc.empresa_id = pm.empresa_id
                JOIN petalops.pedido p
                  ON p.id_pedido = pm.pedido_id
                 AND p.empresa_id = pm.empresa_id
                LEFT JOIN petalops.estado_pedido ep
                  ON ep.id_estado_pedido = p.estado_pedido_id
                WHERE pm.empresa_id = :empresa_id
                  AND p.sucursal_id = :sucursal_id
                  AND CAST(p.fecha_pedido AS DATE) = :fecha_operacion
                  AND (
                    lower(COALESCE(mpc.codigo, '')) = 'efectivo'
                    OR lower(COALESCE(mpc.nombre, '')) = 'efectivo'
                  )
                  AND upper(COALESCE(ep.nombre_estado, '')) NOT IN ('CANCELADO', 'RECHAZADO', 'ANULADO')
                """
            ),
            {
                "empresa_id": int(empresa_id),
                "sucursal_id": int(sucursal_id),
                "fecha_operacion": fecha_operacion,
            },
        ).first()
        total += money(row[0] if row else 0)

    if total > 0:
        return total

    if relation_exists(db, "pago"):
        legacy_filter = ""
        if has_phase2_amounts:
            legacy_filter = """
                  AND NOT EXISTS (
                    SELECT 1
                    FROM petalops.pago_metodo pm
                    WHERE pm.empresa_id = pa.empresa_id
                      AND pm.pedido_id = pa.pedido_id
                  )
            """
        row = db.execute(
            text(
                f"""
                SELECT COALESCE(SUM(pa.monto), 0)
                FROM petalops.pago pa
                JOIN petalops.pedido p
                  ON p.id_pedido = pa.pedido_id
                 AND p.empresa_id = pa.empresa_id
                LEFT JOIN petalops.estado_pedido ep
                  ON ep.id_estado_pedido = p.estado_pedido_id
                WHERE pa.empresa_id = :empresa_id
                  AND p.sucursal_id = :sucursal_id
                  AND CAST(p.fecha_pedido AS DATE) = :fecha_operacion
                  AND COALESCE(pa.metodo_pago, '') ILIKE '%Efectivo%'
                  AND upper(COALESCE(ep.nombre_estado, '')) NOT IN ('CANCELADO', 'RECHAZADO', 'ANULADO')
                  {legacy_filter}
                """
            ),
            {
                "empresa_id": int(empresa_id),
                "sucursal_id": int(sucursal_id),
                "fecha_operacion": fecha_operacion,
            },
        ).first()
        total += money(row[0] if row else 0)

    return total


def load_base_anterior(db: Session, *, empresa_id: int, sucursal_id: int, fecha_operacion: date) -> Decimal:
    row = db.execute(
        text(
            """
            SELECT nueva_base
            FROM petalops.caja
            WHERE empresa_id = :empresa_id
              AND sucursal_id = :sucursal_id
              AND fecha < :fecha_operacion
            ORDER BY fecha DESC
            LIMIT 1
            """
        ),
        {
            "empresa_id": int(empresa_id),
            "sucursal_id": int(sucursal_id),
            "fecha_operacion": fecha_operacion,
        },
    ).first()
    return money(row[0] if row else 0)


def upsert_caja(
    db: Session,
    *,
    empresa_id: int,
    sucursal_id: int,
    fecha: date,
    base: Decimal,
    efectivo: Decimal,
    gasto: Decimal,
    total_efectivo: Decimal,
    guardado: Decimal,
    nueva_base: Decimal,
    observacion: str,
    usuario_id: int | None,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO petalops.caja (
                empresa_id,
                sucursal_id,
                fecha,
                base,
                efectivo,
                gasto,
                total_efectivo,
                guardado,
                nueva_base,
                observacion,
                usuario_id,
                updated_at
            )
            VALUES (
                :empresa_id,
                :sucursal_id,
                :fecha,
                :base,
                :efectivo,
                :gasto,
                :total_efectivo,
                :guardado,
                :nueva_base,
                :observacion,
                :usuario_id,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT (empresa_id, sucursal_id, fecha)
            DO UPDATE SET
                base = EXCLUDED.base,
                efectivo = EXCLUDED.efectivo,
                gasto = EXCLUDED.gasto,
                total_efectivo = EXCLUDED.total_efectivo,
                guardado = EXCLUDED.guardado,
                nueva_base = EXCLUDED.nueva_base,
                observacion = EXCLUDED.observacion,
                usuario_id = EXCLUDED.usuario_id,
                updated_at = CURRENT_TIMESTAMP
            """
        ),
        {
            "empresa_id": int(empresa_id),
            "sucursal_id": int(sucursal_id),
            "fecha": fecha,
            "base": base,
            "efectivo": efectivo,
            "gasto": gasto,
            "total_efectivo": total_efectivo,
            "guardado": guardado,
            "nueva_base": nueva_base,
            "observacion": observacion,
            "usuario_id": (int(usuario_id) if usuario_id is not None else None),
        },
    )


def refresh_caja_por_pedido(db: Session, *, pedido, usuario_id: int | None = None) -> None:
    if not pedido or not getattr(pedido, "fechaPedido", None):
        return

    empresa_id = int(pedido.empresaID)
    sucursal_id = int(pedido.sucursalID)
    fecha_operacion = pedido.fechaPedido.date()
    efectivo = load_efectivo_ventas(
        db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        fecha_operacion=fecha_operacion,
    )

    row = db.execute(
        text(
            """
            SELECT base, gasto, guardado, observacion, usuario_id
            FROM petalops.caja
            WHERE empresa_id = :empresa_id
              AND sucursal_id = :sucursal_id
              AND fecha = :fecha_operacion
            LIMIT 1
            """
        ),
        {
            "empresa_id": empresa_id,
            "sucursal_id": sucursal_id,
            "fecha_operacion": fecha_operacion,
        },
    ).mappings().first()

    base = money(row["base"] if row else None)
    if not row:
        base = load_base_anterior(
            db,
            empresa_id=empresa_id,
            sucursal_id=sucursal_id,
            fecha_operacion=fecha_operacion,
        )
    gasto = money(row["gasto"] if row else None)
    guardado = money(row["guardado"] if row else None)
    observacion = str(row["observacion"] or "") if row else ""
    resolved_usuario_id = usuario_id if usuario_id is not None else (row["usuario_id"] if row else None)
    total_efectivo = base + efectivo - gasto
    nueva_base = total_efectivo - guardado

    upsert_caja(
        db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        fecha=fecha_operacion,
        base=base,
        efectivo=efectivo,
        gasto=gasto,
        total_efectivo=total_efectivo,
        guardado=guardado,
        nueva_base=nueva_base,
        observacion=observacion,
        usuario_id=resolved_usuario_id,
    )
