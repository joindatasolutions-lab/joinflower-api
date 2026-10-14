from decimal import Decimal

from app.schemas.inventario import RecetaCreateRequest, RecetaItem


def test_receta_create_uses_catalog_compatible_defaults():
    payload = RecetaCreateRequest(nombre="Arreglo clasico", precioVenta=Decimal("90000"))

    assert payload.categoria == "Arreglos"
    assert payload.coleccion == "General"
    assert payload.activo is True


def test_receta_item_exposes_catalog_metadata():
    item = RecetaItem(
        idReceta=1,
        empresaID=3,
        nombre="Arreglo clasico",
        codigoProducto="ARR-001",
        categoria="Bouquets",
        coleccion="Madres",
        activo=True,
    )

    assert item.codigoProducto == "ARR-001"
    assert item.categoria == "Bouquets"
    assert item.coleccion == "Madres"
