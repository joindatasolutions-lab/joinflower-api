import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import assert_same_empresa, require_admin_role
from app.database import get_db
from app.schemas.configuracion import (
    CatalogoCreateRequest,
    CatalogoItem,
    CatalogoListResponse,
    CatalogoUpdateRequest,
    MenuCampoItem,
    MenuCampoListResponse,
    MenuCampoUpdateRequest,
)
from app.services.empresa_menu_service import (
    CAMPOS_CATALOGO as _CAMPOS,
    catalog_code_from_name as _catalog_code_from_name,
    sync_empresa_menu_opciones as _sync_empresa_menu_opciones,
)

router = APIRouter(prefix="/configuracion", tags=["Configuracion"])


def _next_orden(db: Session, *, tabla: str, empresa_id: int) -> int:
    row = db.execute(
        text(f"SELECT COALESCE(MAX(orden), 0) + 1 FROM petalops.{tabla} WHERE empresa_id = :empresa_id"),
        {"empresa_id": empresa_id},
    ).first()
    return int(row[0] or 1) if row else 1


def _listar_catalogo(db: Session, *, empresa_id: int, campo: str) -> CatalogoListResponse:
    meta = _CAMPOS[campo]
    rows = db.execute(
        text(
            f"""
            SELECT {meta["id_columna"]} AS id, codigo, nombre, orden, activo
            FROM petalops.{meta["tabla"]}
            WHERE empresa_id = :empresa_id
            ORDER BY orden ASC, nombre ASC
            """
        ),
        {"empresa_id": empresa_id},
    ).mappings().all()
    return CatalogoListResponse(
        items=[
            CatalogoItem(
                id=int(row["id"]),
                codigo=str(row["codigo"]),
                nombre=str(row["nombre"]),
                orden=int(row["orden"] or 0),
                activo=bool(row["activo"]),
            )
            for row in rows
        ]
    )


def _crear_catalogo_item(db: Session, *, empresa_id: int, campo: str, nombre: str) -> CatalogoItem:
    meta = _CAMPOS[campo]
    nombre = nombre.strip()
    if not nombre:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El nombre es obligatorio")

    duplicado = db.execute(
        text(
            f"""
            SELECT 1 FROM petalops.{meta["tabla"]}
            WHERE empresa_id = :empresa_id AND lower(nombre) = lower(:nombre)
            """
        ),
        {"empresa_id": empresa_id, "nombre": nombre},
    ).first()
    if duplicado:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe un elemento con ese nombre")

    orden = _next_orden(db, tabla=meta["tabla"], empresa_id=empresa_id)
    codigo = _catalog_code_from_name(nombre)
    inserted = db.execute(
        text(
            f"""
            INSERT INTO petalops.{meta["tabla"]} (
                empresa_id, codigo, nombre, orden, activo, created_at, updated_at
            ) VALUES (
                :empresa_id, :codigo, :nombre, :orden, TRUE, NOW(), NOW()
            )
            RETURNING {meta["id_columna"]}
            """
        ),
        {"empresa_id": empresa_id, "codigo": codigo, "nombre": nombre, "orden": orden},
    ).first()

    _sync_empresa_menu_opciones(db, empresa_id=empresa_id, campo=campo)
    db.commit()

    return CatalogoItem(id=int(inserted[0]), codigo=codigo, nombre=nombre, orden=orden, activo=True)


