from datetime import date, datetime, timezone

from sqlalchemy import and_
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.models.entrega import Entrega
from app.models.pedido import Pedido
from app.routers.pedido import (
    _fecha_filtro_pedido,
    _fecha_pedido_str,
    _fecha_respuesta_pedido,
    _filtrar_pedidos_por_entrega_hoy,
    _filtrar_pedidos_por_rango_entrega,
    _hora_pedido_str,
)


def test_fecha_filtro_pedido_converts_utc_range_to_colombia_naive_datetime():
    utc_end_of_colombia_day = datetime(2026, 7, 16, 4, 59, 59, tzinfo=timezone.utc)

    normalized = _fecha_filtro_pedido(utc_end_of_colombia_day)

    assert normalized == datetime(2026, 7, 15, 23, 59, 59)


def test_fecha_respuesta_pedido_is_returned_in_colombia_time():
    utc_value = datetime(2026, 7, 16, 5, 9, 19, tzinfo=timezone.utc)

    normalized = _fecha_respuesta_pedido(utc_value)

    assert normalized == datetime(2026, 7, 16, 0, 9, 19)
    assert _fecha_pedido_str(utc_value) == "2026-07-16"
    assert _hora_pedido_str(utc_value) == "00:09:19"


def test_filtro_entregas_hoy_usa_fecha_programada_del_ultimo_intento_y_empresa():
    db = Session()
    base = (
        db.query(Pedido.idPedido)
        .outerjoin(
            Entrega,
            and_(
                Entrega.pedidoID == Pedido.idPedido,
                Entrega.empresaID == Pedido.empresaID,
            ),
        )
        .filter(Pedido.empresaID == 3)
    )

    filtered = _filtrar_pedidos_por_entrega_hoy(base, db, date(2026, 9, 13))
    sql = str(
        filtered.statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()

    assert "coalesce" in sql
    assert "reprogramadapara" in sql
    assert "fechaentregaprogramada" in sql
    assert "intentonumero desc nulls last" in sql
    assert "entrega_1.empresa_id = petalops.pedido.empresa_id" in sql
    assert "2026-09-13 00:00:00" in sql
    assert "2026-09-14 00:00:00" in sql


def test_filtro_rango_entrega_acepta_solo_fecha_desde_o_solo_fecha_hasta():
    db = Session()
    base = (
        db.query(Pedido.idPedido)
        .outerjoin(
            Entrega,
            and_(
                Entrega.pedidoID == Pedido.idPedido,
                Entrega.empresaID == Pedido.empresaID,
            ),
        )
        .filter(Pedido.empresaID == 9)
    )

    solo_desde = _filtrar_pedidos_por_rango_entrega(base, db, fecha_desde=date(2026, 9, 17))
    sql_desde = str(
        solo_desde.statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    ).lower()
    assert "2026-09-17 00:00:00" in sql_desde
    assert sql_desde.count(">=") >= 1

    solo_hasta = _filtrar_pedidos_por_rango_entrega(base, db, fecha_hasta=date(2026, 9, 20))
    sql_hasta = str(
        solo_hasta.statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    ).lower()
    assert "2026-09-21 00:00:00" in sql_hasta


def test_filtro_rango_entrega_de_varios_dias_incluye_todo_el_rango():
    db = Session()
    base = (
        db.query(Pedido.idPedido)
        .outerjoin(
            Entrega,
            and_(
                Entrega.pedidoID == Pedido.idPedido,
                Entrega.empresaID == Pedido.empresaID,
            ),
        )
        .filter(Pedido.empresaID == 9)
    )

    filtered = _filtrar_pedidos_por_rango_entrega(base, db, fecha_desde=date(2026, 9, 17), fecha_hasta=date(2026, 9, 23))
    sql = str(
        filtered.statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    ).lower()

    assert "2026-09-17 00:00:00" in sql
    assert "2026-09-24 00:00:00" in sql
