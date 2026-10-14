from app.schemas.inventario import InventarioCreateRequest, InventarioUpdateRequest


def test_create_inventory_product_accepts_lifecycle_notes_and_status():
    payload = InventarioCreateRequest(
        empresaID=3,
        codigo="FLO-001",
        nombre="Rosa Freedom",
        categoria="Flores",
        diasVidaUtil=7,
        observaciones="Mantener refrigerada",
        activo=False,
    )

    assert payload.diasVidaUtil == 7
    assert payload.observaciones == "Mantener refrigerada"
    assert payload.activo is False


def test_update_inventory_product_accepts_code_and_status():
    payload = InventarioUpdateRequest(
        codigo="FLO-002",
        nombre="Rosa Explorer",
        categoria="Flores",
        activo=False,
    )

    assert payload.codigo == "FLO-002"
    assert payload.activo is False
