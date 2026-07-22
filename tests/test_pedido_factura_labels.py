from types import SimpleNamespace

from app.routers import pedido


def test_factura_empresa_labels_do_not_default_to_flora_for_other_tenants():
    empresa = SimpleNamespace(nombreComercial=None, nombreEmpresa=None)
    sucursal = SimpleNamespace(nombreSucursal="PetalOps Centro")

    titulo, subtitulo = pedido._factura_empresa_labels(empresa, sucursal, 1)

    assert titulo == "PetalOps Centro"
    assert subtitulo == ""


def test_factura_empresa_labels_keep_flora_subtitle_for_flora():
    empresa = SimpleNamespace(nombreComercial="FLORA", nombreEmpresa=None)

    titulo, subtitulo = pedido._factura_empresa_labels(empresa, None, pedido.FLORA_EMPRESA_ID)

    assert titulo == "FLORA"
    assert subtitulo == "Tienda de Flores"
