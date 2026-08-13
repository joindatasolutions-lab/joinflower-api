from datetime import date, timedelta
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
    ContabilidadDomiciliarioInfo,
    ContabilidadDomiciliarioPedidoItem,
    ContabilidadDomiciliarioPedidosResponse,
    ContabilidadDomiciliarioPedidosResumen,
    ContabilidadFloristRow,
    ContabilidadResumenResponse,
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


def _florist_rows_sql() -> str:
    return """
        WITH reasignaciones AS (
            SELECT
                ph.produccion_id,
                COUNT(*)::int AS total_reasignaciones
            FROM petalops.produccion_historial ph
            WHERE ph.empresa_id = :empresa_id
              AND ph.florista_anterior_id IS NOT NULL
              AND ph.florista_nuevo_id IS NOT NULL
            GROUP BY ph.produccion_id
        )
        SELECT
            emp.id_empleado AS id,
            emp.nombre_empleado AS nombre,
            CASE
                WHEN lower(COALESCE(emp.tipo, '')) = 'externo' THEN 'Externo'
                ELSE 'Interno'
            END AS tipo,
            COUNT(DISTINCT pr.pedido_id)::int AS pedidos,
            SUM(COALESCE(NULLIF(pd.cantidad, 0), 1))::int AS arreglos,
            ROUND(SUM(COALESCE(pd.subtotal, 0)), 2)::float AS "totalVendido",
            ROUND(AVG(COALESCE(pd.subtotal, 0)), 2)::float AS promedio,
            COUNT(*) FILTER (
                WHERE lower(COALESCE(ep.codigo, ep.nombre, '')) IN ('completado', 'terminado', 'listo', 'paraentrega', 'para_entrega')
            )::int AS completados,
            COUNT(*) FILTER (
                WHERE lower(COALESCE(ep.codigo, ep.nombre, '')) IN ('en_proceso', 'produccion', 'asignado')
            )::int AS "enProceso",
            COUNT(*) FILTER (
                WHERE lower(COALESCE(ep.codigo, ep.nombre, '')) = 'pendiente'
            )::int AS pendientes,
            COUNT(*) FILTER (
                WHERE lower(COALESCE(ep.codigo, ep.nombre, '')) = 'cancelado'
            )::int AS cancelados,
            ROUND(AVG(NULLIF(pr.tiempo_real_min, 0)), 2)::float AS "tiempoPromedioMin",
            SUM(COALESCE(reasignaciones.total_reasignaciones, 0))::int AS reasignaciones
        FROM petalops.produccion pr
        JOIN petalops.empleado emp
          ON emp.id_empleado = pr.empleado_id
         AND emp.empresa_id = pr.empresa_id
         AND upper(emp.cargo) = 'FLORISTA'
        LEFT JOIN petalops.pedido_detalle pd
          ON pd.id_pedido_detalle = pr.pedido_detalle_id
         AND pd.empresa_id = pr.empresa_id
        LEFT JOIN petalops.estado_produccion ep
          ON ep.id_estado_produccion = pr.estado_produccion_id
        LEFT JOIN reasignaciones
          ON reasignaciones.produccion_id = pr.id_produccion
        WHERE pr.empresa_id = :empresa_id
          AND (:sucursal_id IS NULL OR pr.sucursal_id = :sucursal_id)
          AND pr.fecha_programada_produccion::date BETWEEN :fecha_desde AND :fecha_hasta
          AND pr.empleado_id IS NOT NULL
        GROUP BY emp.id_empleado, emp.nombre_empleado, emp.tipo
        ORDER BY arreglos DESC, "totalVendido" DESC
    """


def _row_to_florist_item(row) -> ContabilidadFloristRow:
    return ContabilidadFloristRow(
        id=int(row["id"]),
        nombre=str(row["nombre"] or ""),
        tipo=str(row["tipo"] or "Interno"),
        pedidos=int(row["pedidos"] or 0),
        arreglos=int(row["arreglos"] or 0),
        totalVendido=float(row["totalVendido"] or 0),
        promedio=float(row["promedio"] or 0),
        completados=int(row["completados"] or 0),
        enProceso=int(row["enProceso"] or 0),
        pendientes=int(row["pendientes"] or 0),
        cancelados=int(row["cancelados"] or 0),
        tiempoPromedioMin=(float(row["tiempoPromedioMin"]) if row["tiempoPromedioMin"] is not None else None),
        reasignaciones=int(row["reasignaciones"] or 0),
    )


