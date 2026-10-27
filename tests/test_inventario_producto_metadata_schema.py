from app.schemas.inventario import InventarioCreateRequest, InventarioUpdateRequest


def test_create_inventory_product_accepts_lifecycle_notes_and_status():
    payload = InventarioCreateRequest(
        empresaID=3,
        codigo="FLO-001",
        nombre="Rosa Freedom",
        categoria="Flores",
        diasVidaUtil=7,
        observaciones="Mantener refrigerada",
        valorUnitario="2500",
        costoPaquete="30000",
        precioVenta="4000",
        precioVentaPaquete="45000",
        activo=False,
    )

    assert payload.diasVidaUtil == 7
    assert payload.observaciones == "Mantener refrigerada"
    assert payload.valorUnitario == 2500
    assert payload.costoPaquete == 30000
    assert payload.precioVenta == 4000
    assert payload.precioVentaPaquete == 45000
    assert payload.activo is False


def test_update_inventory_product_accepts_code_and_status():
    payload = InventarioUpdateRequest(
        codigo="FLO-002",
        nombre="Rosa Explorer",
        categoria="Flores",
        costoPaquete="32000",
        precioVentaPaquete="48000",
        activo=False,
    )

    assert payload.codigo == "FLO-002"
    assert payload.costoPaquete == 32000
    assert payload.precioVentaPaquete == 48000
    assert payload.activo is False
