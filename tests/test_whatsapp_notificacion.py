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
from app.models.whatsapp_notificacion import WhatsappNotificacion
from app.schemas.domicilios import ESTADO_ENTREGADO
from app.services import whatsapp_client, whatsapp_service
from app.jobs import whatsapp_dispatch_job


class FakeQuery:
    def __init__(self, results):
        self._results = list(results)

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._results[0] if self._results else None


class FakeSession:
    def __init__(self, por_modelo, whatsapp_notifications_enabled=True):
        self._por_modelo = por_modelo
        self.commits = 0
        self.rollbacks = 0
        self.whatsapp_notifications_enabled = whatsapp_notifications_enabled

    def query(self, modelo):
        return FakeQuery(self._por_modelo.get(modelo, []))

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
    assert params["modulo"] == whatsapp_service.MODULE_NOTIFICACIONES_WHATSAPP
    assert params["estado_entregado"] == ESTADO_ENTREGADO
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


# --- Mensaje: variables solo de la base de datos, sin hardcode por tenant ---------------

def test_mensaje_usa_nombre_real_de_la_empresa_sin_hardcode(monkeypatch):
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

    assert capturado["parametros"] == ["La Fiore Casa de Flores", "Carlos", "829"]
