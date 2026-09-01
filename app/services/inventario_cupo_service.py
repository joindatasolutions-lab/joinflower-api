import json
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session


def _normalizar_productos(productos: list[dict]) -> dict[int, Decimal]:
    result: dict[int, Decimal] = {}
    for item in productos:
        producto_id = item.get("productoID") or item.get("productoId")
        if producto_id is None:
            continue
        cantidad = Decimal(str(item.get("cantidad") or 0))
        if cantidad <= 0:
            continue
        key = int(producto_id)
        result[key] = result.get(key, Decimal("0")) + cantidad
    return result


def validar_cupos_recetas_para_productos(
    db: Session,
    *,
    empresa_id: int,
    productos: list[dict],
    pedido_id: int | None = None,
) -> None:
    cantidades = _normalizar_productos(productos)
    if not cantidades:
        return

    rows = db.execute(
        text(
            """
            WITH solicitado AS (
              SELECT CAST(key AS BIGINT) AS producto_id, CAST(value AS NUMERIC) AS cantidad
              FROM jsonb_each_text(CAST(:cantidades AS JSONB))
            )
            SELECT
              r.id_receta,
              r.nombre,
              r.producto_id,
              r.capacidad_manual,
              s.cantidad AS solicitado,
              COALESCE(SUM(pd.cantidad) FILTER (
                WHERE UPPER(ep.nombre_estado) IN ('APROBADO', 'PAGADO')
                  AND DATE(pe.fecha_pedido) = CURRENT_DATE
                  AND (:pedido_id IS NULL OR pe.id_pedido <> :pedido_id)
              ), 0) AS vendidos_hoy,
              COALESCE(SUM(pd.cantidad) FILTER (
                WHERE UPPER(ep.nombre_estado) IN ('APROBADO', 'PAGADO')
                  AND (ee.codigo IS NULL OR ee.codigo NOT IN ('entregado', 'cancelado'))
                  AND (:pedido_id IS NULL OR pe.id_pedido <> :pedido_id)
              ), 0) AS reservados
            FROM solicitado s
            JOIN petalops.receta r
              ON r.producto_id = s.producto_id
             AND r.empresa_id = :empresa_id
             AND r.activo = true
             AND r.capacidad_manual IS NOT NULL
             AND r.capacidad_manual > 0
            LEFT JOIN petalops.pedido_detalle pd
              ON pd.producto_id = r.producto_id
             AND pd.empresa_id = r.empresa_id
            LEFT JOIN petalops.pedido pe ON pe.id_pedido = pd.pedido_id
            LEFT JOIN petalops.estado_pedido ep ON ep.id_estado_pedido = pe.estado_pedido_id
            LEFT JOIN petalops.entrega en ON en.pedido_id = pe.id_pedido
            LEFT JOIN petalops.estado_entrega ee ON ee.id_estado_entrega = en.estadoentregaid
            GROUP BY r.id_receta, r.nombre, r.producto_id, r.capacidad_manual, s.cantidad
            """
        ),
        {
            "empresa_id": int(empresa_id),
            "pedido_id": (int(pedido_id) if pedido_id is not None else None),
            "cantidades": json.dumps({str(pid): str(cantidad) for pid, cantidad in cantidades.items()}),
        },
    ).mappings().all()

    bloqueos = []
    for row in rows:
        capacidad = Decimal(row["capacidad_manual"] or 0)
        solicitado = Decimal(row["solicitado"] or 0)
        vendidos_hoy = Decimal(row["vendidos_hoy"] or 0)
        reservados = Decimal(row["reservados"] or 0)
        ocupados = max(vendidos_hoy, reservados)
        disponible = capacidad - ocupados
        if solicitado > disponible:
            bloqueos.append(
                {
                    "recetaID": int(row["id_receta"]),
                    "productoID": int(row["producto_id"]),
                    "nombre": str(row["nombre"] or ""),
                    "capacidad": float(capacidad),
                    "ocupados": float(ocupados),
                    "disponible": float(max(disponible, Decimal("0"))),
                    "solicitado": float(solicitado),
                }
            )

    if bloqueos:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVENTARIO_CUPO_INSUFICIENTE",
                "message": "No hay cupo disponible para uno o mas arreglos de inventario",
                "items": bloqueos,
            },
        )
