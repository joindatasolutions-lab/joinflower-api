import json
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

# Los dos campos dinamicos de petalops.empresa_menu que dependen de un catalogo
# normalizado. opciones_json de cada uno se mantiene sincronizado con su tabla
# via sync_empresa_menu_opciones — cualquier codigo que inserte o desactive
# filas en metodo_pago_catalogo/canal_venta debe llamarla despues, o el campo
# nunca aparece en el formulario de pedido aunque el catalogo tenga datos.
CAMPOS_CATALOGO = {
    "pedido_metodos_pago": {
        "tabla": "metodo_pago_catalogo",
        "id_columna": "id_metodo_pago",
        "titulo_defecto": "Metodos de pago",
        "tipo_control": "multi_select",
        "orden_defecto": 10,
    },
    "pedido_canal_venta": {
        "tabla": "canal_venta",
        "id_columna": "id_canal_venta",
        "titulo_defecto": "Canal de venta",
        "tipo_control": "select",
        "orden_defecto": 20,
    },
}


def catalog_code_from_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return normalized or "item"


def sync_empresa_menu_opciones(db: Session, *, empresa_id: int, campo: str) -> None:
    meta = CAMPOS_CATALOGO[campo]
    opciones_rows = db.execute(
        text(
            f"""
            SELECT nombre
            FROM petalops.{meta["tabla"]}
            WHERE empresa_id = :empresa_id
              AND activo = TRUE
            ORDER BY orden ASC, nombre ASC
            """
        ),
        {"empresa_id": empresa_id},
    ).scalars().all()
    opciones_json = json.dumps([str(nombre) for nombre in opciones_rows])

    existing = db.execute(
        text(
            """
            SELECT id_empresa_menu
            FROM petalops.empresa_menu
            WHERE empresa_id = :empresa_id
              AND codigo = :codigo
              AND seccion = 'pedido_detalle'
            """
        ),
        {"empresa_id": empresa_id, "codigo": campo},
    ).first()

    if existing:
        db.execute(
            text(
                """
                UPDATE petalops.empresa_menu
                SET opciones_json = CAST(:opciones AS JSONB),
                    updated_at = NOW()
                WHERE id_empresa_menu = :id_empresa_menu
                """
            ),
            {"opciones": opciones_json, "id_empresa_menu": int(existing[0])},
        )
        return

    db.execute(
        text(
            """
            INSERT INTO petalops.empresa_menu (
                empresa_id, codigo, titulo, seccion, tipo_control,
                opciones_json, requerido_aprobacion, activo, orden, created_at, updated_at
            ) VALUES (
                :empresa_id, :codigo, :titulo, 'pedido_detalle', :tipo_control,
                CAST(:opciones AS JSONB), FALSE, TRUE, :orden, NOW(), NOW()
            )
            """
        ),
        {
            "empresa_id": empresa_id,
            "codigo": campo,
            "titulo": meta["titulo_defecto"],
            "tipo_control": meta["tipo_control"],
            "opciones": opciones_json,
            "orden": meta["orden_defecto"],
        },
    )
