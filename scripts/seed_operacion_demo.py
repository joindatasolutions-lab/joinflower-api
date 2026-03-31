from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from sqlalchemy import text

# Permite ejecutar el script directamente sin configurar PYTHONPATH.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal


DEC2 = Decimal("0.01")


@dataclass
class PedidoStateIds:
    aprobado: int
    en_produccion: int
    listo: int
    entregado: int


@dataclass
class ProduccionStateIds:
    pendiente: int
    en_proceso: int
    terminado: int


def d2(value: Decimal | float | int) -> Decimal:
    return Decimal(value).quantize(DEC2, rounding=ROUND_HALF_UP)


def ensure_estado_entrega(db) -> None:
    defaults = [
        (1, "pendiente", "Pendiente", 1),
        (2, "asignado", "Asignado", 2),
        (3, "en_ruta", "En ruta", 3),
        (4, "entregado", "Entregado", 4),
        (5, "no_entregado", "No entregado", 5),
        (6, "cancelado", "Cancelado", 6),
    ]
    for estado_id, codigo, nombre, orden in defaults:
        db.execute(
            text(
                """
                INSERT INTO petalops.estado_entrega
                (id_estado_entrega, codigo, nombre, orden, created_at)
                VALUES (:id_estado_entrega, :codigo, :nombre, :orden, CURRENT_TIMESTAMP)
                ON CONFLICT (id_estado_entrega) DO NOTHING
                """
            ),
            {
                "id_estado_entrega": estado_id,
                "codigo": codigo,
                "nombre": nombre,
                "orden": orden,
            },
        )


def resolve_pedido_states(db) -> PedidoStateIds:
    rows = db.execute(
        text(
            """
            SELECT id_estado_pedido, upper(nombre_estado)
            FROM petalops.estado_pedido
            """
        )
    ).fetchall()
    by_name = {str(name): int(state_id) for state_id, name in rows}

    def pick(name: str, fallback: int) -> int:
        return by_name.get(name, fallback)

    return PedidoStateIds(
        aprobado=pick("APROBADO", 2),
        en_produccion=pick("EN_PRODUCCION", 4),
        listo=pick("LISTO", 5),
        entregado=pick("ENTREGADO", 20),
    )


def resolve_produccion_states(db) -> ProduccionStateIds:
    rows = db.execute(
        text(
            """
            SELECT id_estado_produccion, lower(coalesce(codigo, nombre))
            FROM petalops.estado_produccion
            """
        )
    ).fetchall()
    by_code = {str(code): int(state_id) for state_id, code in rows}

    return ProduccionStateIds(
        pendiente=by_code.get("pendiente", 1),
        en_proceso=by_code.get("en_proceso", 3),
        terminado=by_code.get("terminado", 4),
    )


def ensure_counter_row(db, empresa_id: int, sucursal_id: int) -> None:
    db.execute(
        text(
            """
            INSERT INTO petalops.sucursal_contador_pedido (empresa_id, sucursal_id, ultimo_pedido, updated_at)
            VALUES (:empresa_id, :sucursal_id, 0, CURRENT_TIMESTAMP)
            ON CONFLICT (empresa_id, sucursal_id) DO NOTHING
            """
        ),
        {"empresa_id": empresa_id, "sucursal_id": sucursal_id},
    )


def next_numero_pedido(db, empresa_id: int, sucursal_id: int) -> int:
    row = db.execute(
        text(
            """
            UPDATE petalops.sucursal_contador_pedido
            SET ultimo_pedido = ultimo_pedido + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE empresa_id = :empresa_id
              AND sucursal_id = :sucursal_id
            RETURNING ultimo_pedido
            """
        ),
        {"empresa_id": empresa_id, "sucursal_id": sucursal_id},
    ).first()
    return int(row[0])


