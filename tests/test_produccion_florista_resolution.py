from types import SimpleNamespace

from app.routers.produccion import _current_florista_for_user


class FakeQuery:
    def __init__(self, result):
        self.result = result

    def join(self, *_args, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.result


class FakeExecuteResult:
    def __init__(self, row):
        self.row = row

    def first(self):
        return self.row


class FakeSession:
    def __init__(self, query_results, execute_row=None):
        self._query_results = list(query_results)
        self.execute_row = execute_row
        self.execute_calls = []

    def query(self, *_args, **_kwargs):
        if not self._query_results:
            raise AssertionError("Unexpected query() call")
        return FakeQuery(self._query_results.pop(0))

    def execute(self, statement, params):
        self.execute_calls.append((str(statement), params))
        return FakeExecuteResult(self.execute_row)


def test_current_florista_for_user_prefers_direct_usuario_match():
    florista = SimpleNamespace(idFlorista=11)
    db = FakeSession(query_results=[florista])
    auth = SimpleNamespace(userID=25, empresaID=3, sucursalID=1, login="flora.florista1", email="flora.florista1@empresa3.local", nombre="Flora Florista 1")

    result = _current_florista_for_user(db, auth)

    assert result is florista
    assert db.execute_calls == []


def test_current_florista_for_user_falls_back_to_login_email_name_lookup():
    florista = SimpleNamespace(idFlorista=11)
    db = FakeSession(query_results=[None, florista], execute_row=(11,))
    auth = SimpleNamespace(
        userID=25,
        empresaID=3,
        sucursalID=1,
        login="flora.florista1",
        email="flora.florista1@empresa3.local",
        nombre="Flora Florista 1",
    )

    result = _current_florista_for_user(db, auth)

    assert result is florista
    assert len(db.execute_calls) == 1
    _statement, params = db.execute_calls[0]
    assert params["empresa_id"] == 3
    assert params["sucursal_id"] == 1
    assert params["login"] == "flora.florista1"
    assert params["email"] == "flora.florista1@empresa3.local"
    assert params["nombre"] == "flora florista 1"


def test_current_florista_for_user_returns_none_when_no_match_exists():
    db = FakeSession(query_results=[None], execute_row=None)
    auth = SimpleNamespace(userID=25, empresaID=3, sucursalID=1, login="flora.florista1", email="", nombre="")

    result = _current_florista_for_user(db, auth)

    assert result is None
    assert len(db.execute_calls) == 1
