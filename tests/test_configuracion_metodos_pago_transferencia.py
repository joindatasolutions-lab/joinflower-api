from app.routers import configuracion as configuracion_router
from app.schemas.configuracion import CatalogoUpdateRequest


class FakeResult:
    def __init__(self, rows=None, scalar_values=None):
        self.rows = list(rows or [])
        self.scalar_values = list(scalar_values or [])

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return self

    def scalar(self):
        return self.scalar_values[0] if self.scalar_values else None


class FakeDb:
    def __init__(self):
        self.calls = []
        self.commits = 0
        self.rows = {
            "list": [
                {
                    "id": 10,
                    "codigo": "transferencia_nequi",
                    "nombre": "Nequi",
                    "orden": 1,
                    "activo": True,
                    "cuenta": "Nequi",
                    "numero_cuenta": "3001720582",
                    "activas_cuentas_catalogo": True,
                }
            ],
            "existing": {
                "id": 10,
                "codigo": "transferencia_nequi",
                "nombre": "Nequi",
                "orden": 1,
                "activo": True,
                "cuenta": None,
                "numero_cuenta": None,
                "activas_cuentas_catalogo": False,
            },
        }

    def execute(self, statement, params=None):
        sql = str(statement)
        params = dict(params or {})
        self.calls.append((sql, params))

        if "COALESCE(MAX(orden)" in sql:
            return FakeResult(rows=[(2,)])
        if "SELECT 1 FROM petalops.metodo_pago_catalogo" in sql:
            return FakeResult(rows=[])
        if "ORDER BY orden ASC, nombre ASC" in sql:
            return FakeResult(rows=self.rows["list"])
        if "AND id_metodo_pago = :item_id" in sql and "SELECT" in sql:
            return FakeResult(rows=[self.rows["existing"]])
        if "INSERT INTO petalops.metodo_pago_catalogo" in sql:
            return FakeResult(
                rows=[
                    {
                        "id": 11,
                        "codigo": params["codigo"],
                        "nombre": params["nombre"],
                        "orden": params["orden"],
                        "activo": True,
                        "cuenta": params.get("cuenta"),
                        "numero_cuenta": params.get("numero_cuenta"),
                        "activas_cuentas_catalogo": params.get("activas_cuentas_catalogo"),
                    }
                ]
            )
        return FakeResult(rows=[])

    def commit(self):
        self.commits += 1


def test_listar_metodos_pago_incluye_datos_transferencia():
    db = FakeDb()

    resultado = configuracion_router._listar_catalogo(
        db,
        empresa_id=3,
        campo="pedido_metodos_pago",
    )

    item = resultado.items[0]
    assert item.cuenta == "Nequi"
    assert item.numeroCuenta == "3001720582"
    assert item.activasCuentasCatalogo is True


def test_crear_metodo_pago_deja_cuenta_inactiva_por_defecto():
    db = FakeDb()

    resultado = configuracion_router._crear_catalogo_item(
        db,
        empresa_id=3,
        campo="pedido_metodos_pago",
        nombre="Daviplata",
    )

    insert_call = next(call for call in db.calls if "INSERT INTO petalops.metodo_pago_catalogo" in call[0])
    assert insert_call[1]["cuenta"] is None
    assert insert_call[1]["numero_cuenta"] is None
    assert insert_call[1]["activas_cuentas_catalogo"] is False
    assert resultado.activasCuentasCatalogo is False
    assert db.commits == 1


def test_actualizar_metodo_pago_permite_activar_datos_transferencia():
    db = FakeDb()
    payload = CatalogoUpdateRequest(
        cuenta="Nequi",
        numeroCuenta="3001720582",
        activasCuentasCatalogo=True,
    )

    resultado = configuracion_router._actualizar_catalogo_item(
        db,
        empresa_id=3,
        campo="pedido_metodos_pago",
        item_id=10,
        payload=payload,
    )

    update_call = next(call for call in db.calls if "UPDATE petalops.metodo_pago_catalogo" in call[0])
    assert "cuenta = :cuenta" in update_call[0]
    assert update_call[1]["cuenta"] == "Nequi"
    assert update_call[1]["numero_cuenta"] == "3001720582"
    assert update_call[1]["activas_cuentas_catalogo"] is True
    assert resultado.cuenta == "Nequi"
    assert resultado.numeroCuenta == "3001720582"
    assert resultado.activasCuentasCatalogo is True
