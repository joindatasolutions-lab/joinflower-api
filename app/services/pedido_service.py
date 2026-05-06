from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import String, cast, or_, func
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.barrio import Barrio
from app.models.cliente import Cliente
from app.models.empleado import Empleado
from app.models.empresa import Empresa
from app.models.entrega import Entrega
from app.models.estadopedido import EstadoPedido
from app.models.pedido import Pedido
from app.models.pedidodetalle import PedidoDetalle
from app.models.producto import Producto
from app.models.sucursal import Sucursal
from app.schemas.pedido import PedidoCheckoutRequest


def _activo_truthy(column):
    return cast(column, String).in_(["1", "true", "True", "t", "T"])


def _normalizar_telefono_completo(indicativo: str | None, telefono: str | None) -> str | None:
    prefijo = str(indicativo or "").strip().replace(" ", "")
    numero = str(telefono or "").strip().replace(" ", "")

    if not prefijo and not numero:
        return None

    if prefijo and not prefijo.startswith("+"):
        prefijo = f"+{prefijo}"

    return f"{prefijo}{numero}"


def _normalizar_activo_legacy(value: bool) -> int:
    return 1 if value else 0


def _numero_pedido_temporal() -> int:
    return -int(datetime.now(timezone.utc).timestamp() * 1000000)


def _buscar_estado_inicial_pedido(db: Session) -> EstadoPedido | None:
    return (
        db.query(EstadoPedido)
        .filter(
            func.upper(EstadoPedido.nombreEstado).in_(["CREADO", "PENDIENTE"]),
            _activo_truthy(EstadoPedido.activo),
        )
        .order_by(EstadoPedido.idEstadoPedido.asc())
        .first()
    )


def _cliente_identificacion_fallback(identificacion: str | None, telefono: str | None) -> str:
    value = str(identificacion or "").strip()
    if value:
        return value
    phone = str(telefono or "").strip()
    if phone:
        return phone
    return f"TMP-{int(datetime.now(timezone.utc).timestamp())}"


def _prefijo_desde_sucursal(sucursal: Sucursal) -> str:
    # Compatibilidad: usa un prefijo configurable si existe; si no, deriva del nombre.
    for field in ("prefijoPedido", "codigoSucursal", "abreviatura", "codigo"):
        value = getattr(sucursal, field, None)
        if value:
            raw = str(value).strip().upper()
            cleaned = "".join(ch for ch in raw if ch.isalnum())
            if cleaned:
                return cleaned[:6]

    nombre = str(getattr(sucursal, "nombreSucursal", "") or "").strip().upper()
    cleaned_name = "".join(ch for ch in nombre if ch.isalnum())
    if cleaned_name:
        return cleaned_name[:3]
    return "PED"


def generar_numeracion_pedido(db: Session, empresa_id: int, sucursal_id: int) -> tuple[int, str]:
    sucursal = (
        db.query(Sucursal)
        .filter(Sucursal.idSucursal == sucursal_id, Sucursal.empresaID == empresa_id)
        .first()
    )
    if not sucursal:
        sucursal = db.query(Sucursal).filter(Sucursal.idSucursal == sucursal_id).first()
    if not sucursal:
        raise HTTPException(status_code=400, detail="Sucursal no existe para la empresa indicada")

    prefijo = _prefijo_desde_sucursal(sucursal)
    now_utc = datetime.now(timezone.utc)

    db.execute(
        text(
            """
            INSERT INTO petalops.sucursal_contador_pedido (empresa_id, sucursal_id, ultimo_pedido, updated_at)
            VALUES (:empresa_id, :sucursal_id, 0, :updated_at)
            ON CONFLICT (empresa_id, sucursal_id) DO NOTHING
            """
        ),
        {
            "empresa_id": int(empresa_id),
            "sucursal_id": int(sucursal_id),
            "updated_at": now_utc,
        },
    )

    row = db.execute(
        text(
            """
            UPDATE petalops.sucursal_contador_pedido
            SET ultimo_pedido = ultimo_pedido + 1,
                updated_at = :updated_at
            WHERE empresa_id = :empresa_id
              AND sucursal_id = :sucursal_id
            RETURNING ultimo_pedido
            """
        ),
        {
            "empresa_id": int(empresa_id),
            "sucursal_id": int(sucursal_id),
            "updated_at": now_utc,
        },
    ).first()

    if not row or row[0] is None:
        raise HTTPException(status_code=500, detail="No fue posible generar el consecutivo del pedido")

    numero_pedido = int(row[0])
    codigo_pedido = f"{prefijo}-{numero_pedido:05d}"
    return numero_pedido, codigo_pedido