def _actualizar_catalogo_item(
    db: Session, *, empresa_id: int, campo: str, item_id: int, payload: CatalogoUpdateRequest
) -> CatalogoItem:
    meta = _CAMPOS[campo]
    row = db.execute(
        text(
            f"""
            SELECT {meta["id_columna"]} AS id, codigo, nombre, orden, activo
            FROM petalops.{meta["tabla"]}
            WHERE empresa_id = :empresa_id AND {meta["id_columna"]} = :item_id
            """
        ),
        {"empresa_id": empresa_id, "item_id": item_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Elemento no encontrado")

    nuevo_nombre = row["nombre"] if payload.nombre is None else payload.nombre.strip()
    if not nuevo_nombre:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El nombre es obligatorio")
    nuevo_orden = row["orden"] if payload.orden is None else payload.orden
    nuevo_activo = row["activo"] if payload.activo is None else payload.activo

    if payload.nombre is not None and nuevo_nombre.lower() != str(row["nombre"]).lower():
        duplicado = db.execute(
            text(
                f"""
                SELECT 1 FROM petalops.{meta["tabla"]}
                WHERE empresa_id = :empresa_id AND lower(nombre) = lower(:nombre)
                  AND {meta["id_columna"]} != :item_id
                """
            ),
            {"empresa_id": empresa_id, "nombre": nuevo_nombre, "item_id": item_id},
        ).first()
        if duplicado:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe un elemento con ese nombre")

    db.execute(
        text(
            f"""
            UPDATE petalops.{meta["tabla"]}
            SET nombre = :nombre, orden = :orden, activo = :activo, updated_at = NOW()
            WHERE empresa_id = :empresa_id AND {meta["id_columna"]} = :item_id
            """
        ),
        {
            "nombre": nuevo_nombre,
            "orden": nuevo_orden,
            "activo": bool(nuevo_activo),
            "empresa_id": empresa_id,
            "item_id": item_id,
        },
    )

    _sync_empresa_menu_opciones(db, empresa_id=empresa_id, campo=campo)
    db.commit()

    return CatalogoItem(
        id=item_id, codigo=str(row["codigo"]), nombre=nuevo_nombre, orden=int(nuevo_orden), activo=bool(nuevo_activo)
    )


@router.get("/empresas/{empresa_id}/metodos-pago", response_model=CatalogoListResponse)
def listar_metodos_pago(empresa_id: int, db: Session = Depends(get_db), auth=Depends(require_admin_role)):
    assert_same_empresa(auth, empresa_id)
    return _listar_catalogo(db, empresa_id=empresa_id, campo="pedido_metodos_pago")


@router.post("/empresas/{empresa_id}/metodos-pago", response_model=CatalogoItem, status_code=status.HTTP_201_CREATED)
def crear_metodo_pago(
    empresa_id: int, payload: CatalogoCreateRequest, db: Session = Depends(get_db), auth=Depends(require_admin_role)
):
    assert_same_empresa(auth, empresa_id)
    return _crear_catalogo_item(db, empresa_id=empresa_id, campo="pedido_metodos_pago", nombre=payload.nombre)


@router.patch("/empresas/{empresa_id}/metodos-pago/{item_id}", response_model=CatalogoItem)
def actualizar_metodo_pago(
    empresa_id: int,
    item_id: int,
    payload: CatalogoUpdateRequest,
    db: Session = Depends(get_db),
    auth=Depends(require_admin_role),
):
    assert_same_empresa(auth, empresa_id)
    return _actualizar_catalogo_item(
        db, empresa_id=empresa_id, campo="pedido_metodos_pago", item_id=item_id, payload=payload
    )


@router.get("/empresas/{empresa_id}/canales-venta", response_model=CatalogoListResponse)
def listar_canales_venta(empresa_id: int, db: Session = Depends(get_db), auth=Depends(require_admin_role)):
    assert_same_empresa(auth, empresa_id)
    return _listar_catalogo(db, empresa_id=empresa_id, campo="pedido_canal_venta")


@router.post("/empresas/{empresa_id}/canales-venta", response_model=CatalogoItem, status_code=status.HTTP_201_CREATED)
def crear_canal_venta(
    empresa_id: int, payload: CatalogoCreateRequest, db: Session = Depends(get_db), auth=Depends(require_admin_role)
):
    assert_same_empresa(auth, empresa_id)
    return _crear_catalogo_item(db, empresa_id=empresa_id, campo="pedido_canal_venta", nombre=payload.nombre)


@router.patch("/empresas/{empresa_id}/canales-venta/{item_id}", response_model=CatalogoItem)
def actualizar_canal_venta(
    empresa_id: int,
    item_id: int,
    payload: CatalogoUpdateRequest,
    db: Session = Depends(get_db),
    auth=Depends(require_admin_role),
):
    assert_same_empresa(auth, empresa_id)
    return _actualizar_catalogo_item(
        db, empresa_id=empresa_id, campo="pedido_canal_venta", item_id=item_id, payload=payload
    )


@router.get("/empresas/{empresa_id}/menu-pedido", response_model=MenuCampoListResponse)
def listar_menu_pedido(empresa_id: int, db: Session = Depends(get_db), auth=Depends(require_admin_role)):
    assert_same_empresa(auth, empresa_id)

    items = []
    for campo, meta in _CAMPOS.items():
        row = db.execute(
            text(
                """
                SELECT titulo, tipo_control, opciones_json, requerido_aprobacion, activo, orden
                FROM petalops.empresa_menu
                WHERE empresa_id = :empresa_id AND codigo = :codigo AND seccion = 'pedido_detalle'
                """
            ),
            {"empresa_id": empresa_id, "codigo": campo},
        ).mappings().first()

        if row:
            opciones = row["opciones_json"]
            if isinstance(opciones, str):
                try:
                    opciones = json.loads(opciones)
                except ValueError:
                    opciones = []
            total_opciones = len(opciones) if isinstance(opciones, list) else 0
            items.append(
                MenuCampoItem(
                    codigo=campo,
                    titulo=str(row["titulo"]),
                    tipoControl=str(row["tipo_control"]),
                    requeridoAprobacion=bool(row["requerido_aprobacion"]),
                    activo=bool(row["activo"]),
                    orden=int(row["orden"] or 0),
                    totalOpciones=total_opciones,
                )
            )
        else:
            items.append(
                MenuCampoItem(
                    codigo=campo,
                    titulo=meta["titulo_defecto"],
                    tipoControl=meta["tipo_control"],
                    requeridoAprobacion=False,
                    activo=False,
                    orden=meta["orden_defecto"],
                    totalOpciones=0,
                )
            )

    return MenuCampoListResponse(items=items)


@router.patch("/empresas/{empresa_id}/menu-pedido/{campo}", response_model=MenuCampoItem)
def actualizar_menu_pedido(
    empresa_id: int,
    campo: str,
    payload: MenuCampoUpdateRequest,
    db: Session = Depends(get_db),
    auth=Depends(require_admin_role),
):
    assert_same_empresa(auth, empresa_id)
    if campo not in _CAMPOS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campo no reconocido")

    # Asegura que exista la fila de empresa_menu (con sus opciones al dia) antes de aplicar los cambios.
    _sync_empresa_menu_opciones(db, empresa_id=empresa_id, campo=campo)

    row = db.execute(
        text(
            """
            SELECT id_empresa_menu, titulo, tipo_control, opciones_json, requerido_aprobacion, activo, orden
            FROM petalops.empresa_menu
            WHERE empresa_id = :empresa_id AND codigo = :codigo AND seccion = 'pedido_detalle'
            """
        ),
        {"empresa_id": empresa_id, "codigo": campo},
    ).mappings().first()

    nuevo_titulo = row["titulo"] if payload.titulo is None else payload.titulo.strip()
    if not nuevo_titulo:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El titulo es obligatorio")
    nuevo_requerido = row["requerido_aprobacion"] if payload.requeridoAprobacion is None else payload.requeridoAprobacion
    nuevo_activo = row["activo"] if payload.activo is None else payload.activo

    db.execute(
        text(
            """
            UPDATE petalops.empresa_menu
            SET titulo = :titulo, requerido_aprobacion = :requerido, activo = :activo, updated_at = NOW()
            WHERE id_empresa_menu = :id_empresa_menu
            """
        ),
        {
            "titulo": nuevo_titulo,
            "requerido": bool(nuevo_requerido),
            "activo": bool(nuevo_activo),
            "id_empresa_menu": int(row["id_empresa_menu"]),
        },
    )
    db.commit()

    opciones = row["opciones_json"]
    if isinstance(opciones, str):
        try:
            opciones = json.loads(opciones)
        except ValueError:
            opciones = []
    total_opciones = len(opciones) if isinstance(opciones, list) else 0

    return MenuCampoItem(
        codigo=campo,
        titulo=nuevo_titulo,
        tipoControl=str(row["tipo_control"]),
        requeridoAprobacion=bool(nuevo_requerido),
        activo=bool(nuevo_activo),
        orden=int(row["orden"] or 0),
        totalOpciones=total_opciones,
    )
