from types import SimpleNamespace
from datetime import datetime

import pytest
from sqlalchemy import Column, MetaData, Table, create_engine, text, literal
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.delivery_queries import current_delivery_id, latest_delivery_ids
from app.routers import pedido as router
from app.models.pedido import Pedido
from app.models.entrega import Entrega
from app.models.cliente import Cliente
from app.models.estadopedido import EstadoPedido
from app.models.estadoentrega import EstadoEntrega
from app.models.pedidodetalle import PedidoDetalle
from app.models.producto import Producto


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    with engine.connect() as conn:
        conn.execute(text("ATTACH DATABASE ':memory:' AS petalops"))
        metadata = MetaData()
        for model in [Pedido, Entrega, Cliente, EstadoPedido, EstadoEntrega, PedidoDetalle, Producto]:
            Table(model.__tablename__, metadata, *[
                Column(c.name, c.type, primary_key=c.primary_key, nullable=True)
                for c in model.__table__.columns
            ], schema="petalops").create(conn)
        with Session(bind=conn) as session:
            session.add(EstadoPedido(idEstadoPedido=1, nombreEstado="APROBADO"))
            for i in range(1, 6):
                session.add(Pedido(idPedido=i, empresaID=1, sucursalID=10, numeroPedido=i,
                    clienteID=1, fechaPedido=datetime(2026, 9, 1), estadoPedidoID=1,
                    totalBruto=100, totalIva=0, totalNeto=100))
            session.add(Pedido(idPedido=99, empresaID=2, sucursalID=20, numeroPedido=99,
                clienteID=2, estadoPedidoID=1, totalBruto=999))
            session.flush()
            yield session
    engine.dispose()


def test_delivery_attempt_precedes_id_and_ties_use_id(db):
    db.execute(text("INSERT INTO petalops.entrega (id_entrega, empresa_id, pedido_id, intentonumero) VALUES (100,1,1,1), (20,1,1,2), (21,1,1,2), (200,2,1,9), (300,1,2,NULL)"))
    rows = db.query(Pedido.idPedido, current_delivery_id(db)).filter(Pedido.empresaID == 1).all()
    assert dict(rows)[1] == 21
    assert dict(rows)[2] == 300
    ranked = latest_delivery_ids(db, 1)
    assert dict(db.query(ranked.c.pedido_id, ranked.c.entrega_id).all()) == {1: 21, 2: 300}


@pytest.mark.parametrize("printed, page, expected, total", [(False, 1, [5, 4], 5), (False, 2, [3, 2], 5), (False, 3, [1], 5), (False, 4, [], 5), (True, 1, [5, 3], 3), (True, 2, [1], 3)])
def test_order_page_and_kpis_are_computed_in_database(db, monkeypatch, printed, page, expected, total):
    calls = []
    monkeypatch.setattr(router, "colombia_now_naive", lambda: datetime(2026, 10, 17, 12))
    monkeypatch.setattr(router, "_factura_impresa_condition", lambda: Pedido.idPedido.in_([2, 4]) if printed else literal(False))
    monkeypatch.setattr(router, "_load_pago_resumen_batch", lambda db, **kw: calls.append(kw["pedido_ids"]) or {})
    monkeypatch.setattr(router, "_tenant_order_rules", lambda *a: {})
    monkeypatch.setattr(router, "_mostrar_codigo_catalogo", lambda *a: False)
    monkeypatch.setattr(router, "_approval_gate_summary", lambda *a, **kw: {"pagoResumen": {}, "puedeAprobar": True, "motivo": None})
    result = router.listar_pedidos.__wrapped__(
        request=Request({"type": "http"}), empresa_id=1, sucursal_id=None,
        estado=None, q=None, fecha_desde=None, fecha_hasta=None,
        filtrar_por_entrega=False, sin_imprimir=True, solo_tienda=False,
        solo_entregas_hoy=False, orden_consecutivo=False, page=page, page_size=2,
        db=db, auth=SimpleNamespace(empresaID=1, esGlobalJoin=False, rol="Admin", login="admin"),
    )
    assert [item.pedidoID for item in result.items] == expected
    assert result.total == total
    assert result.kpis.ventaPeriodo == total * 100
    assert result.kpis.pedidosPeriodo == total
    assert result.kpis.ventaHoy == 0
    assert result.kpis.pedidosHoy == 0
    assert result.facturasPendientesImpresion == total
    assert calls == ([expected] if expected else [])


