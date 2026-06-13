from datetime import date
from decimal import Decimal
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.security import assert_same_empresa, get_current_auth_context, require_module_access
from app.database import get_db
from app.schemas.contabilidad import (
    CajaCierreRequest,
    CajaCierreResponse,
    CajaDiaItem,
    CajaEfectivoDiaResponse,
    CajaListResponse,
)
from app.services import caja_service

router = APIRouter(
    prefix="/contabilidad",
    tags=["Contabilidad"],
    dependencies=[Depends(require_module_access("contabilidad", "puedeVer"))],
)
contabilidad_logger = get_logger("contabilidad")


def _money(value) -> Decimal:
    return caja_service.money(value)


def _parse_query_date(value) -> date:
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail="Fecha invalida. Usa YYYY-MM-DD o DD/MM/YYYY")


def _calculate_nueva_base(
    *,
    base_inicial: Decimal,
    efectivo_ventas: Decimal,
    total_gastos: Decimal,
    monto_guardado: Decimal,
) -> Decimal:
    return caja_service.calculate_nueva_base(
        base_inicial=base_inicial,
        efectivo_ventas=efectivo_ventas,
        total_gastos=total_gastos,
        monto_guardado=monto_guardado,
    )


def _row_to_caja_item(row) -> CajaDiaItem:
    return CajaDiaItem(
        fecha_operacion=row["fecha"],
        base_inicial=_money(row["base"]),
        efectivo_ventas=_money(row["efectivo"]),
        total_gastos=_money(row["gasto"]),
        total_efectivo=_money(row["total_efectivo"]),
        monto_guardado=_money(row["guardado"]),
        nueva_base=_money(row["nueva_base"]),
        observacion=row["observacion"] or "",
    )


def _relation_exists(db: Session, relation_name: str) -> bool:
    return caja_service.relation_exists(db, relation_name)


def _caja_totales_sql(db: Session, *, single_day: bool) -> str:
    return caja_service.caja_totales_sql(single_day=single_day)


def _load_efectivo_ventas(db: Session, *, empresa_id: int, sucursal_id: int, fecha_operacion: date) -> Decimal:
    return caja_service.load_efectivo_ventas(
        db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        fecha_operacion=fecha_operacion,
    )


def _load_base_anterior(db: Session, *, empresa_id: int, sucursal_id: int, fecha_operacion: date) -> Decimal:
    return caja_service.load_base_anterior(
        db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        fecha_operacion=fecha_operacion,
    )


def _build_caja_draft(db: Session, *, empresa_id: int, sucursal_id: int, fecha_operacion: date) -> CajaDiaItem:
    base_inicial = _load_base_anterior(
        db,
        empresa_id=int(empresa_id),
        sucursal_id=int(sucursal_id),
        fecha_operacion=fecha_operacion,
    )
    efectivo_ventas = _load_efectivo_ventas(
        db,
        empresa_id=int(empresa_id),
        sucursal_id=int(sucursal_id),
        fecha_operacion=fecha_operacion,
    )
    total_gastos = Decimal("0")
    total_efectivo = base_inicial + efectivo_ventas - total_gastos
    return CajaDiaItem(
        fecha_operacion=fecha_operacion,
        base_inicial=base_inicial,
        efectivo_ventas=efectivo_ventas,
        total_gastos=total_gastos,
        total_efectivo=total_efectivo,
        monto_guardado=Decimal("0"),
        nueva_base=_calculate_nueva_base(
            base_inicial=base_inicial,
            efectivo_ventas=efectivo_ventas,
            total_gastos=total_gastos,
            monto_guardado=Decimal("0"),
        ),
        observacion="",
    )


def _load_caja_dia(db: Session, *, empresa_id: int, sucursal_id: int, fecha_operacion: date) -> CajaDiaItem | None:
    row = db.execute(
        text(_caja_totales_sql(db, single_day=True)),
        {
            "empresa_id": int(empresa_id),
            "sucursal_id": int(sucursal_id),
            "fecha_operacion": fecha_operacion,
        },
    ).mappings().first()
    if not row:
        return None

    item = _row_to_caja_item(row)
    efectivo_real = _load_efectivo_ventas(
        db,
        empresa_id=int(empresa_id),
        sucursal_id=int(sucursal_id),
        fecha_operacion=fecha_operacion,
    )
    item.efectivo_ventas = efectivo_real
    item.total_efectivo = item.base_inicial + efectivo_real - item.total_gastos
    item.nueva_base = item.total_efectivo - item.monto_guardado
    return item


def _upsert_caja(
    db: Session,
    *,
    empresa_id: int,
    sucursal_id: int,
    fecha: date,
    base: Decimal,
    efectivo: Decimal,
    gasto: Decimal,
    total_efectivo: Decimal,
    guardado: Decimal,
    nueva_base: Decimal,
    observacion: str,
    usuario_id: int | None,
) -> None:
    caja_service.upsert_caja(
        db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        fecha=fecha,
        base=base,
        efectivo=efectivo,
        gasto=gasto,
        total_efectivo=total_efectivo,
        guardado=guardado,
        nueva_base=nueva_base,
        observacion=observacion,
        usuario_id=usuario_id,
    )


