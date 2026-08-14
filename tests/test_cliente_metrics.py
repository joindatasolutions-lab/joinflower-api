from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.routers.cliente import (
    CUSTOMER_COMMERCIAL_PRIORITIES,
    CUSTOMER_EFFECTIVE_PURCHASE_STATES,
    CUSTOMER_TEST_NAME_PATTERNS,
    _average_price_range,
    calculate_commercial_priority,
    _customer_insights,
    _customer_special_date_opportunities,
    _customer_intelligence,
    _customer_metric_item,
    _customer_metrics_payload,
    _customer_metric_rows,
    _decorate_customer_segments,
    listar_clientes_por_prioridad_comercial_tenant,
    _with_comparison,
)


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _MetricRowsDb:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, *_args, **_kwargs):
        return _RowsResult(self.rows)


class _CaptureSqlDb:
    def __init__(self):
        self.statement = ""
        self.params = {}

    def execute(self, statement, params=None):
        self.statement = str(statement)
        self.params = params or {}
        return _RowsResult([])


def _row(cliente_id, total_spent, purchase_count, first_purchase, last_purchase, avg_days=None, period_spent=None, period_purchase_count=None):
    return {
        "cliente_id": cliente_id,
        "empresa_id": 3,
        "nombre_completo": f"Cliente {cliente_id}",
        "identificacion": str(cliente_id),
        "telefono": "300",
        "telefono_completo": "57300",
        "email": None,
        "fecha_cumpleanos": None,
        "fecha_aniversario": None,
        "purchase_count": purchase_count,
        "total_spent": Decimal(str(total_spent)),
        "average_order_value": Decimal(str(total_spent / purchase_count)) if purchase_count else Decimal("0"),
        "first_purchase_at": first_purchase,
        "last_purchase_at": last_purchase,
        "average_days_between_purchases": avg_days,
        "period_purchase_count": purchase_count if period_purchase_count is None else period_purchase_count,
        "period_total_spent": Decimal(str(period_spent if period_spent is not None else total_spent)),
        "period_average_order_value": Decimal(str(total_spent / purchase_count)) if purchase_count else Decimal("0"),
        "favorite_product": "Ramo premium" if purchase_count else None,
        "favorite_category": "Arreglos" if purchase_count else None,
        "preferred_channel": "WhatsApp" if purchase_count else None,
    }


def test_customer_metric_rows_only_counts_approved_orders_as_effective_purchase():
    db = _CaptureSqlDb()

    _customer_metric_rows(
        db,
        empresa_id=3,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 8, 14),
        today=date(2026, 8, 14),
    )

    assert "ANY(:effective_purchase_states)" in db.statement
    assert db.params["effective_purchase_states"] == list(CUSTOMER_EFFECTIVE_PURCHASE_STATES)
    assert CUSTOMER_EFFECTIVE_PURCHASE_STATES == ("APROBADO",)
    assert "test_customer_name_patterns" in db.statement
    assert db.params["test_customer_name_patterns"] == list(CUSTOMER_TEST_NAME_PATTERNS)
    assert CUSTOMER_TEST_NAME_PATTERNS == ("%prueba%",)


def test_decorate_customer_segments_keeps_multiple_segments_and_commercial_priority():
    rows = [
        {
            "customer_id": 1,
            "name": "VIP",
            "purchase_count": 5,
            "total_spent": Decimal("1000000"),
            "first_purchase_at": date(2026, 1, 1),
            "last_purchase_at": date(2026, 3, 1),
            "average_days_between_purchases": Decimal("30"),
            "days_since_last_purchase": 166,
        },
        {
            "customer_id": 2,
            "name": "Activo",
            "purchase_count": 1,
            "total_spent": Decimal("100000"),
            "first_purchase_at": date(2026, 8, 1),
            "last_purchase_at": date(2026, 8, 1),
            "average_days_between_purchases": None,
            "days_since_last_purchase": 13,
        },
    ]

    result = _decorate_customer_segments(
        rows,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 14),
        today=date(2026, 8, 14),
    )

    assert {"VIP", "HIGH_VALUE", "RECURRING", "INACTIVE", "AT_RISK"}.issubset(set(result[0]["segments"]))
    assert result[0]["commercial_priority"] == "P0"
    assert result[0]["commercial_priority_label"] == "VIP en riesgo"
    assert {"NEW", "ACTIVE"}.issubset(set(result[1]["segments"]))
    assert result[1]["commercial_priority"] == "P6"
    assert result[1]["commercial_priority_label"] == "Cliente nuevo"


