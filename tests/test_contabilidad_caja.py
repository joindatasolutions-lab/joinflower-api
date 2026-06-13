from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.routers.contabilidad import (
    _caja_totales_sql,
    _calculate_nueva_base,
    _parse_query_date,
    _row_to_caja_item,
    listar_cierres_caja,
)
from app.schemas.contabilidad import CajaCierreRequest
from app.services import caja_service


def test_caja_cierre_request_accepts_camel_case():
    payload = CajaCierreRequest(
        empresaID=1,
        sucursalID=2,
        fechaOperacion="2026-06-30",
        baseInicial=100000,
        efectivo=70000,
        gasto=15000,
        totalEfectivo=155000,
        montoGuardado=40000,
        nuevaBase=115000,
        usuarioID=9,
    )

    assert payload.empresaID == 1
    assert payload.sucursalID == 2
    assert payload.fechaOperacion == date(2026, 6, 30)
    assert payload.baseInicial == Decimal("100000")
    assert payload.efectivo == Decimal("70000")
    assert payload.gasto == Decimal("15000")
    assert payload.totalEfectivo == Decimal("155000")
    assert payload.montoGuardado == Decimal("40000")
    assert payload.nuevaBase == Decimal("115000")
    assert payload.usuarioID == 9


def test_caja_cierre_request_accepts_snake_case():
    payload = CajaCierreRequest(
        empresa_id=1,
        sucursal_id=2,
        fecha="2026-06-30",
        base=100000,
        efectivo_ventas=70000,
        total_gastos=15000,
        total_efectivo=155000,
        guardado=40000,
        nueva_base=130000,
        usuario_id=9,
    )

    assert payload.empresaID == 1
    assert payload.sucursalID == 2
    assert payload.fechaOperacion == date(2026, 6, 30)
    assert payload.baseInicial == Decimal("100000")
    assert payload.efectivo == Decimal("70000")
    assert payload.gasto == Decimal("15000")
    assert payload.totalEfectivo == Decimal("155000")
    assert payload.montoGuardado == Decimal("40000")
    assert payload.nuevaBase == Decimal("130000")
    assert payload.usuarioID == 9


def test_caja_cierre_request_accepts_front_formatted_values():
    payload = CajaCierreRequest(
        empresaID=1,
        sucursalID=1,
        fecha="12/06/2026",
        base="0.00",
        efectivo="$602.000",
        gasto="0.00",
        totalEfectivo="$602.000",
        guardado="0.00",
        nuevaBase="$602.000",
    )

    assert payload.fechaOperacion == date(2026, 6, 12)
    assert payload.baseInicial == Decimal("0.00")
    assert payload.efectivo == Decimal("602000")
    assert payload.gasto == Decimal("0.00")
    assert payload.totalEfectivo == Decimal("602000")
    assert payload.montoGuardado == Decimal("0.00")
    assert payload.nuevaBase == Decimal("602000")


def test_parse_query_date_accepts_frontend_display_format():
    assert _parse_query_date("11/06/2026") == date(2026, 6, 11)
    assert _parse_query_date("2026-06-11") == date(2026, 6, 11)


def test_row_to_caja_item_maps_nulls_to_contract_defaults():
    item = _row_to_caja_item(
        {
            "fecha": date(2026, 6, 30),
            "base": Decimal("100000"),
            "efectivo": None,
            "gasto": None,
            "total_efectivo": Decimal("170000"),
            "guardado": Decimal("40000"),
            "nueva_base": Decimal("130000"),
            "observacion": None,
        }
    )

    assert item.efectivo_ventas == Decimal("0")
    assert item.total_gastos == Decimal("0")
    assert item.observacion == ""


def test_listar_cierres_caja_rejects_invalid_date_range():
    with pytest.raises(HTTPException) as exc:
        listar_cierres_caja(
            empresa_id=1,
            sucursal_id=1,
            fecha_desde_raw="2026-07-01",
            fecha_hasta_raw="2026-06-30",
            db=None,
            auth=None,
        )

    assert exc.value.status_code == 400


class _NoViewDb:
    def execute(self, *_args, **_kwargs):
        return self

    def first(self):
        return (False,)


def test_caja_totales_sql_reads_unified_caja_table():
    sql = _caja_totales_sql(_NoViewDb(), single_day=False)

    assert "petalops.caja" in sql
    assert "petalops.caja_apertura_cierre" not in sql
    assert "petalops.caja_gasto" not in sql
    assert "vw_contabilidad_resumen_ventas_diario" not in sql


def test_calculate_nueva_base_subtracts_gastos_and_guardado():
    assert _calculate_nueva_base(
        base_inicial=Decimal("100000"),
        efectivo_ventas=Decimal("70000"),
        total_gastos=Decimal("15000"),
        monto_guardado=Decimal("40000"),
    ) == Decimal("115000")


class _FakePedido:
    empresaID = 1
    sucursalID = 2
    fechaPedido = datetime(2026, 6, 30, 14, 30)


class _FakeResult:
    def __init__(self, value=None):
        self.value = value

    def first(self):
        return self.value

    def mappings(self):
        return self


class _CajaRefreshDb:
    def __init__(self):
        self.upsert_params = None

    def execute(self, statement, params=None):
        sql = str(statement)
        if "to_regclass" in sql:
            return _FakeResult((True,))
        if "information_schema.columns" in sql:
            return _FakeResult((1,))
        if "SUM(pm.monto)" in sql:
            return _FakeResult((Decimal("3000"),))
        if "SELECT base, gasto, guardado" in sql:
            return _FakeResult(None)
        if "SELECT nueva_base" in sql:
            return _FakeResult((Decimal("0"),))
        if "INSERT INTO petalops.caja" in sql:
            self.upsert_params = params
            return _FakeResult(None)
        return _FakeResult(None)


def test_refresh_caja_por_pedido_accumulates_cash_total_for_day():
    db = _CajaRefreshDb()

    caja_service.refresh_caja_por_pedido(db, pedido=_FakePedido(), usuario_id=9)

    assert db.upsert_params["fecha"] == date(2026, 6, 30)
    assert db.upsert_params["efectivo"] == Decimal("3000")
    assert db.upsert_params["total_efectivo"] == Decimal("3000")
    assert db.upsert_params["nueva_base"] == Decimal("3000")
    assert db.upsert_params["usuario_id"] == 9