def test_shared_search_compiles_correlated_subqueries_with_bound_input(db):
    from sqlalchemy.dialects import postgresql
    from app.core.order_search import order_search_condition
    term = "%O'Connor%"
    statement = db.query(Pedido.idPedido).outerjoin(
        Cliente, Cliente.idCliente == Pedido.clienteID
    ).outerjoin(Entrega, Entrega.idEntrega == current_delivery_id(db)).filter(
        Pedido.empresaID == 1, order_search_condition(term)
    ).limit(20).offset(20).statement
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "O'Connor" not in sql
    assert term in compiled.params.values()
    assert "EXISTS" in sql and "LIMIT" in sql and "OFFSET" in sql
    assert "intentonumero DESC NULLS LAST" in sql


@pytest.mark.parametrize('delivery, start, end, state, expected', [
    (False, None, None, None, [4, 3, 2, 1]),
    (True, None, None, None, [4, 3, 2, 1]),
    (False, datetime(2026, 10, 1), datetime(2026, 10, 31, 23, 59, 59), None, [3, 2]),
    (False, datetime(2026, 10, 1), None, None, [4, 3, 2]),
    (False, None, datetime(2026, 9, 30, 23, 59, 59), None, [1]),
    (False, None, None, 'APROBADO', [4, 2, 1]),
    (True, datetime(2026, 10, 1), datetime(2026, 10, 31), None, [2, 1]),
])
def test_text_search_combines_filters_and_keeps_page_statistics(db, monkeypatch, delivery, start, end, state, expected):
    db.add_all([
        Cliente(idCliente=1, empresaID=1, nombreCompleto='Tata Becerra'),
        Cliente(idCliente=2, empresaID=2, nombreCompleto='Tata Becerra'),
        Cliente(idCliente=3, empresaID=1, nombreCompleto='Otro cliente'),
        EstadoPedido(idEstadoPedido=2, nombreEstado='PENDIENTE'),
    ])
    for i, month in [(1, 9), (2, 10), (3, 10), (4, 11)]:
        order = db.get(Pedido, i)
        order.fechaPedido = datetime(2026, month, 15)
    db.get(Pedido, 3).estadoPedidoID = 2
    db.get(Pedido, 5).clienteID = 3
    db.add(Pedido(idPedido=6, empresaID=1, sucursalID=20, clienteID=1,
                  fechaPedido=datetime(2026, 10, 15), estadoPedidoID=1, totalBruto=900))
    for i, month in [(1, 10), (2, 10), (3, 11)]:
        db.add(Entrega(idEntrega=i, empresaID=1, pedidoID=i, intentoNumero=1,
                       fechaEntregaProgramada=datetime(2026, month, 20)))
    db.flush()
    # SQLite cannot execute the PostgreSQL-only payment search branch.
    # Keep a real name predicate to exercise its AND composition in the endpoint.
    monkeypatch.setattr(router, 'order_search_condition', lambda term: Cliente.nombreCompleto.ilike(term))
    monkeypatch.setattr(router, 'assert_sucursal_empresa', lambda *args: None)
    monkeypatch.setattr(router, '_factura_impresa_condition', lambda: literal(False))
    monkeypatch.setattr(router, '_load_pago_resumen_batch', lambda *args, **kwargs: {})
    monkeypatch.setattr(router, '_tenant_order_rules', lambda *args: {})
    monkeypatch.setattr(router, '_mostrar_codigo_catalogo', lambda *args: False)
    monkeypatch.setattr(router, '_approval_gate_summary', lambda *args, **kwargs: {'pagoResumen': {}, 'puedeAprobar': True, 'motivo': None})
    results = []
    ids = []
    for page in range(1, len(expected) + 2):
        result = router.listar_pedidos.__wrapped__(
            request=Request({'type': 'http'}), empresa_id=1, sucursal_id=10,
            estado=state, q='tata becerra', fecha_desde=start, fecha_hasta=end,
            filtrar_por_entrega=delivery, sin_imprimir=False, solo_tienda=False,
            solo_entregas_hoy=False, orden_consecutivo=False, page=page, page_size=1,
            db=db, auth=SimpleNamespace(empresaID=1, esGlobalJoin=False, rol='Admin', login='admin'),
        )
        ids.extend(item.pedidoID for item in result.items)
        assert result.total == len(expected)
        assert result.kpis.pedidosPeriodo == len(expected)
        assert result.kpis.ventaPeriodo == 100 * len([i for i in expected if i != 3])
        results.append(result.kpis.model_dump())
    # Pending orders sort before numbered approved orders.
    assert set(ids) == set(expected) and len(ids) == len(expected)
    assert all(kpis == results[0] for kpis in results)
