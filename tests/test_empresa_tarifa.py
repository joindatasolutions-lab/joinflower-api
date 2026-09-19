from app.models.empresa import Empresa


def test_empresa_tarifa_defaults_to_2500():
    empresa = Empresa(idEmpresa=10)

    assert empresa.tarifa is None
    assert Empresa.__table__.c.tarifa.default.arg == 2500
    assert str(Empresa.__table__.c.tarifa.server_default.arg) == "2500"
    assert Empresa.__table__.c.tarifa.nullable is False