def ensure_empleados(db, empresa_id: int, sucursal_id: int) -> tuple[list[int], list[int]]:
    floristas = [
        "Florista Demo 1",
        "Florista Demo 2",
        "Florista Demo 3",
    ]
    domiciliarios = [
        "Domiciliario Demo 1",
        "Domiciliario Demo 2",
    ]

    def upsert(nombre: str, cargo: str, identificacion: str) -> int:
        row = db.execute(
            text(
                """
                SELECT id_empleado
                FROM petalops.empleado
                WHERE empresa_id = :empresa_id
                  AND identificacion = :identificacion
                LIMIT 1
                """
            ),
            {"empresa_id": empresa_id, "identificacion": identificacion},
        ).first()
        if row:
            return int(row[0])

        row = db.execute(
            text(
                """
                INSERT INTO petalops.empleado
                (empresa_id, sucursal_id, nombre_empleado, cargo, activo, identificacion, created_at, updated_at)
                VALUES
                (:empresa_id, :sucursal_id, :nombre_empleado, :cargo, 1, :identificacion, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id_empleado
                """
            ),
            {
                "empresa_id": empresa_id,
                "sucursal_id": sucursal_id,
                "nombre_empleado": nombre,
                "cargo": cargo,
                "identificacion": identificacion,
            },
        ).first()
        return int(row[0])

    florista_ids = [
        upsert(nombre, "Florista", f"FLR-{empresa_id}-{sucursal_id}-{idx}")
        for idx, nombre in enumerate(floristas, start=1)
    ]
    domiciliario_ids = [
        upsert(nombre, "Domiciliario", f"DOM-{empresa_id}-{sucursal_id}-{idx}")
        for idx, nombre in enumerate(domiciliarios, start=1)
    ]
    return florista_ids, domiciliario_ids


def ensure_clientes(db, empresa_id: int, count: int) -> list[int]:
    existing = db.execute(
        text(
            """
            SELECT cliente_id
            FROM petalops.cliente
            WHERE empresa_id = :empresa_id
            ORDER BY cliente_id
            """
        ),
        {"empresa_id": empresa_id},
    ).fetchall()
    cliente_ids = [int(row[0]) for row in existing]

    missing = max(0, count - len(cliente_ids))
    for idx in range(1, missing + 1):
        seq = len(cliente_ids) + idx
        row = db.execute(
            text(
                """
                INSERT INTO petalops.cliente
                (empresa_id, tipo_ident, identificacion, indicativo, telefono_completo, nombre_completo, telefono, email, activo, created_at, updated_at)
                VALUES
                (:empresa_id, 'CC', :identificacion, '+57', :telefono_completo, :nombre_completo, :telefono, :email, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING cliente_id
                """
            ),
            {
                "empresa_id": empresa_id,
                "identificacion": f"CLI-{empresa_id}-{seq:05d}",
                "telefono_completo": f"+573001000{seq:03d}",
                "nombre_completo": f"Cliente Demo {seq}",
                "telefono": f"3001000{seq:03d}",
                "email": f"cliente{seq}@demo.local",
            },
        ).first()
        cliente_ids.append(int(row[0]))

    return cliente_ids


def fetch_productos(db, empresa_id: int) -> list[tuple[int, str]]:
    rows = db.execute(
        text(
            """
            SELECT id_producto, nombre_producto
            FROM petalops.producto
            WHERE empresa_id = :empresa_id
              AND coalesce(activo, true) = true
            ORDER BY id_producto
            """
        ),
        {"empresa_id": empresa_id},
    ).fetchall()
    return [(int(row[0]), str(row[1] or f"Producto {row[0]}")) for row in rows]