def _find_branch_product_price(db: Session, *, empresa_id: int, sucursal_id: int, producto_id: int) -> Decimal:
    row = db.execute(
        text(
            """
            SELECT ps.precio
            FROM petalops.producto_sucursal ps
            JOIN petalops.producto p
              ON p.id_producto = ps.producto_id
            WHERE p.id_producto = :producto_id
              AND p.empresa_id = :empresa_id
              AND ps.sucursal_id = :sucursal_id
              AND lower(CAST(p.activo AS VARCHAR)) IN ('true', 't', '1')
              AND lower(CAST(ps.activo AS VARCHAR)) IN ('true', 't', '1')
            LIMIT 1
            """
        ),
        {
            "producto_id": int(producto_id),
            "empresa_id": int(empresa_id),
            "sucursal_id": int(sucursal_id),
        },
    ).first()
    if not row or row[0] is None:
        raise HTTPException(status_code=400, detail="No se encontró precio activo para ese arreglo en la sucursal")
    return Decimal(str(row[0]))


def _sanitize_producto_observacion(observacion: str | None, producto: Producto | None = None) -> str | None:
    text = str(observacion or "").strip()
    if not text:
        return None
    descripcion = str(getattr(producto, "descripcion", "") or "").strip()
    if descripcion and text.casefold() == descripcion.casefold():
        return None
    return text


def _resolve_costo_domicilio(
    db: Session,
    *,
    empresa_id: int,
    sucursal_id: int,
    tipo_entrega: str | None,
    barrio_id: int | None = None,
    barrio_nombre: str | None = None,
) -> Decimal:
    tipo = str(tipo_entrega or "").strip().lower()
    if tipo and tipo != "domicilio":
        return Decimal("0.00")

    if barrio_id is not None:
        barrio = (
            db.query(Barrio)
            .filter(
                Barrio.idBarrio == int(barrio_id),
                Barrio.empresaID == int(empresa_id),
                Barrio.sucursalID == int(sucursal_id),
            )
            .first()
        )
        if barrio and barrio.costoDomicilio is not None:
            return Decimal(str(barrio.costoDomicilio)).quantize(Decimal("0.01"))

    nombre = str(barrio_nombre or "").strip()
    if nombre:
        barrio = (
            db.query(Barrio)
            .filter(
                Barrio.empresaID == int(empresa_id),
                Barrio.sucursalID == int(sucursal_id),
                func.lower(Barrio.nombreBarrio) == nombre.lower(),
            )
            .first()
        )
        if barrio and barrio.costoDomicilio is not None:
            return Decimal(str(barrio.costoDomicilio)).quantize(Decimal("0.01"))

    return Decimal("0.00")


def _expand_checkout_productos(productos: list) -> list[dict]:
    expanded: list[dict] = []
    for item in productos:
        producto_id = int(item.productoID)
        cantidad = max(int(item.cantidad), 0)
        for _ in range(cantidad):
            expanded.append(
                {
                    "productoID": producto_id,
                    "cantidad": 1,
                }
            )
    return expanded