def _estado_key(value: str | None) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _hhmm(value) -> str | None:
    if not value:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    raw = str(value).strip()
    return raw[:5] if raw else None


def _date_or_none(value) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _domiciliario_pedidos_params(
    *,
    empresa_id: int,
    sucursal_id: int,
    domiciliario_id: int,
    fecha_desde: date,
    fecha_hasta: date,
    estado_entrega: str | None,
) -> dict:
    return {
        "empresa_id": int(empresa_id),
        "sucursal_id": int(sucursal_id),
        "domiciliario_id": int(domiciliario_id),
        "fecha_desde": datetime.combine(fecha_desde, datetime.min.time()),
        "fecha_hasta": datetime.combine(fecha_hasta + timedelta(days=1), datetime.min.time()),
        "estado_entrega": (_estado_key(estado_entrega) if estado_entrega else None),
    }


def _domiciliario_info_sql() -> str:
    return """
        SELECT
            emp.id_empleado AS id,
            emp.nombre_empleado AS nombre,
            CASE
                WHEN lower(COALESCE(emp.tipo, '')) = 'externo' THEN 'Externo'
                ELSE 'Interno'
            END AS tipo
        FROM petalops.empleado emp
        WHERE emp.empresa_id = :empresa_id
          AND emp.id_empleado = :domiciliario_id
          AND upper(COALESCE(emp.cargo, '')) = 'DOMICILIARIO'
        LIMIT 1
    """


def _domiciliario_pedidos_sql() -> str:
    return """
        WITH latest_entregas AS (
            SELECT DISTINCT ON (e.pedido_id)
                e.*
            FROM petalops.entrega e
            JOIN petalops.pedido p_scope
              ON p_scope.id_pedido = e.pedido_id
             AND p_scope.empresa_id = e.empresa_id
            WHERE e.empresa_id = :empresa_id
              AND COALESCE(e.sucursalid, p_scope.sucursal_id) = :sucursal_id
            ORDER BY e.pedido_id, e.intentonumero DESC NULLS LAST, e.id_entrega DESC
        )
        SELECT
            emp.id_empleado AS domiciliario_id,
            emp.nombre_empleado AS domiciliario_nombre,
            CASE
                WHEN lower(COALESCE(emp.tipo, '')) = 'externo' THEN 'Externo'
                ELSE 'Interno'
            END AS domiciliario_tipo,
            p.id_pedido,
            COALESCE(NULLIF(p.codigo_pedido, ''), p.numero_pedido::text, p.id_pedido::text) AS numero_pedido,
            p.fecha_pedido,
            le.fechaentrega,
            COALESCE(le.fechaentrega, le.reprogramadapara, le.fechaentregaprogramada, le.createdat) AS fecha_referencia,
            c.nombre_completo AS cliente,
            COALESCE(NULLIF(c.telefono_completo, ''), NULLIF(c.telefono, ''), NULLIF(le.telefonodestino, '')) AS telefono,
            le.direccion,
            COALESCE(NULLIF(le.barrionombre, ''), b.nombre_barrio) AS barrio,
            CASE WHEN b.zona_id IS NULL THEN NULL ELSE CONCAT('Zona ', b.zona_id) END AS zona,
            ep.nombre_estado AS estado_pedido,
            COALESCE(ee.codigo, ee.nombre) AS estado_entrega_codigo,
            COALESCE(ee.nombre, ee.codigo) AS estado_entrega,
            COALESCE(p.costo_domicilio, b.costo_domicilio, 0) AS valor_domicilio,
            COALESCE(p.total_neto, p.total_bruto, 0) AS total_pedido,
            le.fechaasignacion,
            le.fechasalida,
            le.observaciones,
            le.observaciongeneral,
            le.motivonoentregado,
            le.reprogramadapara,
            CASE
                WHEN le.fechaentrega IS NOT NULL AND le.fechaasignacion IS NOT NULL
                THEN ROUND(EXTRACT(EPOCH FROM (le.fechaentrega - le.fechaasignacion)) / 60.0)::int
                ELSE NULL
            END AS tiempo_entrega_min
        FROM latest_entregas le
        JOIN petalops.pedido p
          ON p.id_pedido = le.pedido_id
         AND p.empresa_id = le.empresa_id
        JOIN petalops.empleado emp
          ON emp.id_empleado = le.domiciliarioid
         AND emp.empresa_id = le.empresa_id
        LEFT JOIN petalops.cliente c
          ON c.cliente_id = p.cliente_id
         AND c.empresa_id = p.empresa_id
        LEFT JOIN petalops.estado_pedido ep
          ON ep.id_estado_pedido = p.estado_pedido_id
        LEFT JOIN petalops.estado_entrega ee
          ON ee.id_estado_entrega = le.estadoentregaid
        LEFT JOIN petalops.barrio b
          ON b.id_barrio = le.barrioid
         AND b.empresa_id = le.empresa_id
        WHERE le.domiciliarioid = :domiciliario_id
          AND COALESCE(le.fechaentrega, le.reprogramadapara, le.fechaentregaprogramada, le.createdat) >= :fecha_desde
          AND COALESCE(le.fechaentrega, le.reprogramadapara, le.fechaentregaprogramada, le.createdat) < :fecha_hasta
          AND (
                :estado_entrega IS NULL
                OR lower(replace(COALESCE(ee.codigo, ee.nombre, ''), ' ', '_')) = :estado_entrega
          )
        ORDER BY
            COALESCE(le.fechaentrega, le.reprogramadapara, le.fechaentregaprogramada, le.createdat) DESC,
            p.id_pedido DESC
    """


