"""Verifica _upsert_cliente_pedido_manual: el pedido manual busca/crea el cliente por
telefono o identificacion. Antes, cuando no habia identificacion real, se rellenaba con
un valor derivado del telefono (pelado o con prefijo "TEL-") como respaldo -- y como el
match tambien busca por identificacion, un pedido futuro cuya identificacion enviada
coincidiera por accidente con ese respaldo fusionaba silenciosamente a dos clientes
distintos. Caso real en produccion: el registro de "Daniela Colon" quedo sobreescrito con
el nombre y telefono de "Rodrigo Colon" el 2026-09-16 porque la identificacion enviada en
el pedido de Rodrigo coincidia exactamente con el telefono-respaldo (sin prefijo) que se
le habia asignado a Daniela. Esa logica de respaldo se elimino: si no hay identificacion,
el campo queda vacio (None) en vez de inventar un valor.
"""
from datetime import datetime, timezone

from app.routers.pedido import _upsert_cliente_pedido_manual


def _evalua_clausula(cliente, clausula):
    """Evalua una clausula de SQLAlchemy (BinaryExpression o BooleanClauseList de
    or_/and_) contra un objeto Python plano, para poder probar la logica de matching
    real de _upsert_cliente_pedido_manual sin una base de datos de verdad."""
    if hasattr(clausula, "clauses"):
        resultados = [_evalua_clausula(cliente, c) for c in clausula.clauses]
        return any(resultados) if "OR" in str(clausula.operator).upper() or clausula.operator.__name__ == "or_" else all(resultados)
    return getattr(cliente, clausula.left.key, None) == clausula.right.value


class _FakeQuery:
    def __init__(self, resultados):
        self._resultados = list(resultados)
        self._clausulas = []

    def filter(self, *args, **kwargs):
        self._clausulas.extend(args)
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        for cliente in self._resultados:
            if all(_evalua_clausula(cliente, c) for c in self._clausulas):
                return cliente
        return None


class _FakeCliente:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeSession:
    def __init__(self, clientes_existentes):
        self._clientes = list(clientes_existentes)
        self.added = []

    def query(self, model):
        return _FakeQuery(self._clientes)

    def add(self, obj):
        self.added.append(obj)
        self._clientes.append(obj)

    def flush(self):
        for cliente in self.added:
            if not hasattr(cliente, "idCliente"):
                cliente.idCliente = 9999


def test_pedido_de_otro_cliente_no_se_fusiona_con_identificacion_ajena():
    # Daniela ya existe en el sistema sin identificacion real (nunca se le inventa una).
    daniela = _FakeCliente(
        idCliente=5150,
        empresaID=5,
        empresa_id=5,
        telefono="3204675782",
        telefonoCompleto="3204675782",
        telefono_completo="3204675782",
        identificacion=None,
        nombreCompleto="Daniela colon",
        tipoIdent="CC",
        indicativo=None,
        email=None,
        updatedAt=datetime.now(timezone.utc),
    )
    db = _FakeSession([daniela])

    # Rodrigo llega con otro telefono y, por coincidencia, con una identificacion igual
    # al telefono de Daniela. Como daniela.identificacion es None (nunca se le asigno un
    # respaldo derivado del telefono), esto no puede matchear contra ella.
    resultado = _upsert_cliente_pedido_manual(
        db,
        empresa_id=5,
        tipo_ident="CC",
        identificacion="3204675782",
        indicativo=None,
        nombre_completo="Rodrigo Colon",
        telefono="3023216896",
        email=None,
    )

    assert resultado is not daniela
    assert daniela.nombreCompleto == "Daniela colon"
    assert daniela.telefono == "3204675782"


def test_mismo_cliente_repite_pedido_y_si_se_reconoce_por_su_propio_telefono():
    daniela = _FakeCliente(
        idCliente=5150,
        empresaID=5,
        empresa_id=5,
        telefono="3204675782",
        telefonoCompleto="3204675782",
        telefono_completo="3204675782",
        identificacion=None,
        nombreCompleto="Daniela colon",
        tipoIdent="CC",
        indicativo=None,
        email=None,
        updatedAt=datetime.now(timezone.utc),
    )
    db = _FakeSession([daniela])

    resultado = _upsert_cliente_pedido_manual(
        db,
        empresa_id=5,
        tipo_ident="CC",
        identificacion=None,
        indicativo=None,
        nombre_completo="Daniela Colon",
        telefono="3204675782",
        email=None,
    )

    assert resultado is daniela


def test_cliente_nuevo_sin_identificacion_queda_con_identificacion_vacia():
    db = _FakeSession([])

    resultado = _upsert_cliente_pedido_manual(
        db,
        empresa_id=5,
        tipo_ident="CC",
        identificacion=None,
        indicativo=None,
        nombre_completo="Cliente Nuevo",
        telefono="3001112233",
        email=None,
    )

    assert resultado.identificacion is None
