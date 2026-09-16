"""Verifica _cliente_identificacion_fallback y _upsert_cliente_pedido_manual: el pedido
manual busca/crea el cliente por telefono o identificacion. Cuando no hay identificacion
real, se usaba el telefono "pelado" como respaldo -- y como el match tambien busca por
identificacion, un pedido futuro cuya identificacion enviada coincidiera por accidente con
ese respaldo (p.ej. un campo del formulario que no se limpio entre pedidos, o un typo)
fusionaba silenciosamente a dos clientes distintos. Caso real en produccion: el registro de
"Daniela Colon" quedo sobreescrito con el nombre y telefono de "Rodrigo Colon" el
2026-09-16 porque la identificacion enviada en el pedido de Rodrigo coincidia exactamente
con el telefono-respaldo (sin prefijo) que se le habia asignado a Daniela.
"""
from datetime import datetime, timezone

from app.routers.pedido import _cliente_identificacion_fallback, _upsert_cliente_pedido_manual


def test_fallback_usa_identificacion_real_si_se_envia():
    assert _cliente_identificacion_fallback("123456789", "3001234567") == "123456789"


def test_fallback_de_telefono_queda_prefijado_no_pelado():
    resultado = _cliente_identificacion_fallback(None, "3204675782")
    assert resultado == "TEL-3204675782"
    assert resultado != "3204675782"


def test_fallback_generico_si_no_hay_nada():
    assert _cliente_identificacion_fallback(None, None).startswith("TMP-")


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


def test_pedido_de_otro_cliente_no_se_fusiona_con_fallback_de_telefono_ajeno():
    # Daniela ya existe en el sistema con su telefono como respaldo de identificacion
    # (ya prefijado gracias al fix).
    daniela = _FakeCliente(
        idCliente=5150,
        empresaID=5,
        empresa_id=5,
        telefono="3204675782",
        telefonoCompleto="3204675782",
        telefono_completo="3204675782",
        identificacion="TEL-3204675782",
        nombreCompleto="Daniela colon",
        tipoIdent="CC",
        indicativo=None,
        email=None,
        updatedAt=datetime.now(timezone.utc),
    )
    db = _FakeSession([daniela])

    # Rodrigo llega con OTRO telefono y, por el bug del formulario, con una identificacion
    # que por accidente coincidia con el telefono pelado de Daniela ("3204675782"). Con el
    # fallback ya prefijado, esto ya no puede matchear contra daniela.identificacion
    # ("TEL-3204675782" != "3204675782"), asi que ya no la sobreescribe.
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
        identificacion="TEL-3204675782",
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
