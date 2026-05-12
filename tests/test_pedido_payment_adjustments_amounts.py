from decimal import Decimal

from app.routers.pedido import _build_pedido_adjustments, _extract_payment_adjustments, _serialize_pago_metadata


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
    assert ajustes["total"] == Decimal("98000.00")


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