def resolve_sucursal(db, empresa_id: int, sucursal_id: int | None) -> tuple[int, str]:
    if sucursal_id is None:
        row = db.execute(
            text(
                """
                SELECT id_sucursal, coalesce(prefijo_pedido, 'PED')
                FROM petalops.sucursal
                WHERE empresa_id = :empresa_id
                ORDER BY id_sucursal
                LIMIT 1
                """
            ),
            {"empresa_id": empresa_id},
        ).first()
    else:
        row = db.execute(
            text(
                """
                SELECT id_sucursal, coalesce(prefijo_pedido, 'PED')
                FROM petalops.sucursal
                WHERE empresa_id = :empresa_id
                  AND id_sucursal = :sucursal_id
                LIMIT 1
                """
            ),
            {"empresa_id": empresa_id, "sucursal_id": sucursal_id},
        ).first()

    if not row:
        raise ValueError(f"No existe sucursal para empresa_id={empresa_id} con sucursal_id={sucursal_id}")
    return int(row[0]), str(row[1] or "PED")


def seed_operacion(empresa_id: int, sucursal_id: int | None, pedidos: int, seed: int) -> None:
    rng = random.Random(seed)
    db = SessionLocal()
    try:
        with db.begin():
            empresa_exists = db.execute(
                text("SELECT 1 FROM petalops.empresa WHERE id_empresa = :empresa_id LIMIT 1"),
                {"empresa_id": empresa_id},
            ).first()
            if not empresa_exists:
                raise ValueError(f"No existe empresa_id={empresa_id}")

            sucursal_id_resolved, prefijo = resolve_sucursal(db, empresa_id, sucursal_id)
            ensure_estado_entrega(db)
            pedido_states = resolve_pedido_states(db)
            prod_states = resolve_produccion_states(db)
            ensure_counter_row(db, empresa_id, sucursal_id_resolved)

            florista_ids, domiciliario_ids = ensure_empleados(db, empresa_id, sucursal_id_resolved)
            cliente_ids = ensure_clientes(db, empresa_id, max(pedidos, 10))
            productos = fetch_productos(db, empresa_id)
            if not productos:
                raise ValueError(
                    f"No hay productos activos para empresa_id={empresa_id}. Crea catálogo primero."
                )

            created_pedidos = 0
            created_detalles = 0
            created_producciones = 0
            created_entregas = 0

            now = datetime.now()
            for idx in range(1, pedidos + 1):
                cliente_id = rng.choice(cliente_ids)
                num_items = 1 if len(productos) == 1 else rng.randint(1, min(3, len(productos)))
                selected_products = rng.sample(productos, k=num_items)

                detalle_rows = []
                total_bruto = Decimal("0")
                total_iva = Decimal("0")

                for producto_id, _nombre in selected_products:
                    qty = Decimal(rng.randint(1, 3))
                    precio_unit = d2(25000 + ((producto_id * 113 + idx * 331) % 60000))
                    iva_unit = d2(precio_unit * Decimal("0.19"))
                    subtotal = d2(precio_unit * qty)
                    total_bruto += subtotal
                    total_iva += d2(iva_unit * qty)
                    detalle_rows.append((producto_id, qty, precio_unit, iva_unit, subtotal))

                total_neto = d2(total_bruto + total_iva)
                numero_pedido = next_numero_pedido(db, empresa_id, sucursal_id_resolved)
                codigo_pedido = f"{prefijo}-{numero_pedido:06d}"
                fecha_pedido = now - timedelta(days=rng.randint(0, 9), hours=rng.randint(0, 23))

                if idx % 4 == 1:
                    pedido_estado = pedido_states.aprobado
                    prod_estado = prod_states.pendiente
                    entrega_estado = 1
                elif idx % 4 == 2:
                    pedido_estado = pedido_states.en_produccion
                    prod_estado = prod_states.en_proceso
                    entrega_estado = 2
                elif idx % 4 == 3:
                    pedido_estado = pedido_states.listo
                    prod_estado = prod_states.terminado
                    entrega_estado = 3
                else:
                    pedido_estado = pedido_states.entregado
                    prod_estado = prod_states.terminado
                    entrega_estado = 4

                pedido_row = db.execute(
                    text(
                        """
                        INSERT INTO petalops.pedido
                        (empresa_id, sucursal_id, cliente_id, fecha_pedido, estado_pedido_id, version, total_bruto, total_iva, total_neto, created_at, updated_at, numero_pedido, codigo_pedido)
                        VALUES
                        (:empresa_id, :sucursal_id, :cliente_id, :fecha_pedido, :estado_pedido_id, 1, :total_bruto, :total_iva, :total_neto, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, :numero_pedido, :codigo_pedido)
                        RETURNING id_pedido
                        """
                    ),
                    {
                        "empresa_id": empresa_id,
                        "sucursal_id": sucursal_id_resolved,
                        "cliente_id": cliente_id,
                        "fecha_pedido": fecha_pedido,
                        "estado_pedido_id": pedido_estado,
                        "total_bruto": total_bruto,
                        "total_iva": total_iva,
                        "total_neto": total_neto,
                        "numero_pedido": numero_pedido,
                        "codigo_pedido": codigo_pedido,
                    },
                ).first()
                pedido_id = int(pedido_row[0])
                created_pedidos += 1

                produccion_ids = []
                for det_idx, (producto_id, qty, precio_unit, iva_unit, subtotal) in enumerate(detalle_rows, start=1):
                    det_row = db.execute(
                        text(
                            """
                            INSERT INTO petalops.pedido_detalle
                            (empresa_id, sucursal_id, pedido_id, producto_id, cantidad, precio_unitario, iva_unitario, subtotal)
                            VALUES
                            (:empresa_id, :sucursal_id, :pedido_id, :producto_id, :cantidad, :precio_unitario, :iva_unitario, :subtotal)
                            RETURNING id_pedido_detalle
                            """
                        ),
                        {
                            "empresa_id": empresa_id,
                            "sucursal_id": sucursal_id_resolved,
                            "pedido_id": pedido_id,
                            "producto_id": producto_id,
                            "cantidad": qty,
                            "precio_unitario": precio_unit,
                            "iva_unitario": iva_unit,
                            "subtotal": subtotal,
                        },
                    ).first()
                    pedido_detalle_id = int(det_row[0])
                    created_detalles += 1

                    florista_id = florista_ids[(idx + det_idx) % len(florista_ids)]
                    fecha_programada = fecha_pedido.date()
                    fecha_asignacion = fecha_pedido + timedelta(hours=1)
                    fecha_inicio = fecha_asignacion + timedelta(minutes=20) if prod_estado in (prod_states.en_proceso, prod_states.terminado) else None
                    fecha_fin = fecha_inicio + timedelta(minutes=45) if (fecha_inicio and prod_estado == prod_states.terminado) else None

                    prod_row = db.execute(
                        text(
                            """
                            INSERT INTO petalops.produccion
                            (empresa_id, sucursal_id, pedido_id, pedido_detalle_id, empleado_id, fecha_programada_produccion, fecha_asignacion, fecha_inicio, fecha_finalizacion, tiempoestimadomin, tiempo_real_min, estado_produccion_id, prioridad, observacionesinternas, orden_produccion, created_at, updated_at)
                            VALUES
                            (:empresa_id, :sucursal_id, :pedido_id, :pedido_detalle_id, :empleado_id, :fecha_programada_produccion, :fecha_asignacion, :fecha_inicio, :fecha_finalizacion, :tiempoestimadomin, :tiempo_real_min, :estado_produccion_id, :prioridad, :observacionesinternas, :orden_produccion, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                            RETURNING id_produccion
                            """
                        ),
                        {
                            "empresa_id": empresa_id,
                            "sucursal_id": sucursal_id_resolved,
                            "pedido_id": pedido_id,
                            "pedido_detalle_id": pedido_detalle_id,
                            "empleado_id": florista_id,
                            "fecha_programada_produccion": fecha_programada,
                            "fecha_asignacion": fecha_asignacion,
                            "fecha_inicio": fecha_inicio,
                            "fecha_finalizacion": fecha_fin,
                            "tiempoestimadomin": 45,
                            "tiempo_real_min": (45 if fecha_fin else None),
                            "estado_produccion_id": prod_estado,
                            "prioridad": rng.choice(["BAJA", "MEDIA", "ALTA"]),
                            "observacionesinternas": "Seed automático de pruebas",
                            "orden_produccion": det_idx,
                        },
                    ).first()
                    produccion_ids.append(int(prod_row[0]))
                    created_producciones += 1

                domiciliario_id = domiciliario_ids[idx % len(domiciliario_ids)]
                fecha_programada_entrega = fecha_pedido + timedelta(hours=6)
                fecha_salida = fecha_programada_entrega if entrega_estado in (3, 4) else None
                fecha_entrega = (fecha_salida + timedelta(hours=1)) if entrega_estado == 4 and fecha_salida else None

                db.execute(
                    text(
                        """
                        INSERT INTO petalops.entrega
                        (empresa_id, sucursalid, pedido_id, produccionid, domiciliarioid, empleado_id, estadoentregaid, tipoentrega, destinatario, telefonodestino, direccion, barrionombre, rangohora, mensaje, fechaasignacion, fechasalida, fechaentregaprogramada, fechaentrega, intentonumero, createdat, updatedat, observaciones)
                        VALUES
                        (:empresa_id, :sucursalid, :pedido_id, :produccionid, :domiciliarioid, :empleado_id, :estadoentregaid, :tipoentrega, :destinatario, :telefonodestino, :direccion, :barrionombre, :rangohora, :mensaje, :fechaasignacion, :fechasalida, :fechaentregaprogramada, :fechaentrega, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, :observaciones)
                        """
                    ),
                    {
                        "empresa_id": empresa_id,
                        "sucursalid": sucursal_id_resolved,
                        "pedido_id": pedido_id,
                        "produccionid": (produccion_ids[0] if produccion_ids else None),
                        "domiciliarioid": domiciliario_id,
                        "empleado_id": domiciliario_id,
                        "estadoentregaid": entrega_estado,
                        "tipoentrega": "Domicilio",
                        "destinatario": f"Cliente {cliente_id}",
                        "telefonodestino": f"3002000{idx:03d}",
                        "direccion": f"Calle {10 + idx} # {20 + idx}-30",
                        "barrionombre": "Zona Demo",
                        "rangohora": "9:00 - 18:00",
                        "mensaje": "Entrega de prueba",
                        "fechaasignacion": fecha_pedido + timedelta(hours=5),
                        "fechasalida": fecha_salida,
                        "fechaentregaprogramada": fecha_programada_entrega,
                        "fechaentrega": fecha_entrega,
                        "observaciones": "Registro seed",
                    },
                )
                created_entregas += 1

        print(
            (
                f"Seed OK | empresa_id={empresa_id} sucursal_id={sucursal_id_resolved} "
                f"pedidos={created_pedidos} detalles={created_detalles} "
                f"producciones={created_producciones} entregas={created_entregas}"
            )
        )
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Poblar datos de prueba para pedidos, produccion y domicilios.")
    parser.add_argument("--empresa-id", type=int, default=3, help="Empresa objetivo (default: 3)")
    parser.add_argument("--sucursal-id", type=int, default=None, help="Sucursal objetivo (default: primera de la empresa)")
    parser.add_argument("--pedidos", type=int, default=25, help="Cantidad de pedidos a crear")
    parser.add_argument("--seed", type=int, default=20260327, help="Semilla aleatoria")
    args = parser.parse_args()

    if args.pedidos <= 0:
        raise ValueError("--pedidos debe ser mayor a 0")

    seed_operacion(
        empresa_id=args.empresa_id,
        sucursal_id=args.sucursal_id,
        pedidos=args.pedidos,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
