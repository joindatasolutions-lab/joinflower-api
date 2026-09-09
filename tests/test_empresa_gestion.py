"""Pruebas de los endpoints nuevos de gestion de empresa (superusuario joinadmin):
GET/PUT /auth/usuarios/empresas/{id} y GET/PUT /auth/usuarios/empresas/{id}/tema.

Usa una sesion falsa (sin base de datos real) para poder ejercitar la logica real de los
routers sin depender de Postgres ni tocar datos de empresas reales.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.tema import Tema
from app.routers import auth as auth_router
from app.schemas.auth import EmpresaUpdateRequest, TemaUpdateRequest


class FakeMappingResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class FakeExecuteResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return FakeMappingResult(self._row)


class FakeQuery:
    def __init__(self, results):
        self._results = list(results)

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._results[0] if self._results else None


class FakeSession:
    def __init__(self, empresa_row=None, tema=None):
        self._empresa_row = empresa_row
        self._tema = tema
        self.executed = []
        self.commits = 0
        self.rollbacks = 0
        self.added = []

    def execute(self, statement, params=None):
        self.executed.append((str(statement), params))
        return FakeExecuteResult(self._empresa_row)

    def query(self, model):
        assert model is Tema
        return FakeQuery([self._tema] if self._tema else [])

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, obj):
        pass


EMPRESA_ROW = {
    "id_empresa": 999,
    "nombre_empresa": "Empresa Prueba",
    "nombre_comercial": "Empresa Prueba SAS",
    "nit": "NIT-999",
    "estado": 1,
    "slug": "empresa-prueba",
    "dominio": None,
    "logo_url": None,
    "plan_id": 1,
    "celular": "3000000000",
    "ciudad": "Bogota",
    "direccion": "Calle 1",
    "nombre_responsable": "Juan Perez",
    "cargo_responsable": "Gerente",
    "correo_responsable": "juan@empresa.com",
    "celular_responsable": "3111111111",
}

FAKE_AUTH = SimpleNamespace(userID=1, login="joinadmin", empresaID=1)


def test_obtener_empresa_retorna_detalle_completo():
    db = FakeSession(empresa_row=EMPRESA_ROW)

    resultado = auth_router.obtener_empresa(empresa_id=999, db=db, _auth=FAKE_AUTH)

    assert resultado.empresaID == 999
    assert resultado.nombreComercial == "Empresa Prueba SAS"
    assert resultado.estado == "Activo"
    assert resultado.celular == "3000000000"
    assert resultado.nombreResponsable == "Juan Perez"


def test_obtener_empresa_inexistente_da_404():
    db = FakeSession(empresa_row=None)

    with pytest.raises(HTTPException) as exc_info:
        auth_router.obtener_empresa(empresa_id=12345, db=db, _auth=FAKE_AUTH)

    assert exc_info.value.status_code == 404


def test_actualizar_empresa_solo_cambia_campos_enviados():
    db = FakeSession(empresa_row=EMPRESA_ROW)
    payload = EmpresaUpdateRequest(ciudad="Medellin", nombreResponsable="Maria Gomez")

    resultado = auth_router.actualizar_empresa(empresa_id=999, payload=payload, db=db, auth=FAKE_AUTH)

    assert resultado.status == "ok"
    assert db.commits == 1
    update_statement, update_params = db.executed[-1]
    assert "UPDATE petalops.empresa" in update_statement
    assert update_params["ciudad"] == "Medellin"
    assert update_params["nombre_responsable"] == "Maria Gomez"
    assert "nit" not in update_params  # no se envio, no debe tocarse


def test_actualizar_empresa_estado_invalido_rechaza():
    db = FakeSession(empresa_row=EMPRESA_ROW)
    payload = EmpresaUpdateRequest(estado="Suspendido")

    with pytest.raises(HTTPException) as exc_info:
        auth_router.actualizar_empresa(empresa_id=999, payload=payload, db=db, auth=FAKE_AUTH)

    assert exc_info.value.status_code == 400
    assert db.rollbacks == 1


def test_obtener_tema_sin_fila_retorna_nulos():
    db = FakeSession(empresa_row=EMPRESA_ROW, tema=None)

    resultado = auth_router.obtener_tema_empresa(empresa_id=999, db=db, _auth=FAKE_AUTH)

    assert resultado.empresaID == 999
    assert resultado.colorPrimario is None
    assert resultado.fuenteFamilia is None


def test_obtener_tema_con_fila_retorna_valores():
    tema = Tema(empresaID=999, colorPrimario="#3A554D", colorSecundario="#C1A057", fuenteFamilia="Montserrat, sans-serif")
    db = FakeSession(empresa_row=EMPRESA_ROW, tema=tema)

    resultado = auth_router.obtener_tema_empresa(empresa_id=999, db=db, _auth=FAKE_AUTH)

    assert resultado.colorPrimario == "#3A554D"
    assert resultado.fuenteFamilia == "Montserrat, sans-serif"


def test_actualizar_tema_crea_fila_si_no_existe():
    db = FakeSession(empresa_row=EMPRESA_ROW, tema=None)
    payload = TemaUpdateRequest(colorPrimario="#3A554D", colorSecundario="#C1A057", fuenteFamilia="Cormorant, serif")

    resultado = auth_router.actualizar_tema_empresa(empresa_id=999, payload=payload, db=db, auth=FAKE_AUTH)

    assert len(db.added) == 1
    assert db.added[0].colorPrimario == "#3A554D"
    assert resultado.colorSecundario == "#C1A057"


def test_actualizar_tema_actualiza_fila_existente_sin_crear_otra():
    tema = Tema(empresaID=999, colorPrimario="#111111", colorSecundario="#222222", fuenteFamilia="Segoe UI, Tahoma, Geneva, Verdana, sans-serif")
    db = FakeSession(empresa_row=EMPRESA_ROW, tema=tema)
    payload = TemaUpdateRequest(colorPrimario="#3A554D", colorSecundario="#C1A057", fuenteFamilia="Montserrat, sans-serif")

    auth_router.actualizar_tema_empresa(empresa_id=999, payload=payload, db=db, auth=FAKE_AUTH)

    assert len(db.added) == 0  # reutiliza la fila existente, no crea una nueva
    assert tema.colorPrimario == "#3A554D"
    assert tema.fuenteFamilia == "Montserrat, sans-serif"


def test_tema_update_request_rechaza_color_invalido():
    with pytest.raises(Exception):
        TemaUpdateRequest(colorPrimario="no-es-un-color", colorSecundario="#C1A057", fuenteFamilia="Montserrat")