def test_calculate_commercial_priority_uses_business_priority_order():
    cases = [
        (["VIP", "AT_RISK"], "P0", "VIP en riesgo"),
        (["HIGH_VALUE", "AT_RISK"], "P1", "Alto valor en riesgo"),
        (["AT_RISK"], "P2", "Cliente en riesgo"),
        (["VIP", "INACTIVE"], "P3", "VIP inactivo"),
        (["HIGH_VALUE", "INACTIVE"], "P4", "Alto valor inactivo"),
        (["INACTIVE"], "P5", "Cliente inactivo"),
        (["NEW"], "P6", "Cliente nuevo"),
        (["RECURRING"], "P7", "Cliente recurrente"),
        (["ACTIVE"], "P8", "Cliente activo"),
        (["VIP", "RECURRING", "AT_RISK"], "P0", "VIP en riesgo"),
    ]

    for segments, expected_priority, expected_label in cases:
        priority = calculate_commercial_priority(segments)
        assert priority == {"priority": expected_priority, "label": expected_label}

    assert tuple(CUSTOMER_COMMERCIAL_PRIORITIES.keys()) == ("P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8")


def test_customer_metrics_payload_returns_p0_kpis():
    db = _MetricRowsDb(
        [
            _row(1, 1000, 2, date(2026, 1, 1), date(2026, 8, 1), avg_days=Decimal("30")),
            _row(2, 500, 1, date(2026, 8, 3), date(2026, 8, 3)),
            _row(3, 0, 0, None, None, period_spent=0),
        ]
    )

    payload = _customer_metrics_payload(
        db,
        empresa_id=3,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 14),
        today=date(2026, 8, 14),
    )

    assert payload["customers"]["total"] == 3
    assert payload["customers"]["buyers"] == 2
    assert payload["customers"]["non_buyers"] == 1
    assert payload["customers"]["recurring"] == 1
    assert payload["customers"]["repeat_rate"] == 50.0
    assert payload["activity"]["active_30d"] == 2
    assert payload["value"]["total_revenue"] == 1500.0
    assert payload["value"]["lifetime_revenue"] == 1500.0
    assert payload["value"]["average_lifetime_value"] == 750.0
    assert payload["commercial_priorities"]["P7"]["count"] == 1
    assert payload["commercial_priorities"]["P7"]["historical_value"] == 1000.0
    assert payload["commercial_priorities"]["P7"]["period_value"] == 1000.0
    assert payload["commercial_priorities"]["P6"]["count"] == 1
    assert payload["insights"]


def test_customer_priorities_endpoint_filters_and_totals_historical_value():
    db = _MetricRowsDb(
        [
            _row(1, 1000, 2, date(2026, 1, 1), date(2026, 8, 1), avg_days=Decimal("30")),
            _row(2, 500, 1, date(2026, 8, 3), date(2026, 8, 3)),
            _row(3, 900, 2, date(2026, 1, 1), date(2026, 7, 1), avg_days=Decimal("30"), period_spent=0, period_purchase_count=0),
        ]
    )

    payload = listar_clientes_por_prioridad_comercial_tenant(
        3,
        priority="P7",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 14),
        page=1,
        limit=50,
        search="",
        sort="total_spent",
        order="desc",
        db=db,
        auth=SimpleNamespace(empresaID=3, rol="USER", esGlobalJoin=False),
    )

    assert payload["priority"] == "P7"
    assert payload["label"] == "Cliente recurrente"
    assert payload["total"] == 1
    assert payload["total_historical_value"] == 1000.0
    assert payload["total_period_value"] == 1000.0
    assert payload["data"][0]["commercial_priority"] == "P7"


def test_with_comparison_wraps_metric_changes():
    current = {"customers": {"buyers": 12}, "activity": {}, "value": {"total_revenue": 1500.0}, "frequency": {}}
    previous = {"customers": {"buyers": 10}, "activity": {}, "value": {"total_revenue": 1000.0}, "frequency": {}}

    payload = _with_comparison(current, previous)

    assert payload["comparison"]["customers"]["buyers"]["direction"] == "up"
    assert payload["comparison"]["customers"]["buyers"]["change"] == 20.0
    assert payload["comparison"]["value"]["total_revenue"]["change"] == 50.0


