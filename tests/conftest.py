from datetime import datetime, timezone
import os
from uuid import uuid4

from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.security import pwd_context
from app.database import SessionLocal
from app.main import app
from app.models.rol import Rol
from app.models.usuario import Usuario
from app.routers.auth import _ensure_default_operational_roles

load_dotenv()


FLORA_EMPRESA_ID = 3
FLORA_SUCURSAL_ID = 3

TEST_ROLE_USERS = {
    "flora.admin": {
        "password": "FloraAdmin2026*",
        "nombre": "Flora Empresa Admin",
        "email": "flora.admin@empresa3.local",
        "rol": "Admin",
    },
    "flora.pedidos": {
        "password": "FloraPedidos2026*",
        "nombre": "Flora Pedidos",
        "email": "flora.pedidos@empresa3.local",
        "rol": "Pedidos",
    },
    "flora.florista1": {
        "password": "FloraFlorista12026*",
        "nombre": "Flora Florista 1",
        "email": "flora.florista1@empresa3.local",
        "rol": "Florista",
    },
    "flora.domi1": {
        "password": "FloraDomi12026*",
        "nombre": "Flora Domi 1",
        "email": "flora.domi1@empresa3.local",
        "rol": "Domiciliario",
    },
    "flora.inventario": {
        "password": "FloraInventario2026*",
        "nombre": "Flora Inventario",
        "email": "flora.inventario@empresa3.local",
        "rol": "Inventarista",
    },
}

DELIVERY_TRANSITIONS_REQUIRED = (
    (1, 2),  # Pendiente -> Asignado
    (1, 6),  # Pendiente -> Cancelado
    (2, 3),  # Asignado -> EnRuta
    (2, 6),  # Asignado -> Cancelado
    (3, 4),  # EnRuta -> Entregado
    (3, 5),  # EnRuta -> NoEntregado
    (5, 2),  # NoEntregado -> Asignado
    (5, 6),  # NoEntregado -> Cancelado
)


def integration_enabled() -> bool:
    return os.getenv("RUN_INTEGRATION_TESTS", "0") == "1"


def ensure_flora_test_users() -> None:
    session = SessionLocal()
    try:
        _ensure_default_operational_roles(session, FLORA_EMPRESA_ID)
        session.flush()

        roles = {
            str(role.nombreRol or "").strip(): int(role.idRol)
            for role in session.query(Rol).filter(Rol.empresaID == FLORA_EMPRESA_ID).all()
        }

        now = datetime.now(timezone.utc)
        for login, cfg in TEST_ROLE_USERS.items():
            role_id = roles.get(cfg["rol"])
            if role_id is None:
                continue

            user = session.query(Usuario).filter(Usuario.login == login).first()
            if not user:
                user = Usuario(
                    empresaID=FLORA_EMPRESA_ID,
                    sucursalID=FLORA_SUCURSAL_ID,
                    nombre=cfg["nombre"],
                    login=login,
                    email=cfg["email"],
                    passwordHash=pwd_context.hash(cfg["password"]),
                    rolID=role_id,
                    estado="Activo",
                    esSuperadmin=False,
                    createdAt=now,
                    updatedAt=now,
                )
                session.add(user)
            else:
                # Non-invasive integration mode:
                # never rewrite existing users or passwords from tests.
                continue

        session.commit()
    finally:
        session.close()


def integration_client() -> TestClient:
    return TestClient(app)


def login_joinadmin(client: TestClient) -> dict:
    response = client.post("/auth/login", json={"login": "joinadmin", "password": "Admin123*"})
    assert response.status_code == 200, response.text
    return response.json()


