from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session


def money(value) -> Decimal:
    return Decimal(str(value or 0))


def calculate_nueva_base(
    *,
    base_inicial: Decimal,
    efectivo_ventas: Decimal,
    total_gastos: Decimal,
    monto_guardado: Decimal,
) -> Decimal:
    return base_inicial + efectivo_ventas - total_gastos - monto_guardado


def calculate_cierre(
    *,
    base_inicial: Decimal,
    efectivo_ventas: Decimal,
    total_gastos: Decimal,
    total_contado: Decimal | None,
    monto_guardado: Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    total_efectivo = base_inicial + efectivo_ventas - total_gastos
    if total_efectivo < 0:
        raise ValueError("gastos_exceden_disponible")

    conteo = total_efectivo if total_contado is None else total_contado
    if monto_guardado > conteo:
        raise ValueError("guardado_excede_contado")

    diferencia = conteo - total_efectivo
    sobrante = max(diferencia, Decimal("0"))
    faltante = max(-diferencia, Decimal("0"))
    nueva_base = conteo - monto_guardado
    return total_efectivo, conteo, sobrante, faltante, nueva_base


def relation_exists(db: Session, relation_name: str) -> bool:
    row = db.execute(
        text("SELECT to_regclass(:relation_name) IS NOT NULL"),
        {"relation_name": f"petalops.{relation_name}"},
    ).first()
    return bool(row and row[0])


def column_exists(db: Session, table_name: str, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'petalops'
              AND table_name = :table_name
              AND column_name = :column_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    return bool(row)


def caja_totales_sql(*, single_day: bool) -> str:
    date_filter = (
        "AND fecha = :fecha_operacion" if single_day else "AND fecha BETWEEN :fecha_desde AND :fecha_hasta"
    )
    return f"""
        SELECT fecha,
               base,
               efectivo,
               gasto,
               total_efectivo,
               guardado,
               nueva_base,
               total_contado,
               sobrante,
               faltante,
               observacion
        FROM petalops.caja
        WHERE empresa_id = :empresa_id
          AND sucursal_id = :sucursal_id
          {date_filter}
        ORDER BY fecha DESC
    """


def load_efectivo_ventas(db: Session, *, empresa_id: int, sucursal_id: int, fecha_operacion: date) -> Decimal:
    total = Decimal("0")

    has_phase2_amounts = (
        relation_exists(db, "pago_metodo")
        and relation_exists(db, "metodo_pago_catalogo")
        and column_exists(db, "pago_metodo", "monto")
    )

    if has_phase2_amounts:
        row = db.execute(
            text(
                """
                SELECT COALESCE(SUM(pm.monto), 0)
                FROM petalops.pago_metodo pm
                JOIN petalops.metodo_pago_catalogo mpc
                  ON mpc.id_metodo_pago = pm.metodo_pago_id
                 AND mpc.empresa_id = pm.empresa_id
                JOIN petalops.pedido p
                  ON p.id_pedido = pm.pedido_id
                 AND p.empresa_id = pm.empresa_id
                LEFT JOIN petalops.estado_pedido ep
                  ON ep.id_estado_pedido = p.estado_pedido_id
                WHERE pm.empresa_id = :empresa_id
                  AND p.sucursal_id = :sucursal_id
                  AND CAST(p.fecha_pedido AS DATE) = :fecha_operacion
                  AND (
                                        COALESCE(mpc.codigo, '') ILIKE '%efectivo%'
                                        OR COALESCE(mpc.nombre, '') ILIKE '%efectivo%'
                  )
                  AND upper(COALESCE(ep.nombre_estado, '')) NOT IN ('CREADO', 'CANCELADO', 'RECHAZADO', 'ANULADO')
                """
            ),
            {
                "empresa_id": int(empresa_id),
                "sucursal_id": int(sucursal_id),
                "fecha_operacion": fecha_operacion,
            },
        ).first()
        total += money(row[0] if row else 0)

    if relation_exists(db, "pago"):
        legacy_filter = ""
        if has_phase2_amounts:
            legacy_filter = """
                  AND NOT EXISTS (
                    SELECT 1
                    FROM petalops.pago_metodo pm
                    WHERE pm.empresa_id = pa.empresa_id
                      AND pm.pedido_id = pa.pedido_id
                  )
            """
        row = db.execute(
            text(
                f"""
                SELECT COALESCE(SUM(pa.monto), 0)
                FROM petalops.pago pa
                JOIN petalops.pedido p
                  ON p.id_pedido = pa.pedido_id
                 AND p.empresa_id = pa.empresa_id
                LEFT JOIN petalops.estado_pedido ep
                  ON ep.id_estado_pedido = p.estado_pedido_id
                WHERE pa.empresa_id = :empresa_id
                  AND p.sucursal_id = :sucursal_id
                  AND CAST(p.fecha_pedido AS DATE) = :fecha_operacion
                  AND COALESCE(pa.metodo_pago, '') ILIKE '%efectivo%'
                  AND upper(COALESCE(ep.nombre_estado, '')) NOT IN ('CREADO', 'CANCELADO', 'RECHAZADO', 'ANULADO')
                  {legacy_filter}
                """
            ),
            {
                "empresa_id": int(empresa_id),
                "sucursal_id": int(sucursal_id),
                "fecha_operacion": fecha_operacion,
            },
        ).first()
        total += money(row[0] if row else 0)

    return total


def load_base_anterior(db: Session, *, empresa_id: int, sucursal_id: int, fecha_operacion: date) -> Decimal:
    row = db.execute(
        text(
            """
            SELECT GREATEST(nueva_base, 0)
            FROM petalops.caja
            WHERE empresa_id = :empresa_id
              AND sucursal_id = :sucursal_id
              AND fecha < :fecha_operacion
            ORDER BY fecha DESC
            LIMIT 1
            """
        ),
        {
            "empresa_id": int(empresa_id),
            "sucursal_id": int(sucursal_id),
            "fecha_operacion": fecha_operacion,
        },
    ).first()
    return money(row[0] if row else 0)


def load_gastos_total(db: Session, *, empresa_id: int, sucursal_id: int, fecha_operacion: date) -> Decimal:
    if not relation_exists(db, "caja_gasto"):
        return Decimal("0")
    row = db.execute(
        text(
            """
            SELECT COALESCE(SUM(monto), 0)
            FROM petalops.caja_gasto
            WHERE empresa_id = :empresa_id
              AND sucursal_id = :sucursal_id
              AND fecha_operacion = :fecha_operacion
            """
        ),
        {"empresa_id": int(empresa_id), "sucursal_id": int(sucursal_id), "fecha_operacion": fecha_operacion},
    ).first()
    return money(row[0] if row else 0)


def refresh_caja_por_gastos(
    db: Session,
    *,
    empresa_id: int,
    sucursal_id: int,
    fecha_operacion: date,
    usuario_id: int | None = None,
) -> None:
    row = db.execute(
        text(
            """
            SELECT base, guardado, total_contado, observacion, usuario_id
            FROM petalops.caja
            WHERE empresa_id = :empresa_id
              AND sucursal_id = :sucursal_id
              AND fecha = :fecha_operacion
            LIMIT 1
            """
        ),
        {"empresa_id": int(empresa_id), "sucursal_id": int(sucursal_id), "fecha_operacion": fecha_operacion},
    ).mappings().first()

    base = money(row["base"] if row else None)
    if not row:
        base = load_base_anterior(db, empresa_id=empresa_id, sucursal_id=sucursal_id, fecha_operacion=fecha_operacion)
    efectivo = load_efectivo_ventas(db, empresa_id=empresa_id, sucursal_id=sucursal_id, fecha_operacion=fecha_operacion)
    gasto = load_gastos_total(db, empresa_id=empresa_id, sucursal_id=sucursal_id, fecha_operacion=fecha_operacion)
    total_efectivo = base + efectivo - gasto
    if total_efectivo < 0:
        raise ValueError("gastos_exceden_disponible")

    guardado = money(row["guardado"] if row else None)
    total_contado = money(row["total_contado"]) if row and row["total_contado"] is not None else None
    if total_contado is None:
        sobrante = Decimal("0")
        faltante = Decimal("0")
        nueva_base = max(total_efectivo - guardado, Decimal("0"))
    else:
        diferencia = total_contado - total_efectivo
        sobrante = max(diferencia, Decimal("0"))
        faltante = max(-diferencia, Decimal("0"))
        nueva_base = max(total_contado - guardado, Decimal("0"))

    upsert_caja(
        db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        fecha=fecha_operacion,
        base=base,
        efectivo=efectivo,
        gasto=gasto,
        total_efectivo=total_efectivo,
        guardado=guardado,
        nueva_base=nueva_base,
        total_contado=total_contado,
        sobrante=sobrante,
        faltante=faltante,
        observacion=str(row["observacion"] or "") if row else "",
        usuario_id=usuario_id if usuario_id is not None else (row["usuario_id"] if row else None),
    )


def upsert_caja(
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
    total_contado: Decimal | None,
    sobrante: Decimal,
    faltante: Decimal,
    observacion: str,
    usuario_id: int | None,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO petalops.caja (
                empresa_id,
                sucursal_id,
                fecha,
                base,
                efectivo,
                gasto,
                total_efectivo,
                guardado,
                nueva_base,
                total_contado,
                sobrante,
                faltante,
                observacion,
                usuario_id,
                updated_at
            )
            VALUES (
                :empresa_id,
                :sucursal_id,
                :fecha,
                :base,
                :efectivo,
                :gasto,
                :total_efectivo,
                :guardado,
                :nueva_base,
                :total_contado,
                :sobrante,
                :faltante,
                :observacion,
                :usuario_id,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT (empresa_id, sucursal_id, fecha)
            DO UPDATE SET
                base = EXCLUDED.base,
                efectivo = EXCLUDED.efectivo,
                gasto = EXCLUDED.gasto,
                total_efectivo = EXCLUDED.total_efectivo,
                guardado = EXCLUDED.guardado,
                nueva_base = EXCLUDED.nueva_base,
                total_contado = EXCLUDED.total_contado,
                sobrante = EXCLUDED.sobrante,
                faltante = EXCLUDED.faltante,
                observacion = EXCLUDED.observacion,
                usuario_id = EXCLUDED.usuario_id,
                updated_at = CURRENT_TIMESTAMP
            """
        ),
        {
            "empresa_id": int(empresa_id),
            "sucursal_id": int(sucursal_id),
            "fecha": fecha,
            "base": base,
            "efectivo": efectivo,
            "gasto": gasto,
            "total_efectivo": total_efectivo,
            "guardado": guardado,
            "nueva_base": nueva_base,
            "total_contado": total_contado,
            "sobrante": sobrante,
            "faltante": faltante,
            "observacion": observacion,
            "usuario_id": (int(usuario_id) if usuario_id is not None else None),
        },
    )


def refresh_caja_por_pedido(db: Session, *, pedido, usuario_id: int | None = None) -> None:
    if not pedido or not getattr(pedido, "fechaPedido", None):
        return

    empresa_id = int(pedido.empresaID)
    sucursal_id = int(pedido.sucursalID)
    fecha_operacion = pedido.fechaPedido.date()
    efectivo = load_efectivo_ventas(
        db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        fecha_operacion=fecha_operacion,
    )

    row = db.execute(
        text(
            """
            SELECT base, gasto, guardado, total_contado, observacion, usuario_id
            FROM petalops.caja
            WHERE empresa_id = :empresa_id
              AND sucursal_id = :sucursal_id
              AND fecha = :fecha_operacion
            LIMIT 1
            """
        ),
        {
            "empresa_id": empresa_id,
            "sucursal_id": sucursal_id,
            "fecha_operacion": fecha_operacion,
        },
    ).mappings().first()

    base = money(row["base"] if row else None)
    if not row:
        base = load_base_anterior(
            db,
            empresa_id=empresa_id,
            sucursal_id=sucursal_id,
            fecha_operacion=fecha_operacion,
        )
    gasto = money(row["gasto"] if row else None)
    guardado = money(row["guardado"] if row else None)
    observacion = str(row["observacion"] or "") if row else ""
    resolved_usuario_id = usuario_id if usuario_id is not None else (row["usuario_id"] if row else None)
    total_efectivo = base + efectivo - gasto
    total_contado = money(row["total_contado"]) if row and row["total_contado"] is not None else None
    if total_contado is None:
        sobrante = Decimal("0")
        faltante = Decimal("0")
        nueva_base = max(total_efectivo - guardado, Decimal("0"))
    else:
        diferencia = total_contado - total_efectivo
        sobrante = max(diferencia, Decimal("0"))
        faltante = max(-diferencia, Decimal("0"))
        nueva_base = max(total_contado - guardado, Decimal("0"))

    upsert_caja(
        db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        fecha=fecha_operacion,
        base=base,
        efectivo=efectivo,
        gasto=gasto,
        total_efectivo=total_efectivo,
        guardado=guardado,
        nueva_base=nueva_base,
        total_contado=total_contado,
        sobrante=sobrante,
        faltante=faltante,
        observacion=observacion,
        usuario_id=resolved_usuario_id,
    )
