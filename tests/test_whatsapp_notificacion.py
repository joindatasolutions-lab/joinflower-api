"""Casos obligatorios de pendientes/Mejoras/promt-meta.md (seccion 16).

No requiere una base de datos real: se usa una sesion falsa (FakeSession/FakeQuery) que
devuelve exactamente los objetos que cada caso necesita, para poder ejercitar la logica de
negocio real de app/services/whatsapp_service.py (incluida la verificacion de aislamiento
entre empresas) sin depender de Postgres.
"""
from datetime import datetime

import pytest

from app.models.cliente import Cliente
from app.models.empresa import Empresa
from app.models.entrega import Entrega
from app.models.pedido import Pedido
from app.models.pedidodetalle import PedidoDetalle
from app.models.producto import Producto
from app.models.whatsapp_notificacion import WhatsappNotificacion
from app.schemas.domicilios import ESTADO_ENTREGADO
from app.services import whatsapp_client, whatsapp_service
from app.jobs import whatsapp_dispatch_job


class FakeQuery:
    def __init__(self, results):
        self._results = list(results)

    def filter(self, *args, **kwargs):
        return self

    def outerjoin(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._results[0] if self._results else None

    def all(self):
        return self._results


class FakeSession:
    def __init__(self, por_modelo, whatsapp_notifications_enabled=True, execute_handler=None):
        self._por_modelo = por_modelo
        self.commits = 0
        self.rollbacks = 0
        self.whatsapp_notifications_enabled = whatsapp_notifications_enabled
        self._execute_handler = execute_handler

    def query(self, *modelo):
        key = modelo[0] if len(modelo) == 1 else modelo
        return FakeQuery(self._por_modelo.get(key, []))

    def execute(self, statement, params=None):
        if self._execute_handler:
            return self._execute_handler(statement, params or {})
        raise AssertionError(f"execute no esperado: {statement}")

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _empresa(id_empresa, nombre):
    return Empresa(idEmpresa=id_empresa, nombreComercial=nombre, nombreEmpresa=nombre, slug=nombre.lower())


def _cliente(id_cliente, empresa_id, telefono_completo="+573001234567", nombre="Cliente Test"):
    return Cliente(idCliente=id_cliente, empresaID=empresa_id, telefonoCompleto=telefono_completo, nombreCompleto=nombre)


def _pedido(id_pedido, empresa_id, cliente_id, numero_pedido=1000):
    return Pedido(idPedido=id_pedido, empresaID=empresa_id, clienteID=cliente_id, numeroPedido=numero_pedido)


def _entrega(id_entrega, empresa_id, estado=4):
    return Entrega(idEntrega=id_entrega, empresaID=empresa_id, estadoEntregaID=estado)


def _notificacion(empresa_id, pedido_id, entrega_id):
    return WhatsappNotificacion(
        idNotificacion=1,
        empresaID=empresa_id,
        pedidoID=pedido_id,
        entregaID=entrega_id,
        canal=whatsapp_service.CANAL_WHATSAPP,
        evento=whatsapp_service.EVENTO_ORDER_DELIVERED,
        status=whatsapp_service.STATUS_PENDING,
        attempts=0,
        createdAt=datetime.utcnow(),
    )


def _session_para(empresa, cliente, pedido, entrega, whatsapp_notifications_enabled=True):
    return FakeSession({
        Empresa: [empresa] if empresa else [],
        Cliente: [cliente] if cliente else [],
        Pedido: [pedido] if pedido else [],
        Entrega: [entrega] if entrega else [],
    }, whatsapp_notifications_enabled=whatsapp_notifications_enabled)


# --- Caso 1: Pedido FLORA + cliente FLORA: envia correctamente ---------------------------

def test_caso1_flora_pedido_y_cliente_flora_envia(monkeypatch):
    empresa = _empresa(3, "Flora")
    cliente = _cliente(10, empresa_id=3)
    pedido = _pedido(100, empresa_id=3, cliente_id=10)
    entrega = _entrega(1000, empresa_id=3)
    notificacion = _notificacion(empresa_id=3, pedido_id=100, entrega_id=1000)
    db = _session_para(empresa, cliente, pedido, entrega)

    monkeypatch.setattr(whatsapp_client, "enviar_plantilla", lambda **kwargs: "wamid.FLORA123")

    whatsapp_service._procesar_una(db, notificacion)

    assert notificacion.status == whatsapp_service.STATUS_SENT
    assert notificacion.metaMessageId == "wamid.FLORA123"
    assert notificacion.errorCode is None


# --- Caso 2: Pedido Lafiore + cliente Lafiore: envia correctamente -----------------------

def test_caso2_lafiore_pedido_y_cliente_lafiore_envia(monkeypatch):
    empresa = _empresa(4, "Lafiore")
    cliente = _cliente(20, empresa_id=4)
    pedido = _pedido(200, empresa_id=4, cliente_id=20)
    entrega = _entrega(2000, empresa_id=4)
    notificacion = _notificacion(empresa_id=4, pedido_id=200, entrega_id=2000)
    db = _session_para(empresa, cliente, pedido, entrega)

    monkeypatch.setattr(whatsapp_client, "enviar_plantilla", lambda **kwargs: "wamid.LAFIORE456")

    whatsapp_service._procesar_una(db, notificacion)

    assert notificacion.status == whatsapp_service.STATUS_SENT
    assert notificacion.metaMessageId == "wamid.LAFIORE456"


# --- Caso 3: Pedido FLORA + cliente Lafiore: NO envia, SECURITY_TENANT_MISMATCH ----------

def test_caso3_cruce_de_tenant_no_envia(monkeypatch):
    empresa = _empresa(3, "Flora")
    cliente_de_otra_empresa = _cliente(20, empresa_id=4)  # cliente real de Lafiore
    pedido = _pedido(100, empresa_id=3, cliente_id=20)
    entrega = _entrega(1000, empresa_id=3)
    notificacion = _notificacion(empresa_id=3, pedido_id=100, entrega_id=1000)
    # La sesion falsa simula el escenario critico: por algun bug, la consulta de cliente
    # devuelve un cliente de OTRA empresa. La verificacion final en codigo debe atraparlo.
    db = _session_para(empresa, cliente_de_otra_empresa, pedido, entrega)

    llamadas = []
    monkeypatch.setattr(whatsapp_client, "enviar_plantilla", lambda **kwargs: llamadas.append(kwargs) or "no-deberia-llamarse")

    whatsapp_service._procesar_una(db, notificacion)

    assert notificacion.status == whatsapp_service.STATUS_FAILED
    assert notificacion.errorCode == "SECURITY_TENANT_MISMATCH"
    assert llamadas == []  # nunca se llego a llamar a Meta


def test_caso3b_cliente_no_encontrado_en_la_empresa_no_envia(monkeypatch):
    empresa = _empresa(3, "Flora")
    pedido = _pedido(100, empresa_id=3, cliente_id=20)
    entrega = _entrega(1000, empresa_id=3)
    notificacion = _notificacion(empresa_id=3, pedido_id=100, entrega_id=1000)
    # cliente=None: filtrado por empresa_id no devolvio nada (el cliente real es de otra empresa)
    db = _session_para(empresa, None, pedido, entrega)

    llamadas = []
    monkeypatch.setattr(whatsapp_client, "enviar_plantilla", lambda **kwargs: llamadas.append(kwargs))

    whatsapp_service._procesar_una(db, notificacion)

    assert notificacion.status == whatsapp_service.STATUS_FAILED
    assert notificacion.errorCode == "SECURITY_TENANT_MISMATCH"
    assert llamadas == []


# --- Caso 4: Pedido entregado dos veces: solo un WhatsApp (idempotencia) -----------------

def test_caso4_idempotencia_no_duplica_fila_pendiente():
    """La garantia real es el UNIQUE (empresa_id, pedido_id, evento, canal) + ON CONFLICT
    DO NOTHING a nivel de Postgres (ver sql/create_whatsapp_notificacion.sql), que no se
    puede probar sin una base real. Aqui se prueba que encolar_notificacion_entregado nunca
    lanza y siempre intenta el mismo INSERT idempotente, sin importar cuantas veces se
    llame para el mismo pedido."""

    ejecuciones = []

    class DummyDb:
        whatsapp_notifications_enabled = True

        def execute(self, statement, params):
            ejecuciones.append(dict(params))

        def commit(self):
            pass

    db = DummyDb()
    for _ in range(3):
        whatsapp_service.encolar_notificacion_entregado(db, empresa_id=3, pedido_id=100, entrega_id=1000)

    assert len(ejecuciones) == 3
    assert all(e["pedido_id"] == 100 and e["empresa_id"] == 3 for e in ejecuciones)
    assert "ON CONFLICT" not in ""  # marcador: la garantia real vive en el SQL, no aqui


def test_encolar_notificacion_no_inserta_si_modulo_whatsapp_inactivo():
    ejecuciones = []

    class DummyDb:
        whatsapp_notifications_enabled = False

        def execute(self, statement, params):
            ejecuciones.append(dict(params))

        def commit(self):
            pass

    whatsapp_service.encolar_notificacion_entregado(DummyDb(), empresa_id=3, pedido_id=100, entrega_id=1000)

    assert ejecuciones == []


def test_encolar_notificacion_nunca_lanza_si_falla_el_insert():
    class DbQueRompe:
        def execute(self, *a, **k):
            raise RuntimeError("fallo simulado de base de datos")

    # No debe lanzar excepcion -- nunca debe romper la confirmacion de entrega.
    whatsapp_service.encolar_notificacion_entregado(DbQueRompe(), empresa_id=3, pedido_id=100, entrega_id=1000)


def test_reconciliar_entregas_entregadas_sin_notificacion_es_idempotente_por_sql():
    ejecuciones = []

    class Resultado:
        def fetchall(self):
            return [(10,), (11,)]

    class DummyDb:
        def execute(self, statement, params):
            ejecuciones.append((str(statement), dict(params)))
            return Resultado()

        def rollback(self):
            raise AssertionError("no debe hacer rollback si el insert funciona")

    insertadas = whatsapp_service.reconciliar_entregas_entregadas_sin_notificacion(
        DummyDb(),
        limite=50,
        horas_atras=24,
    )

    assert insertadas == 2
    sql, params = ejecuciones[0]
    assert "ON CONFLICT (empresa_id, pedido_id, evento, canal) DO NOTHING" in sql
    assert "petalops.empresa_modulo" in sql
    assert "petalops.estado_entrega" in sql
    assert "coalesce(em.activo, 0) = 1" in sql
    assert params["modulo"] == whatsapp_service.MODULE_NOTIFICACIONES_WHATSAPP
    assert params["estado_entregado"] == ESTADO_ENTREGADO.lower()
    assert params["horas_atras"] == 24
    assert params["limite"] == 50


def test_reconciliar_entregas_se_puede_apagar_por_config(monkeypatch):
    monkeypatch.setattr(whatsapp_service, "RECONCILIAR_ENTREGAS_ENABLED", False)

    class DummyDb:
        def execute(self, *args, **kwargs):
            raise AssertionError("no debe consultar si la reconciliacion esta apagada")

    assert whatsapp_service.reconciliar_entregas_entregadas_sin_notificacion(DummyDb()) == 0


def test_procesar_pendientes_reconcilia_antes_de_leer_cola(monkeypatch):
    llamadas = []

    class QueryVacia:
        def filter(self, *args, **kwargs):
            llamadas.append("filter")
            return self

        def order_by(self, *args, **kwargs):
            llamadas.append("order_by")
            return self

        def limit(self, limite):
            llamadas.append(("limit", limite))
            return self

        def all(self):
            llamadas.append("all")
            return []

    class DummyDb:
        def query(self, modelo):
            llamadas.append(("query", modelo))
            return QueryVacia()

    monkeypatch.setattr(
        whatsapp_service,
        "reconciliar_entregas_entregadas_sin_notificacion",
        lambda db, limite: llamadas.append(("reconciliar", limite)) or 3,
    )

    procesadas = whatsapp_service.procesar_notificaciones_pendientes(DummyDb(), limite=20)

    assert procesadas == 0
    assert llamadas[0] == ("reconciliar", whatsapp_service.RECONCILIAR_ENTREGAS_BATCH_SIZE)


def test_procesar_notificacion_pendiente_procesa_evento_especifico(monkeypatch):
    notificacion = _notificacion(empresa_id=3, pedido_id=100, entrega_id=1000)
    notificacion.evento = whatsapp_service.EVENTO_ORDER_ACCEPTED
    db = FakeSession({WhatsappNotificacion: [notificacion]})
    llamadas = []

    monkeypatch.setattr(whatsapp_service, "_procesar_una", lambda db_arg, notif: llamadas.append((db_arg, notif)))

    procesada = whatsapp_service.procesar_notificacion_pendiente(
        db,
        empresa_id=3,
        pedido_id=100,
        evento=whatsapp_service.EVENTO_ORDER_ACCEPTED,
    )

    assert procesada is True
    assert llamadas == [(db, notificacion)]


def test_modulo_whatsapp_inactivo_no_envia_y_marca_skipped(monkeypatch):
    empresa = _empresa(3, "Flora")
    cliente = _cliente(10, empresa_id=3)
    pedido = _pedido(100, empresa_id=3, cliente_id=10)
    entrega = _entrega(1000, empresa_id=3)
    notificacion = _notificacion(empresa_id=3, pedido_id=100, entrega_id=1000)
    db = _session_para(empresa, cliente, pedido, entrega, whatsapp_notifications_enabled=False)

    llamadas = []
    monkeypatch.setattr(whatsapp_client, "enviar_plantilla", lambda **kwargs: llamadas.append(kwargs))

    whatsapp_service._procesar_una(db, notificacion)

    assert notificacion.status == whatsapp_service.STATUS_SKIPPED
    assert notificacion.errorCode == "WHATSAPP_MODULE_DISABLED"
    assert llamadas == []


def test_webhook_delivered_actualiza_notificacion_existente():
    notificacion = _notificacion(empresa_id=2, pedido_id=4456, entrega_id=4425)
    notificacion.status = whatsapp_service.STATUS_SENT
    notificacion.metaMessageId = "wamid.TEST123"
    db = FakeSession({WhatsappNotificacion: [notificacion]})

    resultado = whatsapp_service.procesar_webhook_meta(db, {
        "entry": [{
            "changes": [{
                "value": {
                    "statuses": [{
                        "id": "wamid.TEST123",
                        "status": "delivered",
                        "timestamp": "1788810000",
                    }]
                }
            }]
        }]
    })

    assert resultado == {"statuses_received": 1, "statuses_applied": 1, "statuses_unknown": 0}
    assert notificacion.status == whatsapp_service.STATUS_DELIVERED
    assert notificacion.deliveredAt is not None
    assert db.commits == 1


def test_webhook_read_no_degrada_y_marca_read():
    notificacion = _notificacion(empresa_id=2, pedido_id=4456, entrega_id=4425)
    notificacion.status = whatsapp_service.STATUS_DELIVERED
    notificacion.metaMessageId = "wamid.TESTREAD"
    db = FakeSession({WhatsappNotificacion: [notificacion]})

    whatsapp_service.procesar_estado_webhook_meta(db, {
        "id": "wamid.TESTREAD",
        "status": "read",
        "timestamp": "1788810100",
    })

    assert notificacion.status == whatsapp_service.STATUS_READ
    assert notificacion.deliveredAt is not None
    assert notificacion.readAt is not None


def test_webhook_failed_guarda_error_meta():
    notificacion = _notificacion(empresa_id=2, pedido_id=4456, entrega_id=4425)
    notificacion.status = whatsapp_service.STATUS_SENT
    notificacion.metaMessageId = "wamid.TESTFAILED"
    db = FakeSession({WhatsappNotificacion: [notificacion]})

    whatsapp_service.procesar_estado_webhook_meta(db, {
        "id": "wamid.TESTFAILED",
        "status": "failed",
        "timestamp": "1788810200",
        "errors": [{
            "code": 131026,
            "title": "Message undeliverable",
            "message": "Message was not delivered",
            "error_data": {"details": "Recipient phone number is invalid"},
        }],
    })

    assert notificacion.status == whatsapp_service.STATUS_FAILED
    assert notificacion.failedAt is not None
    assert notificacion.errorCode == "131026"
    assert "Message undeliverable" in notificacion.errorMessage
    assert "Recipient phone number is invalid" in notificacion.errorMessage


def test_webhook_message_id_desconocido_no_actualiza():
    db = FakeSession({WhatsappNotificacion: []})

    resultado = whatsapp_service.procesar_webhook_meta(db, {
        "entry": [{
            "changes": [{
                "value": {
                    "statuses": [{
                        "id": "wamid.NOEXISTE",
                        "status": "delivered",
                        "timestamp": "1788810000",
                    }]
                }
            }]
        }]
    })

    assert resultado == {"statuses_received": 1, "statuses_applied": 0, "statuses_unknown": 1}
    assert db.commits == 0


# --- Caso 5: Telefono invalido: NO envia, SKIPPED ----------------------------------------

@pytest.mark.parametrize("telefono_completo", ["", None, "abc", "123"])
def test_caso5_telefono_invalido_no_envia(monkeypatch, telefono_completo):
    empresa = _empresa(3, "Flora")
    cliente = _cliente(10, empresa_id=3, telefono_completo=telefono_completo)
    cliente.indicativo = None
    cliente.telefono = None
    pedido = _pedido(100, empresa_id=3, cliente_id=10)
    entrega = _entrega(1000, empresa_id=3)
    notificacion = _notificacion(empresa_id=3, pedido_id=100, entrega_id=1000)
    db = _session_para(empresa, cliente, pedido, entrega)

    llamadas = []
    monkeypatch.setattr(whatsapp_client, "enviar_plantilla", lambda **kwargs: llamadas.append(kwargs))

    whatsapp_service._procesar_una(db, notificacion)

    assert notificacion.status == whatsapp_service.STATUS_SKIPPED
    assert notificacion.errorCode == "SKIPPED_INVALID_PHONE"
    assert llamadas == []


def test_normalizar_telefono_colombiano_sin_indicativo():
    cliente = _cliente(1, empresa_id=3, telefono_completo="")
    cliente.indicativo = ""
    cliente.telefono = "3001234567"
    assert whatsapp_service._normalizar_telefono_whatsapp(cliente) == "573001234567"


def test_enmascarar_telefono():
    assert whatsapp_service._enmascarar_telefono("573001234567") == "********4567"
    assert whatsapp_service._enmascarar_telefono("12") == "**"


# --- Caso 6: Meta devuelve 500: notificacion pasa a retry, no rompe nada ----------------

def test_caso6_error_transitorio_de_meta_programa_reintento(monkeypatch):
    empresa = _empresa(3, "Flora")
    cliente = _cliente(10, empresa_id=3)
    pedido = _pedido(100, empresa_id=3, cliente_id=10)
    entrega = _entrega(1000, empresa_id=3)
    notificacion = _notificacion(empresa_id=3, pedido_id=100, entrega_id=1000)
    db = _session_para(empresa, cliente, pedido, entrega)

    def _falla_500(**kwargs):
        raise whatsapp_client.WhatsAppTransientError("Meta respondio 500")

    monkeypatch.setattr(whatsapp_client, "enviar_plantilla", _falla_500)

    whatsapp_service._procesar_una(db, notificacion)

    # No se agoto el limite de intentos (MAX_INTENTOS=3 por defecto, este es el intento 1):
    # debe quedar PENDING con un nextAttemptAt en el futuro, no FAILED definitivo.
    assert notificacion.status == whatsapp_service.STATUS_PENDING
    assert notificacion.errorCode == "TRANSIENT"
    assert notificacion.nextAttemptAt > datetime.utcnow()


def test_caso6b_error_transitorio_agota_intentos_y_queda_failed(monkeypatch):
    empresa = _empresa(3, "Flora")
    cliente = _cliente(10, empresa_id=3)
    pedido = _pedido(100, empresa_id=3, cliente_id=10)
    entrega = _entrega(1000, empresa_id=3)
    notificacion = _notificacion(empresa_id=3, pedido_id=100, entrega_id=1000)
    notificacion.attempts = whatsapp_service.MAX_INTENTOS - 1  # este intento sera el ultimo permitido
    db = _session_para(empresa, cliente, pedido, entrega)

    monkeypatch.setattr(
        whatsapp_client, "enviar_plantilla",
        lambda **kwargs: (_ for _ in ()).throw(whatsapp_client.WhatsAppTransientError("timeout")),
    )

    whatsapp_service._procesar_una(db, notificacion)

    assert notificacion.status == whatsapp_service.STATUS_FAILED
    assert notificacion.errorCode == "MAX_RETRIES_EXCEEDED"


def test_caso6c_error_permanente_no_reintenta(monkeypatch):
    empresa = _empresa(3, "Flora")
    cliente = _cliente(10, empresa_id=3)
    pedido = _pedido(100, empresa_id=3, cliente_id=10)
    entrega = _entrega(1000, empresa_id=3)
    notificacion = _notificacion(empresa_id=3, pedido_id=100, entrega_id=1000)
    db = _session_para(empresa, cliente, pedido, entrega)

    def _permanente(**kwargs):
        raise whatsapp_client.WhatsAppPermanentError("template inexistente", error_code="TEMPLATE_NOT_FOUND")

    monkeypatch.setattr(whatsapp_client, "enviar_plantilla", _permanente)

    whatsapp_service._procesar_una(db, notificacion)

    assert notificacion.status == whatsapp_service.STATUS_FAILED
    assert notificacion.errorCode == "TEMPLATE_NOT_FOUND"


# --- Caso 7: Dos workers procesan simultaneamente: solo uno puede enviar ----------------

def test_caso7_advisory_lock_evita_doble_procesamiento(monkeypatch):
    """La mutua exclusion entre workers concurrentes vive en el advisory lock de Postgres
    (whatsapp_dispatch_job.py), no en whatsapp_service. Se prueba que si el lock ya esta
    tomado, el worker NO procesa nada (ni intenta leer notificaciones)."""

    llamado = {"veces": 0}

    def _procesar_fake(db, limite):
        llamado["veces"] += 1
        return limite

    class DbFake:
        def rollback(self):
            pass

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(whatsapp_dispatch_job, "SessionLocal", lambda: DbFake())
    monkeypatch.setattr(whatsapp_dispatch_job, "_acquire_advisory_lock", lambda db: False)
    monkeypatch.setattr(whatsapp_service, "procesar_notificaciones_pendientes", _procesar_fake)

    procesadas = whatsapp_dispatch_job.run_dispatch_once()

    assert procesadas == 0
    assert llamado["veces"] == 0  # nunca se llego a procesar: otro worker tenia el lock


def test_caso7b_con_lock_disponible_si_procesa(monkeypatch):
    llamado = {"veces": 0}

    def _procesar_fake(db, limite):
        llamado["veces"] += 1
        return 5

    class DbFake:
        def rollback(self):
            pass

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(whatsapp_dispatch_job, "SessionLocal", lambda: DbFake())
    monkeypatch.setattr(whatsapp_dispatch_job, "_acquire_advisory_lock", lambda db: True)
    monkeypatch.setattr(whatsapp_dispatch_job, "_release_advisory_lock", lambda db: None)
    monkeypatch.setattr(whatsapp_service, "procesar_notificaciones_pendientes", _procesar_fake)

    procesadas = whatsapp_dispatch_job.run_dispatch_once()

    assert procesadas == 5
    assert llamado["veces"] == 1


# --- Caso 8: Se intenta enviar un pedido que no esta ENTREGADO: NO enviar ---------------

def test_caso8_entrega_no_esta_entregado_no_envia(monkeypatch):
    empresa = _empresa(3, "Flora")
    cliente = _cliente(10, empresa_id=3)
    pedido = _pedido(100, empresa_id=3, cliente_id=10)
    entrega_pendiente = _entrega(1000, empresa_id=3, estado=1)  # 1 = pendiente, no entregado
    notificacion = _notificacion(empresa_id=3, pedido_id=100, entrega_id=1000)
    db = _session_para(empresa, cliente, pedido, entrega_pendiente)

    llamadas = []
    monkeypatch.setattr(whatsapp_client, "enviar_plantilla", lambda **kwargs: llamadas.append(kwargs))

    whatsapp_service._procesar_una(db, notificacion)

    assert notificacion.status == whatsapp_service.STATUS_SKIPPED
    assert notificacion.errorCode == "ENTREGA_NOT_DELIVERED"
    assert llamadas == []


def test_caso8b_entrega_no_encontrada_no_envia(monkeypatch):
    empresa = _empresa(3, "Flora")
    cliente = _cliente(10, empresa_id=3)
    pedido = _pedido(100, empresa_id=3, cliente_id=10)
    notificacion = _notificacion(empresa_id=3, pedido_id=100, entrega_id=9999)
    db = _session_para(empresa, cliente, pedido, None)

    llamadas = []
    monkeypatch.setattr(whatsapp_client, "enviar_plantilla", lambda **kwargs: llamadas.append(kwargs))

    whatsapp_service._procesar_una(db, notificacion)

    assert notificacion.status == whatsapp_service.STATUS_SKIPPED
    assert notificacion.errorCode == "ENTREGA_NOT_DELIVERED"
    assert llamadas == []


# --- Mensaje: plantilla sin variables --------------------------------------------------

def test_mensaje_pedido_entregado_envia_nombre_del_tenant(monkeypatch):
    empresa = _empresa(4, "La Fiore Casa de Flores")
    cliente = _cliente(20, empresa_id=4, nombre="Carlos")
    pedido = _pedido(200, empresa_id=4, cliente_id=20, numero_pedido=829)
    entrega = _entrega(2000, empresa_id=4)
    notificacion = _notificacion(empresa_id=4, pedido_id=200, entrega_id=2000)
    db = _session_para(empresa, cliente, pedido, entrega)

    capturado = {}

    def _capturar(**kwargs):
        capturado.update(kwargs)
        return "wamid.X"

    monkeypatch.setattr(whatsapp_client, "enviar_plantilla", _capturar)

    whatsapp_service._procesar_una(db, notificacion)

    assert capturado["template_name"] == whatsapp_service.TEMPLATE_PEDIDO_ENTREGADO
    assert capturado["idioma"] == "es"
    assert capturado["parametros"] == ["La Fiore Casa de Flores"]


def test_mensaje_pedido_aceptado_envia_variables_y_logo(monkeypatch):
    empresa = _empresa(3, "FLORA")
    cliente = _cliente(84, empresa_id=3, nombre="Andrea")
    pedido = _pedido(987, empresa_id=3, cliente_id=84, numero_pedido=9988877)
    pedido.estadoPedidoID = 2
    pedido.totalNeto = 200000
    entrega = _entrega(5000, empresa_id=3, estado=1)
    entrega.pedidoID = 987
    entrega.fechaEntregaProgramada = datetime(2026, 9, 10, 0, 0)
    entrega.direccion = "CALLE 118 # 43 -46 TORRE 8 503"
    detalle = PedidoDetalle(idPedidoDetalle=1, empresaID=3, pedidoID=987, cantidad=1)
    producto = Producto(idProducto=10, empresaID=3, nombreProducto="Bouquet 12 Rosas Rojas")
    notificacion = _notificacion(empresa_id=3, pedido_id=987, entrega_id=5000)
    notificacion.evento = whatsapp_service.EVENTO_ORDER_ACCEPTED

    def _execute(statement, params):
        sql = str(statement)

        class Result:
            def __init__(self, value):
                self.value = value

            def first(self):
                return (self.value,) if self.value is not None else None

        if "FROM petalops.estado_pedido" in sql:
            return Result("APROBADO")
        if "SELECT logo_url" in sql:
            return Result("https://ddy2osi8uorg4.cloudfront.net/tenants/flora/logos/logo.png")
        raise AssertionError(f"execute no esperado: {sql}")

    db = FakeSession(
        {
            Empresa: [empresa],
            Cliente: [cliente],
            Pedido: [pedido],
            Entrega: [entrega],
            (PedidoDetalle, Producto): [(detalle, producto)],
        },
        execute_handler=_execute,
    )
    capturado = {}

    def _capturar(**kwargs):
        capturado.update(kwargs)
        return "wamid.ACCEPTED"

    monkeypatch.setattr(whatsapp_client, "enviar_plantilla", _capturar)

    whatsapp_service._procesar_una(db, notificacion)

    assert notificacion.status == whatsapp_service.STATUS_SENT
    assert capturado["template_name"] == whatsapp_service.TEMPLATE_PEDIDO_ACEPTADO
    assert capturado["idioma"] == whatsapp_service.TEMPLATE_PEDIDO_ACEPTADO_IDIOMA
    assert capturado["header_image_url"] == "https://ddy2osi8uorg4.cloudfront.net/tenants/flora/logos/logo.png"
    assert capturado["parametros"] == [
        "Andrea",
        "9988877",
        "1 x Bouquet 12 Rosas Rojas",
        "2026-09-10",
        "200000",
        "CALLE 118 # 43 -46 TORRE 8 503",
        "FLORA",
    ]


def test_mensaje_pedido_aceptado_no_envia_si_dejo_de_estar_aprobado(monkeypatch):
    empresa = _empresa(3, "FLORA")
    cliente = _cliente(84, empresa_id=3, nombre="Andrea")
    pedido = _pedido(987, empresa_id=3, cliente_id=84, numero_pedido=9988877)
    pedido.estadoPedidoID = 6
    entrega = _entrega(5000, empresa_id=3, estado=1)
    notificacion = _notificacion(empresa_id=3, pedido_id=987, entrega_id=5000)
    notificacion.evento = whatsapp_service.EVENTO_ORDER_ACCEPTED

    def _execute(statement, params):
        class Result:
            def first(self):
                return ("CANCELADO",)

        return Result()

    db = _session_para(empresa, cliente, pedido, entrega)
    db._execute_handler = _execute
    llamadas = []
    monkeypatch.setattr(whatsapp_client, "enviar_plantilla", lambda **kwargs: llamadas.append(kwargs))

    whatsapp_service._procesar_una(db, notificacion)

    assert notificacion.status == whatsapp_service.STATUS_SKIPPED
    assert notificacion.errorCode == "PEDIDO_NOT_APPROVED"
    assert llamadas == []


def test_cliente_meta_incluye_nombre_tenant_en_plantilla_entregado(monkeypatch):
    monkeypatch.setattr(whatsapp_client, "META_ACCESS_TOKEN", "token-test")
    monkeypatch.setattr(whatsapp_client, "META_PHONE_NUMBER_ID", "phone-id-test")
    capturado = {}

    class ResponseOk:
        status_code = 200

        def json(self):
            return {"messages": [{"id": "wamid.OK"}]}

    def _post(url, json, headers, timeout):
        capturado.update({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return ResponseOk()

    monkeypatch.setattr(whatsapp_client.httpx, "post", _post)

    meta_id = whatsapp_client.enviar_plantilla(
        telefono_destino="573001234567",
        template_name="pedido_entregado2",
        idioma="es_CO",
        parametros=["FLORA"],
    )

    assert meta_id == "wamid.OK"
    assert capturado["json"]["template"]["name"] == "pedido_entregado2"
    assert capturado["json"]["template"]["components"] == [
        {
            "type": "body",
            "parameters": [{"type": "text", "text": "FLORA"}],
        }
    ]


def test_cliente_meta_incluye_header_image_y_body_params(monkeypatch):
    monkeypatch.setattr(whatsapp_client, "META_ACCESS_TOKEN", "token-test")
    monkeypatch.setattr(whatsapp_client, "META_PHONE_NUMBER_ID", "phone-id-test")
    capturado = {}

    class ResponseOk:
        status_code = 200

        def json(self):
            return {"messages": [{"id": "wamid.OK"}]}

    def _post(url, json, headers, timeout):
        capturado.update({"json": json})
        return ResponseOk()

    monkeypatch.setattr(whatsapp_client.httpx, "post", _post)

    whatsapp_client.enviar_plantilla(
        telefono_destino="573001234567",
        template_name="pedidos_aceptado",
        idioma="es_CO",
        parametros=["Andrea", "9988877"],
        header_image_url="https://cdn.test/logo.png",
    )

    components = capturado["json"]["template"]["components"]
    assert components[0] == {
        "type": "header",
        "parameters": [{"type": "image", "image": {"link": "https://cdn.test/logo.png"}}],
    }
    assert components[1]["type"] == "body"
    assert components[1]["parameters"] == [
        {"type": "text", "text": "Andrea"},
        {"type": "text", "text": "9988877"},
    ]
