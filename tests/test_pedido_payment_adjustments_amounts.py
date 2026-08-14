from decimal import Decimal
from types import SimpleNamespace

from app.routers.pedido import (
    _apply_pedido_domicilio_amounts,
    _build_pedido_adjustments,
    _extract_payment_adjustments,
    _flora_phase2_ready,
    _load_pago_resumen,
    _manual_domicilio_amounts,
    _serialize_pago_metadata,
)


class _FakeScalarResult:
    def first(self):
        return None


class _FakeMappingResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _FakePagoDb:
    def execute(self, statement, params=None):
        sql = str(statement)
        if "FROM petalops.pago" in sql:
            return _FakeMappingResult(
                {
                    "metodo_pago": "Efectivo",
                    "proveedor": "manual",
                    "referencia": None,
                    "raw_respuesta": None,
                    "monto": Decimal("125000"),
                }
            )
        return _FakeScalarResult()


class _FakePhase2SchemaDb:
    def __init__(self, missing_column: tuple[str, str] | None = None):
        self.missing_column = missing_column

    def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}
        if "information_schema.tables" in sql:
            return _FakeScalarRowResult((1,))
        if "information_schema.columns" in sql:
            table_name = str(params.get("table_name") or "")
            column_name = str(params.get("column_name") or "")
            if self.missing_column == (table_name, column_name):
                return _FakeScalarResult()
            return _FakeScalarRowResult((1,))
        return _FakeScalarResult()


class _FakeScalarRowResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


def test_build_pedido_adjustments_uses_fixed_amount_discount_and_saldo_favor():
    ajustes = _build_pedido_adjustments(
        subtotal=Decimal("100000"),
        iva=Decimal("0"),
        domicilio=Decimal("10000"),
        metodos_pago=["Efectivo"],
        omitir_recargo_link=False,
        descuento_monto=Decimal("5000"),
        saldo_favor_monto=Decimal("7000"),
    )

    assert ajustes["descuentoMonto"] == Decimal("5000.00")
    assert ajustes["saldoFavorMonto"] == Decimal("7000.00")
    assert ajustes["total"] == Decimal("112000.00")


def test_manual_domicilio_amounts_omits_gifted_delivery():
    amounts = _manual_domicilio_amounts(
        domicilio=0,
        domicilio_original=15000,
        descuento_domicilio=15000,
        domicilio_obsequiado=True,
        omitir_costo_domicilio=True,
        resolved_domicilio=Decimal("15000"),
    )

    assert amounts["cobrado"] == Decimal("0.00")
    assert amounts["original"] == Decimal("15000.00")
    assert amounts["descuento"] == Decimal("15000.00")
    assert amounts["domicilioObsequiado"] is True
    assert amounts["omitirCostoDomicilio"] is True


def test_manual_domicilio_amounts_charges_delivery_when_not_omitted():
    amounts = _manual_domicilio_amounts(
        domicilio=None,
        domicilio_original=None,
        descuento_domicilio=None,
        domicilio_obsequiado=False,
        omitir_costo_domicilio=False,
        resolved_domicilio=Decimal("12000"),
    )

    assert amounts["cobrado"] == Decimal("12000.00")
    assert amounts["original"] == Decimal("12000.00")
    assert amounts["descuento"] == Decimal("0.00")


def test_apply_pedido_domicilio_amounts_gifted_uses_resolved_neighborhood_cost():
    pedido = SimpleNamespace(
        costoDomicilio=Decimal("0.00"),
        domicilioObsequiado=True,
        omitirCostoDomicilio=False,
        domicilioOriginal=Decimal("8000.00"),
        descuentoDomicilio=Decimal("8000.00"),
    )

    _apply_pedido_domicilio_amounts(
        pedido,
        resolved_domicilio=Decimal("15000"),
        descuento_domicilio=Decimal("8000"),
        prefer_resolved=True,
    )

    assert pedido.costoDomicilio == Decimal("0.00")
    assert pedido.domicilioOriginal == Decimal("15000.00")
    assert pedido.descuentoDomicilio == Decimal("15000.00")


def test_apply_pedido_domicilio_amounts_forced_recalc_prefers_resolved_over_payload():
    pedido = SimpleNamespace(
        costoDomicilio=Decimal("8000.00"),
        domicilioObsequiado=False,
        omitirCostoDomicilio=False,
        domicilioOriginal=Decimal("8000.00"),
        descuentoDomicilio=Decimal("0.00"),
    )

    _apply_pedido_domicilio_amounts(
        pedido,
        resolved_domicilio=Decimal("15000"),
        domicilio_cobrado=Decimal("8000"),
        domicilio_original=Decimal("8000"),
        descuento_domicilio=Decimal("0"),
        prefer_resolved=True,
    )

    assert pedido.costoDomicilio == Decimal("15000.00")
    assert pedido.domicilioOriginal == Decimal("15000.00")
    assert pedido.descuentoDomicilio == Decimal("0.00")


def test_payment_metadata_serializes_discount_notes_balance_and_invoice_state():
    raw = _serialize_pago_metadata(
        None,
        canal_flora="Huawei",
        descuento_monto=Decimal("12000"),
        descuento_nota="Cliente frecuente",
        saldo_favor_monto=Decimal("3000"),
        saldo_favor_nota="Nota saldo",
        factura_impresa=True,
        factura_impresa_at="2026-05-12T20:00:00+00:00",
        factura_impresa_by="joinadmin",
    )

    ajustes = _extract_payment_adjustments(raw)

    assert ajustes["descuentoMonto"] == 12000.0
    assert ajustes["descuentoNota"] == "Cliente frecuente"
    assert ajustes["saldoFavorMonto"] == 3000.0
    assert ajustes["saldoFavorNota"] == "Nota saldo"
    assert ajustes["facturaImpresa"] is True
    assert ajustes["facturaImpresaBy"] == "joinadmin"


def test_load_pago_resumen_legacy_payment_includes_amount_for_cash_breakdown():
    resumen = _load_pago_resumen(_FakePagoDb(), pedido_id=2326, empresa_id=3)

    assert resumen["metodoPago"] == "Efectivo"
    assert resumen["metodosPago"] == ["Efectivo"]
    assert resumen["montoEfectivo"] == 125000.0


def test_flora_phase2_requires_expected_columns():
    assert _flora_phase2_ready(_FakePhase2SchemaDb()) is True
    assert _flora_phase2_ready(_FakePhase2SchemaDb(("pago_metodo", "monto"))) is False
