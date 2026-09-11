import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import assert_same_empresa, get_current_auth_context, require_admin_role
from app.database import get_db
from app.models.empresa_configuracion_asignacion import EmpresaConfiguracionAsignacion
from app.schemas.configuracion import (
    CatalogoCreateRequest,
    CatalogoItem,
    CatalogoListResponse,
    CatalogoUpdateRequest,
    ConfiguracionAsignacionResponse,
    ConfiguracionAsignacionUpdateRequest,
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


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _catalogo_select_sql(meta: dict, campo: str) -> str:
    extra = ""
    if campo == "pedido_metodos_pago":
        extra = ", cuenta, numero_cuenta, activas_cuentas_catalogo"
    return f"""
            SELECT {meta["id_columna"]} AS id, codigo, nombre, orden, activo{extra}
            FROM petalops.{meta["tabla"]}
            WHERE empresa_id = :empresa_id
            """


def _catalogo_item_from_row(row, *, campo: str) -> CatalogoItem:
    base = {
        "id": int(row["id"]),
        "codigo": str(row["codigo"]),
        "nombre": str(row["nombre"]),
        "orden": int(row["orden"] or 0),
        "activo": bool(row["activo"]),
    }
    if campo == "pedido_metodos_pago":
        base.update(
            {
                "cuenta": (str(row["cuenta"]).strip() if row.get("cuenta") else None),
                "numeroCuenta": (str(row["numero_cuenta"]).strip() if row.get("numero_cuenta") else None),
                "activasCuentasCatalogo": bool(row["activas_cuentas_catalogo"]),
            }
        )
    return CatalogoItem(**base)


def _listar_catalogo(db: Session, *, empresa_id: int, campo: str) -> CatalogoListResponse:
    meta = _CAMPOS[campo]
    rows = db.execute(
        text(
            f"""
            {_catalogo_select_sql(meta, campo)}
            ORDER BY orden ASC, nombre ASC
            """
        ),
        {"empresa_id": empresa_id},
    ).mappings().all()
    return CatalogoListResponse(
        items=[_catalogo_item_from_row(row, campo=campo) for row in rows]
    )


def _crear_catalogo_item(
    db: Session,
    *,
    empresa_id: int,
    campo: str,
    nombre: str,
    cuenta: str | None = None,
    numero_cuenta: str | None = None,
    activas_cuentas_catalogo: bool | None = None,
) -> CatalogoItem:
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
    params = {"empresa_id": empresa_id, "codigo": codigo, "nombre": nombre, "orden": orden}
    extra_columns = ""
    extra_values = ""
    if campo == "pedido_metodos_pago":
        extra_columns = ", cuenta, numero_cuenta, activas_cuentas_catalogo"
        extra_values = ", :cuenta, :numero_cuenta, :activas_cuentas_catalogo"
        params.update(
            {
                "cuenta": _clean_optional_text(cuenta),
                "numero_cuenta": _clean_optional_text(numero_cuenta),
                "activas_cuentas_catalogo": bool(activas_cuentas_catalogo),
            }
        )
    inserted = db.execute(
        text(
            f"""
            INSERT INTO petalops.{meta["tabla"]} (
                empresa_id, codigo, nombre, orden, activo{extra_columns}, created_at, updated_at
            ) VALUES (
                :empresa_id, :codigo, :nombre, :orden, TRUE{extra_values}, NOW(), NOW()
            )
            RETURNING {meta["id_columna"]} AS id, codigo, nombre, orden, activo
                      {', cuenta, numero_cuenta, activas_cuentas_catalogo' if campo == 'pedido_metodos_pago' else ''}
            """
        ),
        params,
    ).mappings().first()

    _sync_empresa_menu_opciones(db, empresa_id=empresa_id, campo=campo)
    db.commit()

    return _catalogo_item_from_row(inserted, campo=campo)


def _actualizar_catalogo_item(
    db: Session, *, empresa_id: int, campo: str, item_id: int, payload: CatalogoUpdateRequest
) -> CatalogoItem:
    meta = _CAMPOS[campo]
    row = db.execute(
        text(
            f"""
            {_catalogo_select_sql(meta, campo)}
              AND {meta["id_columna"]} = :item_id
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
    cuenta = row.get("cuenta") if campo == "pedido_metodos_pago" else None
    numero_cuenta = row.get("numero_cuenta") if campo == "pedido_metodos_pago" else None
    activas_cuentas_catalogo = (
        row.get("activas_cuentas_catalogo") if campo == "pedido_metodos_pago" else None
    )
    if campo == "pedido_metodos_pago":
        if payload.cuenta is not None:
            cuenta = _clean_optional_text(payload.cuenta)
        if payload.numeroCuenta is not None:
            numero_cuenta = _clean_optional_text(payload.numeroCuenta)
        if payload.activasCuentasCatalogo is not None:
            activas_cuentas_catalogo = bool(payload.activasCuentasCatalogo)

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

    extra_set = ""
    params = {
        "nombre": nuevo_nombre,
        "orden": nuevo_orden,
        "activo": bool(nuevo_activo),
        "empresa_id": empresa_id,
        "item_id": item_id,
    }
    if campo == "pedido_metodos_pago":
        extra_set = """
                , cuenta = :cuenta,
                  numero_cuenta = :numero_cuenta,
                  activas_cuentas_catalogo = :activas_cuentas_catalogo
        """
        params.update(
            {
                "cuenta": cuenta,
                "numero_cuenta": numero_cuenta,
                "activas_cuentas_catalogo": bool(activas_cuentas_catalogo),
            }
        )

    db.execute(
        text(
            f"""
            UPDATE petalops.{meta["tabla"]}
            SET nombre = :nombre, orden = :orden, activo = :activo{extra_set}, updated_at = NOW()
            WHERE empresa_id = :empresa_id AND {meta["id_columna"]} = :item_id
            """
        ),
        params,
    )

    _sync_empresa_menu_opciones(db, empresa_id=empresa_id, campo=campo)
    db.commit()

    response = {
        "id": item_id,
        "codigo": str(row["codigo"]),
        "nombre": nuevo_nombre,
        "orden": int(nuevo_orden),
        "activo": bool(nuevo_activo),
    }
    if campo == "pedido_metodos_pago":
        response.update(
            {
                "cuenta": cuenta,
                "numeroCuenta": numero_cuenta,
                "activasCuentasCatalogo": bool(activas_cuentas_catalogo),
            }
        )
    return CatalogoItem(**response)


@router.get("/empresas/{empresa_id}/metodos-pago", response_model=CatalogoListResponse)
def listar_metodos_pago(empresa_id: int, db: Session = Depends(get_db), auth=Depends(require_admin_role)):
    assert_same_empresa(auth, empresa_id)
    return _listar_catalogo(db, empresa_id=empresa_id, campo="pedido_metodos_pago")


@router.post("/empresas/{empresa_id}/metodos-pago", response_model=CatalogoItem, status_code=status.HTTP_201_CREATED)
def crear_metodo_pago(
    empresa_id: int, payload: CatalogoCreateRequest, db: Session = Depends(get_db), auth=Depends(require_admin_role)
):
    assert_same_empresa(auth, empresa_id)
    return _crear_catalogo_item(
        db,
        empresa_id=empresa_id,
        campo="pedido_metodos_pago",
        nombre=payload.nombre,
        cuenta=payload.cuenta,
        numero_cuenta=payload.numeroCuenta,
        activas_cuentas_catalogo=payload.activasCuentasCatalogo,
    )


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


@router.get("/empresas/{empresa_id}/asignacion", response_model=ConfiguracionAsignacionResponse)
def obtener_configuracion_asignacion(
    empresa_id: int, db: Session = Depends(get_db), auth=Depends(get_current_auth_context)
):
    # Lectura abierta a cualquier usuario autenticado (florista/domiciliario incluidos):
    # ProductionPage/DeliveryPage necesitan leer este flag para decidir si muestran el
    # boton de autoasignacion. Solo la escritura (PUT, abajo) sigue restringida a admins.
    assert_same_empresa(auth, empresa_id)
    config = (
        db.query(EmpresaConfiguracionAsignacion)
        .filter(EmpresaConfiguracionAsignacion.empresaID == empresa_id)
        .first()
    )
    # Sin fila de configuracion = autoasignacion activa por defecto (opt-out, no opt-in):
    # asi ninguna floristeria existente pierde la autoasignacion que ya tenia antes de
    # que este flag existiera. El admin puede desactivarla explicitamente si no la quiere.
    return ConfiguracionAsignacionResponse(
        empresaID=empresa_id,
        asignacionProduccionActiva=bool(config.asignacionProduccionActiva) if config else True,
        asignacionDomicilioActiva=bool(config.asignacionDomicilioActiva) if config else True,
        autoAsignacionProduccionActiva=bool(config.autoAsignacionProduccionActiva) if config else True,
    )


@router.put("/empresas/{empresa_id}/asignacion", response_model=ConfiguracionAsignacionResponse)
def actualizar_configuracion_asignacion(
    empresa_id: int,
    payload: ConfiguracionAsignacionUpdateRequest,
    db: Session = Depends(get_db),
    auth=Depends(require_admin_role),
):
    assert_same_empresa(auth, empresa_id)
    config = (
        db.query(EmpresaConfiguracionAsignacion)
        .filter(EmpresaConfiguracionAsignacion.empresaID == empresa_id)
        .first()
    )
    if config is None:
        # Misma logica de default que el GET: si esta floristeria nunca configuro nada,
        # arranca con ambas activas (no se le quita algo que ya tenia).
        config = EmpresaConfiguracionAsignacion(
            empresaID=empresa_id,
            asignacionProduccionActiva=True,
            asignacionDomicilioActiva=True,
            autoAsignacionProduccionActiva=True,
            createdAt=datetime.now(timezone.utc),
            updatedAt=datetime.now(timezone.utc),
        )
        db.add(config)

    if payload.asignacionProduccionActiva is not None:
        config.asignacionProduccionActiva = payload.asignacionProduccionActiva
    if payload.asignacionDomicilioActiva is not None:
        config.asignacionDomicilioActiva = payload.asignacionDomicilioActiva
    if payload.autoAsignacionProduccionActiva is not None:
        config.autoAsignacionProduccionActiva = payload.autoAsignacionProduccionActiva
    config.updatedAt = datetime.now(timezone.utc)

    db.commit()
    db.refresh(config)

    return ConfiguracionAsignacionResponse(
        empresaID=empresa_id,
        asignacionProduccionActiva=bool(config.asignacionProduccionActiva),
        asignacionDomicilioActiva=bool(config.asignacionDomicilioActiva),
        autoAsignacionProduccionActiva=bool(config.autoAsignacionProduccionActiva),
    )
