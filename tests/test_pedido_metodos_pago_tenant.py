import json

from app.routers import pedido as pedido_router


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def first(self):
        return self.rows[0] if self.rows else None

    def mappings(self):
        return self

    def all(self):
        return self.rows


class FakeDb:
    def __init__(self, opciones):
        self.opciones = opciones

    def execute(self, statement, params=None):
        sql = str(statement)
        if "information_schema.tables" in sql:
            return FakeResult([(1,)])
        if "FROM petalops.empresa_menu" in sql:
            return FakeResult(
                [
                    {
                        "codigo": "pedido_metodos_pago",
                        "titulo": "Metodos de pago",
                        "seccion": "pedido_detalle",
                        "tipo_control": "multi_select",
                        "opciones_json": json.dumps(self.opciones),
                        "requerido_aprobacion": True,
                        "activo": True,
                        "orden": 10,
                    }
                ]
            )
        raise AssertionError(f"Consulta inesperada: {sql}")


def test_metodos_pago_no_agrega_rappi_si_el_tenant_no_lo_configuro():
    rows = pedido_router._load_empresa_menu_rows(FakeDb(["Efectivo", "Nequi"]), empresa_id=2)

    assert rows[0]["opciones"] == ["Efectivo", "Nequi"]


def test_metodos_pago_conserva_rappi_cuando_esta_configurado_en_bd():
    rows = pedido_router._load_empresa_menu_rows(FakeDb(["Efectivo", "RAPPI"]), empresa_id=3)

    assert rows[0]["opciones"] == ["Efectivo", "RAPPI"]