def _resolve_usuario_id(db: Session, *, empresa_id: int, requested_user_id: int | None, auth) -> int | None:
    candidates = []
    if requested_user_id is not None:
        candidates.append(int(requested_user_id))
    auth_user_id = getattr(auth, "userID", None)
    if auth_user_id is not None and int(auth_user_id) not in candidates:
        candidates.append(int(auth_user_id))

    for user_id in candidates:
        row = db.execute(
            text(
                """
                SELECT id_usuario
                FROM petalops.usuario
                WHERE id_usuario = :user_id
                  AND (:empresa_id IS NULL OR empresa_id = :empresa_id)
                LIMIT 1
                """
            ),
            {
                "user_id": int(user_id),
                "empresa_id": int(empresa_id),
            },
        ).first()
        if row:
            return int(row[0])
    return None


@router.get("/caja", response_model=CajaListResponse)
def listar_cierres_caja(
    empresa_id: int = Query(..., alias="empresaID", gt=0),
    sucursal_id: int = Query(..., alias="sucursalID", gt=0),
    fecha_desde_raw: str = Query(..., alias="fechaDesde"),
    fecha_hasta_raw: str = Query(..., alias="fechaHasta"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    fecha_desde = _parse_query_date(fecha_desde_raw)
    fecha_hasta = _parse_query_date(fecha_hasta_raw)
    if fecha_desde > fecha_hasta:
        raise HTTPException(status_code=400, detail="fechaDesde no puede ser mayor que fechaHasta")
    assert_same_empresa(auth, int(empresa_id))

    rows = db.execute(
        text(_caja_totales_sql(db, single_day=False)),
        {
            "empresa_id": int(empresa_id),
            "sucursal_id": int(sucursal_id),
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
        },
    ).mappings().all()

    return CajaListResponse(items=[_row_to_caja_item(row) for row in rows])


@router.get("/caja/dia", response_model=CajaDiaItem)
def obtener_caja_dia(
    empresa_id: int = Query(..., alias="empresaID", gt=0),
    sucursal_id: int = Query(..., alias="sucursalID", gt=0),
    fecha_raw: str = Query(..., alias="fecha"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    fecha = _parse_query_date(fecha_raw)
    assert_same_empresa(auth, int(empresa_id))
    item = _load_caja_dia(
        db,
        empresa_id=int(empresa_id),
        sucursal_id=int(sucursal_id),
        fecha_operacion=fecha,
    )
    if item is None:
        return _build_caja_draft(
            db,
            empresa_id=int(empresa_id),
            sucursal_id=int(sucursal_id),
            fecha_operacion=fecha,
        )
    return item


@router.get("/caja/efectivo", response_model=CajaEfectivoDiaResponse)
def obtener_efectivo_caja_dia(
    empresa_id: int = Query(..., alias="empresaID", gt=0),
    sucursal_id: int = Query(..., alias="sucursalID", gt=0),
    fecha_raw: str = Query(..., alias="fecha"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    fecha = _parse_query_date(fecha_raw)
    assert_same_empresa(auth, int(empresa_id))
    item = _load_caja_dia(
        db,
        empresa_id=int(empresa_id),
        sucursal_id=int(sucursal_id),
        fecha_operacion=fecha,
    )
    if item is None:
        item = _build_caja_draft(
            db,
            empresa_id=int(empresa_id),
            sucursal_id=int(sucursal_id),
            fecha_operacion=fecha,
        )

    return CajaEfectivoDiaResponse(
        empresaID=int(empresa_id),
        sucursalID=int(sucursal_id),
        fecha=fecha,
        efectivo=item.efectivo_ventas,
        totalEfectivo=item.total_efectivo,
    )


@router.put(
    "/caja/cierre",
    response_model=CajaCierreResponse,
    dependencies=[Depends(require_module_access("contabilidad", "puedeEditar"))],
)
def guardar_cierre_caja(
    payload: CajaCierreRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, int(payload.empresaID))
    usuario_id = _resolve_usuario_id(
        db,
        empresa_id=int(payload.empresaID),
        requested_user_id=payload.usuarioID,
        auth=auth,
    )
    empresa_id = int(payload.empresaID)
    sucursal_id = int(payload.sucursalID)
    fecha_operacion = payload.fechaOperacion
    base_inicial = payload.baseInicial
    monto_guardado = payload.montoGuardado
    observacion = (payload.observacion or "").strip()
    efectivo = _load_efectivo_ventas(
        db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        fecha_operacion=fecha_operacion,
    )
    gasto = payload.gasto
    total_efectivo = base_inicial + efectivo - gasto
    nueva_base = total_efectivo - monto_guardado

    try:
        _upsert_caja(
            db,
            empresa_id=empresa_id,
            sucursal_id=sucursal_id,
            fecha=fecha_operacion,
            base=base_inicial,
            efectivo=efectivo,
            gasto=gasto,
            total_efectivo=total_efectivo,
            guardado=monto_guardado,
            nueva_base=nueva_base,
            observacion=observacion,
            usuario_id=usuario_id,
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        contabilidad_logger.error("Error SQL guardando cierre de caja", exc_info=True)
        raise HTTPException(status_code=400, detail="No fue posible guardar el cierre de caja") from exc

    item = _load_caja_dia(
        db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        fecha_operacion=fecha_operacion,
    )
    if item is None:
        raise HTTPException(status_code=500, detail="Cierre guardado pero no se pudo recargar el consolidado")
    return CajaCierreResponse(status="ok", item=item)
