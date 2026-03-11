from app.core.security import normalize_module_name, normalize_role_name


def test_normalize_module_name():
    assert normalize_module_name(" Pedidos ") == "pedidos"
    assert normalize_module_name(None) == ""


def test_normalize_role_name():
    assert normalize_role_name("Empresa Admin") == "empresa_admin"
    assert normalize_role_name(None) == ""