def test_customer_special_date_opportunities_returns_upcoming_dates():
    rows = [
        {
            "customer_id": 1,
            "name": "Maria",
            "fecha_cumpleanos": date(1990, 8, 20),
            "fecha_aniversario": None,
            "last_purchase_at": date(2026, 5, 1),
            "total_spent": Decimal("850000"),
            "segments": ["VIP"],
        },
        {
            "customer_id": 2,
            "name": "Lejos",
            "fecha_cumpleanos": date(1990, 12, 20),
            "fecha_aniversario": None,
            "last_purchase_at": None,
            "total_spent": Decimal("0"),
            "segments": [],
        },
    ]

    opportunities = _customer_special_date_opportunities(rows, today=date(2026, 8, 14), max_days=30)

    assert len(opportunities) == 1
    assert opportunities[0]["occasion"] == "BIRTHDAY"
    assert opportunities[0]["date"] == "2026-08-20"
    assert opportunities[0]["days_remaining"] == 6


def test_customer_metric_item_includes_ltv_and_preferences():
    item = _customer_metric_item(
        {
            "customer_id": 10,
            "name": "Cliente",
            "purchase_count": 3,
            "total_spent": Decimal("900000"),
            "average_order_value": Decimal("300000"),
            "first_purchase_at": date(2026, 1, 1),
            "last_purchase_at": date(2026, 8, 1),
            "days_since_last_purchase": 13,
            "average_days_between_purchases": Decimal("70"),
            "segments": ["RECURRING", "VIP"],
            "favorite_product": "Ramo premium",
            "favorite_category": "Arreglos",
            "preferred_channel": "WhatsApp",
        }
    )

    assert item["lifetime_value"] == 900000.0
    assert item["favorite_product"] == "Ramo premium"
    assert item["favorite_category"] == "Arreglos"
    assert item["preferred_channel"] == "WhatsApp"
    assert item["average_price_range"] == "HIGH"
    assert item["preferred_occasion"] is None
    assert item["customer_segment"] == ["RECURRING", "VIP"]
    assert item["commercial_priority"] == "P7"
    assert item["commercial_priority_label"] == "Cliente recurrente"


def test_customer_insights_are_backed_by_metrics():
    insights = _customer_insights(
        {
            "customers": {"recurring": 624},
            "activity": {"at_risk": 173},
            "value": {"vip_customers": 184, "recurring_revenue_percentage": 67.4},
            "special_dates": {"special_dates_next_30d": 87},
            "intelligence": {"recommended_reactivation_customers": 173},
        }
    )

    codes = {item["code"] for item in insights}

    assert "CUSTOMERS_AT_RISK" in codes
    assert "SPECIAL_DATES_NEXT_30D" in codes
    assert "RECURRING_REVENUE" in codes


def test_average_price_range_uses_backend_thresholds():
    assert _average_price_range(0) is None
    assert _average_price_range(120000) == "LOW"
    assert _average_price_range(250000) == "MID"
    assert _average_price_range(250001) == "HIGH"


def test_customer_intelligence_recommends_first_purchase_for_non_buyer():
    intelligence = _customer_intelligence(
        {
            "customer_id": 20,
            "purchase_count": 0,
            "segments": [],
            "days_since_last_purchase": None,
            "average_days_between_purchases": None,
        },
        today=date(2026, 8, 14),
    )

    assert intelligence["customer_health_score"] == 20.0
    assert intelligence["repurchase_probability"] == 15.0
    assert intelligence["next_best_action"]["action"] == "ACQUIRE_FIRST_PURCHASE"


def test_customer_intelligence_marks_at_risk_reactivation():
    intelligence = _customer_intelligence(
        {
            "customer_id": 21,
            "purchase_count": 4,
            "segments": ["RECURRING", "AT_RISK", "INACTIVE"],
            "days_since_last_purchase": 180,
            "average_days_between_purchases": Decimal("30"),
            "favorite_product": "Ramo premium",
        },
        today=date(2026, 8, 14),
    )

    assert intelligence["churn_risk_probability"] >= 85.0
    assert intelligence["repurchase_probability"] <= 25.0
    assert intelligence["next_best_action"]["action"] == "REACTIVATE"
    assert intelligence["next_best_action"]["recommended_product"] == "Ramo premium"


def test_customer_intelligence_prioritizes_special_date_campaign():
    intelligence = _customer_intelligence(
        {
            "customer_id": 22,
            "purchase_count": 2,
            "segments": ["RECURRING", "ACTIVE"],
            "days_since_last_purchase": 15,
            "average_days_between_purchases": Decimal("45"),
            "fecha_cumpleanos": date(1990, 8, 20),
            "favorite_category": "Rosas",
        },
        today=date(2026, 8, 14),
    )

    assert intelligence["next_best_action"]["action"] == "SPECIAL_DATE_CAMPAIGN"
    assert intelligence["next_best_action"]["next_special_date"]["days_remaining"] == 6
