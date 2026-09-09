from types import SimpleNamespace

from app.services.pedido_service import generar_numeracion_pedido


class _FakeResult:
    def __init__(self, row=None):
        self._row = row

    def first(self):
        return self._row


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _FakeDb:
    def __init__(self):
        self.statements = []
        self.params = []

    def query(self, model):
        return _FakeQuery(SimpleNamespace(nombreSucursal="PetalOps", prefijoPedido="PTL"))

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        self.params.append(params or {})
        if "RETURNING ultimo_pedido" in sql:
            return _FakeResult((67,))
        return _FakeResult()


def test_generar_numeracion_sincroniza_contador_con_maximo_real():
    db = _FakeDb()

    numero, codigo = generar_numeracion_pedido(db, empresa_id=2, sucursal_id=3)

    assert numero == 67
    assert codigo == "PTL-00067"
    update_sql = next(sql for sql in db.statements if "RETURNING ultimo_pedido" in sql)
    assert "MAX(numero_pedido)" in update_sql
    assert "GREATEST(ultimo_pedido" in update_sql
    assert "numero_pedido > 0" in update_sql