def _row_to_domiciliario_info(row) -> ContabilidadDomiciliarioInfo:
    return ContabilidadDomiciliarioInfo(
        id=int(row["id"]),
        nombre=str(row["nombre"] or ""),
        tipo=str(row["tipo"] or "Interno"),
    )


def _row_to_domiciliario_pedido_item(row, pago_resumen: dict | None = None) -> ContabilidadDomiciliarioPedidoItem:
    pago_resumen = pago_resumen or {}
    observaciones = [
        str(value or "").strip()
        for value in (row.get("observaciones"), row.get("observaciongeneral"))
        if str(value or "").strip()
    ]
    return ContabilidadDomiciliarioPedidoItem(
        pedidoID=int(row["id_pedido"]),
        numeroPedido=str(row["numero_pedido"] or row["id_pedido"]),
        fechaPedido=_date_or_none(row.get("fecha_pedido")),
        fechaEntrega=_date_or_none(row.get("fechaentrega") or row.get("fecha_referencia")),
        cliente=str(row.get("cliente") or "Cliente"),
        telefono=(str(row.get("telefono")).strip() if row.get("telefono") else None),
        direccion=(str(row.get("direccion")).strip() if row.get("direccion") else None),
        barrio=(str(row.get("barrio")).strip() if row.get("barrio") else None),
        zona=(str(row.get("zona")).strip() if row.get("zona") else None),
        estadoPedido=(str(row.get("estado_pedido")).strip().upper() if row.get("estado_pedido") else None),
        estadoEntrega=(
            str(row.get("estado_entrega") or row.get("estado_entrega_codigo")).strip().upper()
            if (row.get("estado_entrega") or row.get("estado_entrega_codigo"))
            else None
        ),
        valorDomicilio=_money(row.get("valor_domicilio")),
        totalPedido=_money(row.get("total_pedido")),
        medioPago=(str(pago_resumen.get("metodoPago")).strip() if pago_resumen.get("metodoPago") else None),
        cuentaPago=(
            str(pago_resumen.get("cuentaBancaria") or pago_resumen.get("metodoPago")).strip()
            if (pago_resumen.get("cuentaBancaria") or pago_resumen.get("metodoPago"))
            else None
        ),
        horaAsignacion=_hhmm(row.get("fechaasignacion")),
        horaEnRuta=_hhmm(row.get("fechasalida")),
        horaEntrega=_hhmm(row.get("fechaentrega")),
        tiempoEntregaMin=(int(row["tiempo_entrega_min"]) if row.get("tiempo_entrega_min") is not None else None),
        observaciones=" | ".join(dict.fromkeys(observaciones)) if observaciones else None,
        novedad=(str(row.get("motivonoentregado")).strip() if row.get("motivonoentregado") else None),
    )


