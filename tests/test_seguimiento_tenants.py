from datetime import date

import pytest
from fastapi import HTTPException

from app.routers import seguimiento_tenants
from app.schemas.auth import AuthContext, RoleAssignmentItem


def _auth(login: str, *, es_global: bool) -> AuthContext:
    return AuthContext(
        userID=1,
        empresaID=1,
        sucursalID=None,
        rolID=1,
        rol="super_admin",
        roles=[RoleAssignmentItem(rolID=1, nombreRol="super_admin", principal=True)],
        nombre="JOIN Admin",
        login=login,
        email=f"{login}@example.com",
        esGlobalJoin=es_global,
        permisos={},
        modulosActivosPlan=set(),
    )


def test_require_joinadmin_session_accepts_global_joinadmin():
    auth = _auth("joinadmin", es_global=True)

    assert seguimiento_tenants._require_joinadmin_session(auth) is auth


@pytest.mark.parametrize(
    ("login", "es_global"),
    [
        ("joinadmin", False),
        ("tenant.admin", True),
    ],
)
def test_require_joinadmin_session_rejects_non_joinadmin_contexts(login, es_global):
    with pytest.raises(HTTPException) as exc:
        seguimiento_tenants._require_joinadmin_session(_auth(login, es_global=es_global))

    assert exc.value.status_code == 403


def test_row_to_tenant_item_and_resumen_contract_only_today_and_month():
    item = seguimiento_tenants._row_to_tenant_item(
        {
            "empresa_id": 3,
            "nombre": "Flora",
            "slug": "flora",
            "logo_url": "https://cdn.example.com/flora/logo.png",
            "estado": "Activo",
            "pedidos_hoy": 3,
            "pedidos_mes": 10,
        }
    )

    resumen = seguimiento_tenants._build_resumen([item])

    assert item.empresaID == 3
    assert item.logoUrl == "https://cdn.example.com/flora/logo.png"
    assert item.pedidosHoy == 3
    assert item.pedidosMes == 10
    assert resumen.tenants == 1
    assert resumen.pedidosHoy == 3
    assert resumen.pedidosMes == 10


def test_month_range_returns_whole_month():
    assert seguimiento_tenants._month_range(2026, 2) == (
        date(2026, 2, 1),
        date(2026, 2, 28),
    )
    assert seguimiento_tenants._month_range(2026, 12) == (
        date(2026, 12, 1),
        date(2026, 12, 31),
    )


class _FakeResult:
    def __init__(self, first_row=None):
        self.first_row = first_row

    def first(self):
        return self.first_row


class _NoOptionalTablesDb:
    def execute(self, statement, params=None):
        sql = str(statement)
        if "information_schema.columns" in sql:
            return _FakeResult(None)
        if "to_regclass" in sql:
            return _FakeResult((False,))
        return _FakeResult(None)


def test_seguimiento_sql_omits_optional_empresa_columns_when_missing():
    sql = seguimiento_tenants._seguimiento_tenants_sql(_NoOptionalTablesDb())

    assert "NULL AS estado" in sql
    assert "NULL AS logo_url" in sql
    assert ":fecha_hoy" in sql
    assert ":mes_desde" in sql
    assert ":mes_hasta" in sql
    assert "pedidos_mes" in sql
    assert "APROBADO" in sql
    assert "WHERE p.empresa_id NOT IN (1, 2, 8)" in sql
    assert "WHERE e.id_empresa NOT IN (1, 2, 8)" in sql