def _crear_pedido_checkout_unitario(
    db: Session,
    *,
    empresa_id: int,
    sucursal_id: int,
    cliente_id: int,
    estado_pedido_id: int,
    fecha_pedido: datetime,
    producto: Producto,
    cantidad_entera: int,
    costo_domicilio: Decimal,
    entrega_payload,
) -> Pedido:
    pedido = Pedido(
        empresaID=empresa_id,
        sucursalID=sucursal_id,
        numeroPedido=_numero_pedido_temporal(),
        codigoPedido=None,
        clienteID=cliente_id,
        fechaPedido=fecha_pedido,
        estadoPedidoID=estado_pedido_id,
        totalBruto=Decimal("0.00"),
        totalIva=Decimal("0.00"),
        costoDomicilio=Decimal("0.00"),
        totalNeto=Decimal("0.00"),
        createdAt=datetime.now(timezone.utc),
    )
    db.add(pedido)
    db.flush()
    pedido.numeroPedido = -int(pedido.idPedido)

    precio_unitario = _find_branch_product_price(
        db,
        empresa_id=int(empresa_id),
        sucursal_id=int(sucursal_id),
        producto_id=int(producto.idProducto),
    )
    cantidad = Decimal(cantidad_entera)
    subtotal = (precio_unitario * cantidad).quantize(Decimal("0.01"))
    total_iva = Decimal("0.00")
    costo_domicilio = Decimal(str(costo_domicilio or 0)).quantize(Decimal("0.01"))

    detalle = PedidoDetalle(
        empresaID=empresa_id,
        sucursalID=sucursal_id,
        pedidoID=pedido.idPedido,
        productoID=producto.idProducto,
        cantidad=cantidad,
        precioUnitario=precio_unitario,
        ivaUnitario=Decimal("0.00"),
        subtotal=subtotal,
        observacionesPersonalizados=_sanitize_producto_observacion(None, producto),
    )
    db.add(detalle)

    pedido.totalBruto = subtotal
    pedido.totalIva = total_iva
    pedido.costoDomicilio = costo_domicilio
    pedido.totalNeto = subtotal + total_iva + costo_domicilio

    entrega = Entrega(
        empresaID=empresa_id,
        sucursalID=sucursal_id,
        pedidoID=pedido.idPedido,
        estadoEntregaID=1,
        tipoEntrega=entrega_payload.tipoEntrega,
        destinatario=entrega_payload.destinatario,
        telefonoDestino=entrega_payload.telefonoDestino,
        direccion=entrega_payload.direccion,
        barrioID=entrega_payload.barrioID,
        barrioNombre=entrega_payload.barrioNombre,
        rangoHora=entrega_payload.rangoHora,
        mensaje=entrega_payload.mensaje,
        firma=entrega_payload.firma,
        observacionGeneral=entrega_payload.observacionGeneral,
        fechaEntregaProgramada=entrega_payload.fechaEntrega,
        fechaEntrega=entrega_payload.fechaEntrega,
        latitudDestino=entrega_payload.latitudDestino,
        longitudDestino=entrega_payload.longitudDestino,
        intentoNumero=1,
        createdAt=datetime.now(timezone.utc),
    )
    db.add(entrega)
    return pedido