def _domiciliario_resumen(
    items: list[ContabilidadDomiciliarioPedidoItem],
    rows: list[dict],
) -> ContabilidadDomiciliarioPedidosResumen:
    entregados = 0
    no_entregados = 0
    reprogramados = 0
    total_domicilios = Decimal("0")

    for item, row in zip(items, rows):
        estado = _estado_key(row.get("estado_entrega_codigo") or item.estadoEntrega)
        if estado == "entregado":
            entregados += 1
        elif estado == "no_entregado":
            no_entregados += 1
        elif row.get("reprogramadapara") is not None:
            reprogramados += 1
        total_domicilios += item.valorDomicilio

    pedidos = len(items)
    promedio = (total_domicilios / Decimal(pedidos)).quantize(Decimal("0.01")) if pedidos else Decimal("0")
    return ContabilidadDomiciliarioPedidosResumen(
        pedidos=pedidos,
        entregados=entregados,
        noEntregados=no_entregados,
        reprogramados=reprogramados,
        totalDomicilios=total_domicilios.quantize(Decimal("0.01")),
        promedioDomicilio=promedio,
    )


@router.get("/floristas/resumen", response_model=ContabilidadResumenResponse)
def obtener_resumen_floristas_contabilidad(
    empresa_id: int = Query(..., alias="empresaID", gt=0),
    sucursal_id: int | None = Query(None, alias="sucursalID", gt=0),
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
        text(_florist_rows_sql()),
        {
            "empresa_id": int(empresa_id),
            "sucursal_id": (int(sucursal_id) if sucursal_id is not None else None),
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
        },
    ).mappings().all()

    return ContabilidadResumenResponse(floristRows=[_row_to_florist_item(row) for row in rows])


@router.get("/domiciliarios/{domiciliario_id}/pedidos", response_model=ContabilidadDomiciliarioPedidosResponse)
def obtener_pedidos_domiciliario_contabilidad(
    domiciliario_id: int,
    empresa_id: int = Query(..., alias="empresaID", gt=0),
    sucursal_id: int = Query(..., alias="sucursalID", gt=0),
    fecha_desde_raw: str = Query(..., alias="fechaDesde"),
    fecha_hasta_raw: str = Query(..., alias="fechaHasta"),
    estado_entrega: str | None = Query(None, alias="estadoEntrega"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    fecha_desde = _parse_query_date(fecha_desde_raw)
    fecha_hasta = _parse_query_date(fecha_hasta_raw)
    if fecha_desde > fecha_hasta:
        raise HTTPException(status_code=400, detail="fechaDesde no puede ser mayor que fechaHasta")
    assert_same_empresa(auth, int(empresa_id))

    info_row = db.execute(
        text(_domiciliario_info_sql()),
        {"empresa_id": int(empresa_id), "domiciliario_id": int(domiciliario_id)},
    ).mappings().first()
    if not info_row:
        raise HTTPException(status_code=404, detail="Domiciliario no encontrado")

    rows = db.execute(
        text(_domiciliario_pedidos_sql()),
        _domiciliario_pedidos_params(
            empresa_id=int(empresa_id),
            sucursal_id=int(sucursal_id),
            domiciliario_id=int(domiciliario_id),
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            estado_entrega=estado_entrega,
        ),
    ).mappings().all()

    pedido_ids = [int(row["id_pedido"]) for row in rows if row.get("id_pedido") is not None]
    pagos_por_pedido = {}
    if pedido_ids:
        from app.routers.pedido import _load_pago_resumen_batch

        pagos_por_pedido = _load_pago_resumen_batch(db, empresa_id=int(empresa_id), pedido_ids=pedido_ids)

    items = [
        _row_to_domiciliario_pedido_item(row, pagos_por_pedido.get(int(row["id_pedido"])))
        for row in rows
    ]
    return ContabilidadDomiciliarioPedidosResponse(
        domiciliario=_row_to_domiciliario_info(info_row),
        resumen=_domiciliario_resumen(items, [dict(row) for row in rows]),
        items=items,
    )


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