def login_user(client: TestClient, login: str, password: str) -> dict:
    response = client.post("/auth/login", json={"login": login, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def global_admin_headers(client: TestClient) -> dict[str, str]:
    payload = login_joinadmin(client)
    return {"Authorization": f"Bearer {payload['accessToken']}"}


def auth_headers_for_user(client: TestClient, login: str, password: str) -> tuple[dict[str, str], dict]:
    payload = login_user(client, login, password)
    return {"Authorization": f"Bearer {payload['accessToken']}"}, payload["user"]


def impersonated_headers(
    client: TestClient,
    *,
    empresa_id: int = FLORA_EMPRESA_ID,
    sucursal_id: int = FLORA_SUCURSAL_ID,
) -> tuple[dict[str, str], dict]:
    login_payload = login_joinadmin(client)
    headers = {"Authorization": f"Bearer {login_payload['accessToken']}"}
    response = client.post(
        "/auth/impersonate",
        json={"empresaID": empresa_id, "sucursalID": sucursal_id},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return {"Authorization": f"Bearer {payload['accessToken']}"}, payload["user"]


def ensure_delivery_transition_catalog(empresa_id: int = FLORA_EMPRESA_ID) -> list[int]:
    session = SessionLocal()
    inserted_ids: list[int] = []
    try:
        existing_rows = session.execute(
            text(
                """
                SELECT estado_origen_id, estado_destino_id
                FROM petalops.transicion_estado_entrega
                WHERE empresa_id = :empresa_id
                """
            ),
            {"empresa_id": int(empresa_id)},
        ).fetchall()
        existing = {(int(origen), int(destino)) for origen, destino in existing_rows}
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for origen_id, destino_id in DELIVERY_TRANSITIONS_REQUIRED:
            if (origen_id, destino_id) in existing:
                continue
            row = session.execute(
                text(
                    """
                    INSERT INTO petalops.transicion_estado_entrega (
                        empresa_id,
                        estado_origen_id,
                        estado_destino_id,
                        created_at
                    )
                    VALUES (
                        :empresa_id,
                        :estado_origen_id,
                        :estado_destino_id,
                        :created_at
                    )
                    RETURNING id_tran_estado_ent
                    """
                ),
                {
                    "empresa_id": int(empresa_id),
                    "estado_origen_id": int(origen_id),
                    "estado_destino_id": int(destino_id),
                    "created_at": now,
                },
            ).first()
            if row and row[0] is not None:
                inserted_ids.append(int(row[0]))

        session.commit()
        return inserted_ids
    finally:
        session.close()


def cleanup_delivery_transition_catalog(inserted_ids: list[int]) -> None:
    if not inserted_ids:
        return

    session = SessionLocal()
    try:
        session.execute(
            text(
                """
                DELETE FROM petalops.transicion_estado_entrega
                WHERE id_tran_estado_ent = ANY(:ids)
                """
            ),
            {"ids": inserted_ids},
        )
        session.commit()
    finally:
        session.close()


def create_ephemeral_courier_user() -> dict[str, int | str]:
    session = SessionLocal()
    try:
        _ensure_default_operational_roles(session, FLORA_EMPRESA_ID)
        session.flush()

        role_row = session.execute(
            text(
                """
                SELECT id_rol
                FROM petalops.rol
                WHERE empresa_id = :empresa_id
                  AND nombre_rol = 'Domiciliario'
                LIMIT 1
                """
            ),
            {"empresa_id": int(FLORA_EMPRESA_ID)},
        ).first()
        assert role_row is not None, "No existe rol Domiciliario para empresa 3"

        suffix = uuid4().hex[:10]
        login = f"qa.domi.{suffix}"
        password = f"QaDomi{suffix[:4]}*2026"
        email = f"{login}@example.com"
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        user_row = session.execute(
            text(
                """
                INSERT INTO petalops.usuario (
                    empresa_id,
                    sucursal_id,
                    nombre,
                    login,
                    email,
                    passwordhash,
                    rolid,
                    estado,
                    es_superadmin,
                    created_at,
                    updated_at
                )
                VALUES (
                    :empresa_id,
                    :sucursal_id,
                    :nombre,
                    :login,
                    :email,
                    :password_hash,
                    :rol_id,
                    :estado,
                    :es_superadmin,
                    :created_at,
                    :updated_at
                )
                RETURNING id_usuario
                """
            ),
            {
                "empresa_id": int(FLORA_EMPRESA_ID),
                "sucursal_id": int(FLORA_SUCURSAL_ID),
                "nombre": f"QA Courier {suffix}",
                "login": login,
                "email": email,
                "password_hash": pwd_context.hash(password),
                "rol_id": int(role_row[0]),
                "estado": "Activo",
                "es_superadmin": False,
                "created_at": now,
                "updated_at": now,
            },
        ).first()
        assert user_row is not None and user_row[0] is not None
        user_id = int(user_row[0])

        empleado_row = session.execute(
            text(
                """
                INSERT INTO petalops.empleado (
                    empresa_id,
                    sucursal_id,
                    nombre_empleado,
                    cargo,
                    activo,
                    created_at,
                    updated_at,
                    usuario,
                    email,
                    usuario_id,
                    is_superuser
                )
                VALUES (
                    :empresa_id,
                    :sucursal_id,
                    :nombre_empleado,
                    :cargo,
                    :activo,
                    :created_at,
                    :updated_at,
                    :usuario,
                    :email,
                    :usuario_id,
                    :is_superuser
                )
                RETURNING id_empleado
                """
            ),
            {
                "empresa_id": int(FLORA_EMPRESA_ID),
                "sucursal_id": int(FLORA_SUCURSAL_ID),
                "nombre_empleado": f"QA Courier {suffix}",
                "cargo": "Domiciliario",
                "activo": 1,
                "created_at": now,
                "updated_at": now,
                "usuario": login,
                "email": email,
                "usuario_id": user_id,
                "is_superuser": 0,
            },
        ).first()
        assert empleado_row is not None and empleado_row[0] is not None

        session.commit()
        return {
            "login": login,
            "password": password,
            "user_id": user_id,
            "empleado_id": int(empleado_row[0]),
        }
    finally:
        session.close()


def cleanup_ephemeral_courier_user(user_id: int | None, empleado_id: int | None) -> None:
    if user_id is None and empleado_id is None:
        return

    session = SessionLocal()
    try:
        if empleado_id is not None:
            session.execute(
                text(
                    """
                    DELETE FROM petalops.empleado
                    WHERE id_empleado = :empleado_id
                      AND empresa_id = :empresa_id
                    """
                ),
                {"empleado_id": int(empleado_id), "empresa_id": int(FLORA_EMPRESA_ID)},
            )
        if user_id is not None:
            session.execute(
                text("DELETE FROM petalops.usuario_modulo WHERE usuario_id = :user_id"),
                {"user_id": int(user_id)},
            )
            session.execute(
                text(
                    """
                    DELETE FROM petalops.usuario
                    WHERE id_usuario = :user_id
                      AND empresa_id = :empresa_id
                    """
                ),
                {"user_id": int(user_id), "empresa_id": int(FLORA_EMPRESA_ID)},
            )
        session.commit()
    finally:
        session.close()


def cleanup_test_order(pedido_id: int, *, empresa_id: int = FLORA_EMPRESA_ID) -> None:
    session = SessionLocal()
    try:
        cliente_row = session.execute(
            text(
                """
                SELECT cliente_id
                FROM petalops.pedido
                WHERE id_pedido = :pedido_id
                  AND empresa_id = :empresa_id
                """
            ),
            {"pedido_id": int(pedido_id), "empresa_id": int(empresa_id)},
        ).first()
        cliente_id = int(cliente_row[0]) if cliente_row and cliente_row[0] is not None else None

        session.execute(
            text(
                """
                DELETE FROM petalops.entrega
                WHERE pedido_id = :pedido_id
                  AND empresa_id = :empresa_id
                """
            ),
            {"pedido_id": int(pedido_id), "empresa_id": int(empresa_id)},
        )
        session.execute(
            text(
                """
                DELETE FROM petalops.produccion_historial
                WHERE empresa_id = :empresa_id
                  AND produccion_id IN (
                    SELECT id_produccion
                    FROM petalops.produccion
                    WHERE pedido_id = :pedido_id
                      AND empresa_id = :empresa_id
                  )
                """
            ),
            {"pedido_id": int(pedido_id), "empresa_id": int(empresa_id)},
        )
        session.execute(
            text(
                """
                DELETE FROM petalops.produccion
                WHERE pedido_id = :pedido_id
                  AND empresa_id = :empresa_id
                """
            ),
            {"pedido_id": int(pedido_id), "empresa_id": int(empresa_id)},
        )
        session.execute(
            text(
                """
                DELETE FROM petalops.pago_metodo
                WHERE pedido_id = :pedido_id
                  AND empresa_id = :empresa_id
                """
            ),
            {"pedido_id": int(pedido_id), "empresa_id": int(empresa_id)},
        )
        session.execute(
            text(
                """
                DELETE FROM petalops.pedido_canal_venta
                WHERE pedido_id = :pedido_id
                  AND empresa_id = :empresa_id
                """
            ),
            {"pedido_id": int(pedido_id), "empresa_id": int(empresa_id)},
        )
        session.execute(
            text(
                """
                DELETE FROM petalops.pago
                WHERE pedido_id = :pedido_id
                  AND empresa_id = :empresa_id
                """
            ),
            {"pedido_id": int(pedido_id), "empresa_id": int(empresa_id)},
        )
        session.execute(
            text(
                """
                DELETE FROM petalops.pedido_detalle
                WHERE pedido_id = :pedido_id
                  AND empresa_id = :empresa_id
                """
            ),
            {"pedido_id": int(pedido_id), "empresa_id": int(empresa_id)},
        )
        session.execute(
            text(
                """
                DELETE FROM petalops.pedido
                WHERE id_pedido = :pedido_id
                  AND empresa_id = :empresa_id
                """
            ),
            {"pedido_id": int(pedido_id), "empresa_id": int(empresa_id)},
        )
        if cliente_id is not None:
            session.execute(
                text(
                    """
                    DELETE FROM petalops.cliente
                    WHERE cliente_id = :cliente_id
                      AND empresa_id = :empresa_id
                      AND (
                        identificacion LIKE 'QA-E2E-%'
                        OR nombre_completo LIKE 'QA E2E %'
                      )
                    """
                ),
                {"cliente_id": int(cliente_id), "empresa_id": int(empresa_id)},
            )
        session.commit()
    finally:
        session.close()