def checkout_pedido(db: Session, payload: PedidoCheckoutRequest) -> dict:
    """Registra un pedido completo en transacción y retorna pedidoID, total y estado."""
    if not payload.productos:
        raise HTTPException(status_code=400, detail="productos no puede estar vacío")

    for item in payload.productos:
        if item.cantidad <= 0:
            raise HTTPException(status_code=400, detail="cantidad debe ser mayor que 0")

    try:
        estado_creado = _buscar_estado_inicial_pedido(db)

        if not estado_creado:
            raise HTTPException(
                status_code=400,
                detail="No existe un estado inicial activo 'CREADO' o 'PENDIENTE' en EstadoPedido",
            )

        producto_ids = list({item.productoID for item in payload.productos})
        productos_db = (
            db.query(Producto)
            .filter(
                Producto.idProducto.in_(producto_ids),
                _activo_truthy(Producto.activo),
                Producto.empresaID == payload.empresaID,
            )
            .all()
        )

        productos_map = {producto.idProducto: producto for producto in productos_db}
        if len(productos_map) != len(producto_ids):
            raise HTTPException(status_code=400, detail="Uno o más productos no existen o están inactivos")

        cliente = (
            db.query(Cliente)
            .filter(
                Cliente.empresaID == payload.empresaID,
                or_(
                    Cliente.telefono == payload.cliente.telefono,
                    Cliente.identificacion == payload.cliente.identificacion,
                ),
            )
            .first()
        )

        if not cliente:
            cliente = Cliente(
                empresaID=payload.empresaID,
                tipoIdent=(payload.cliente.tipoIdent or "CC"),
                identificacion=_cliente_identificacion_fallback(
                    payload.cliente.identificacion,
                    payload.cliente.telefono,
                ),
                indicativo=payload.cliente.indicativo,
                telefonoCompleto=_normalizar_telefono_completo(
                    payload.cliente.indicativo,
                    payload.cliente.telefono,
                ),
                nombreCompleto=payload.cliente.nombreCompleto,
                telefono=payload.cliente.telefono,
                email=payload.cliente.email,
                activo=_normalizar_activo_legacy(True),
                createdAt=datetime.now(timezone.utc),
            )
            db.add(cliente)
            db.flush()
        else:
            cliente.tipoIdent = payload.cliente.tipoIdent or cliente.tipoIdent or "CC"
            cliente.identificacion = (
                payload.cliente.identificacion
                or cliente.identificacion
                or _cliente_identificacion_fallback(None, payload.cliente.telefono or cliente.telefono)
            )
            cliente.indicativo = payload.cliente.indicativo or cliente.indicativo
            cliente.nombreCompleto = payload.cliente.nombreCompleto or cliente.nombreCompleto
            cliente.telefono = payload.cliente.telefono or cliente.telefono
            cliente.telefonoCompleto = _normalizar_telefono_completo(
                payload.cliente.indicativo or cliente.indicativo,
                payload.cliente.telefono or cliente.telefono,
            )
            cliente.email = payload.cliente.email if payload.cliente.email is not None else cliente.email

        fecha_pedido = datetime.now(timezone.utc)

        costo_domicilio = _resolve_costo_domicilio(
            db,
            empresa_id=int(payload.empresaID),
            sucursal_id=int(payload.sucursalID),
            tipo_entrega=payload.entrega.tipoEntrega,
            barrio_id=payload.entrega.barrioID,
            barrio_nombre=payload.entrega.barrioNombre,
        )
        productos_normalizados = _expand_checkout_productos(payload.productos)
        pedidos_creados: list[Pedido] = []

        primer_producto = productos_map[int(productos_normalizados[0]["productoID"])]
        primer_pedido = _crear_pedido_checkout_unitario(
            db,
            empresa_id=int(payload.empresaID),
            sucursal_id=int(payload.sucursalID),
            cliente_id=int(cliente.idCliente),
            estado_pedido_id=int(estado_creado.idEstadoPedido),
            fecha_pedido=fecha_pedido,
            producto=primer_producto,
            cantidad_entera=int(productos_normalizados[0]["cantidad"]),
            costo_domicilio=costo_domicilio,
            entrega_payload=payload.entrega,
        )
        pedidos_creados.append(primer_pedido)

        for producto_item in productos_normalizados[1:]:
            producto = productos_map[int(producto_item["productoID"])]
            pedido_extra = _crear_pedido_checkout_unitario(
                db,
                empresa_id=int(payload.empresaID),
                sucursal_id=int(payload.sucursalID),
                cliente_id=int(cliente.idCliente),
                estado_pedido_id=int(estado_creado.idEstadoPedido),
                fecha_pedido=fecha_pedido,
                producto=producto,
                cantidad_entera=int(producto_item["cantidad"]),
                costo_domicilio=Decimal("0.00"),
                entrega_payload=payload.entrega,
            )
            pedidos_creados.append(pedido_extra)

        db.commit()

        total_general = sum(Decimal(str(item.totalNeto or 0)) for item in pedidos_creados)
        pedido_principal = pedidos_creados[0]

        return {
            "pedidoID": pedido_principal.idPedido,
            "numeroPedido": (int(pedido_principal.numeroPedido) if int(pedido_principal.numeroPedido or 0) > 0 else None),
            "codigoPedido": (str(pedido_principal.codigoPedido) if pedido_principal.codigoPedido else None),
            "pedidoIDs": [int(item.idPedido) for item in pedidos_creados],
            "cantidadPedidos": len(pedidos_creados),
            "total": float(total_general or 0),
            "estado": "CREADO",
        }

    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error registrando checkout: {exc}")
