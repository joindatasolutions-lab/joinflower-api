from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import or_, cast, String, func
from datetime import datetime, timezone
from app.database import get_db
from app.models.producto import Producto
from app.models.cliente import Cliente
from app.models.pedido import Pedido
from app.models.pedidodetalle import PedidoDetalle
from app.models.transicionestadopedido import TransicionEstadoPedido
from app.models.estadopedido import EstadoPedido
from app.models.entrega import Entrega

from app.schemas.pedido import (
    PedidoCheckoutRequest,
    PedidoCheckoutResponse,
    PedidoCreate,
    PedidoListResponse,
    PedidoListItem,
    PedidoDetalleResponse,
    PedidoDetalleProducto,
    RechazarPedidoRequest,
)
from app.services.pedido_service import checkout_pedido

router = APIRouter()


def _numero_pedido_humano(pedido_id: int) -> str:
    return f"PED-{pedido_id:06d}"


def _buscar_estado_por_nombre(db: Session, *nombres: str) -> EstadoPedido | None:
    nombres_upper = [nombre.upper() for nombre in nombres]
    return (
        db.query(EstadoPedido)
        .filter(func.upper(EstadoPedido.nombreEstado).in_(nombres_upper), EstadoPedido.activo == True)
        .order_by(EstadoPedido.idEstadoPedido.asc())
        .first()
    )


def _ids_estado_pendiente(db: Session) -> set[int]:
    estados = (
        db.query(EstadoPedido)
        .filter(func.upper(EstadoPedido.nombreEstado).in_(["PENDIENTE", "CREADO"]), EstadoPedido.activo == True)
        .all()
    )
    return {int(estado.idEstadoPedido) for estado in estados}


@router.get("/pedidos", response_model=PedidoListResponse)
def listar_pedidos(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    estado: str | None = Query(None),
    q: str | None = Query(None),
    fecha_desde: datetime | None = Query(None, alias="fechaDesde"),
    fecha_hasta: datetime | None = Query(None, alias="fechaHasta"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    db: Session = Depends(get_db),
):
    base = (
        db.query(Pedido.idPedido)
        .join(Cliente, Cliente.idCliente == Pedido.clienteID)
        .outerjoin(Entrega, Entrega.pedidoID == Pedido.idPedido)
        .outerjoin(EstadoPedido, EstadoPedido.idEstadoPedido == Pedido.estadoPedidoID)
        .filter(Pedido.empresaID == empresa_id)
    )

    if sucursal_id is not None:
        base = base.filter(Pedido.sucursalID == sucursal_id)

    if estado:
        base = base.filter(func.upper(EstadoPedido.nombreEstado) == estado.upper())

    if fecha_desde:
        base = base.filter(Pedido.fechaPedido >= fecha_desde)

    if fecha_hasta:
        base = base.filter(Pedido.fechaPedido <= fecha_hasta)

    if q:
        term = f"%{q.strip()}%"
        base = (
            base.outerjoin(PedidoDetalle, PedidoDetalle.pedidoID == Pedido.idPedido)
            .outerjoin(Producto, Producto.idProducto == PedidoDetalle.productoID)
            .filter(
                or_(
                    cast(Pedido.idPedido, String).like(term),
                    Cliente.nombreCompleto.like(term),
                    Cliente.telefono.like(term),
                    Cliente.identificacion.like(term),
                    Entrega.destinatario.like(term),
                    Producto.nombreProducto.like(term),
                )
            )
        )

    total = base.distinct().count()

    ids_page = (
        base.distinct()
        .order_by(Pedido.fechaPedido.desc(), Pedido.idPedido.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    pedido_ids = [int(row[0]) for row in ids_page]
    if not pedido_ids:
        return PedidoListResponse(items=[], total=total, page=page, pageSize=page_size)

    pedido_rows = (
        db.query(Pedido, Cliente, Entrega, EstadoPedido)
        .join(Cliente, Cliente.idCliente == Pedido.clienteID)
        .outerjoin(Entrega, Entrega.pedidoID == Pedido.idPedido)
        .outerjoin(EstadoPedido, EstadoPedido.idEstadoPedido == Pedido.estadoPedidoID)
        .filter(Pedido.idPedido.in_(pedido_ids))
        .all()
    )

    detalles_rows = (
        db.query(PedidoDetalle.pedidoID, Producto.nombreProducto)
        .join(Producto, Producto.idProducto == PedidoDetalle.productoID)
        .filter(PedidoDetalle.pedidoID.in_(pedido_ids))
        .all()
    )

    productos_por_pedido: dict[int, list[str]] = {}
    for pedido_id, nombre_producto in detalles_rows:
        productos_por_pedido.setdefault(int(pedido_id), []).append(str(nombre_producto or "Producto"))

    rows_map = {int(pedido.idPedido): (pedido, cliente, entrega, estado_db) for pedido, cliente, entrega, estado_db in pedido_rows}

    items: list[PedidoListItem] = []
    for pedido_id in pedido_ids:
        pedido, cliente, entrega, estado_db = rows_map[pedido_id]
        items.append(
            PedidoListItem(
                pedidoID=pedido_id,
                numeroPedido=_numero_pedido_humano(pedido_id),
                fecha=pedido.fechaPedido,
                cliente=str(cliente.nombreCompleto or "Cliente"),
                destinatario=str((entrega.destinatario if entrega else None) or ""),
                productos=productos_por_pedido.get(pedido_id, []),
                total=float(pedido.totalNeto or 0),
                metodoPago=None,
                estado=str((estado_db.nombreEstado if estado_db else "SIN_ESTADO") or "SIN_ESTADO"),
                telefono=str(cliente.telefono or ""),
                telefonoCompleto=str(cliente.telefonoCompleto or "") if hasattr(cliente, "telefonoCompleto") else None,
            )
        )

    return PedidoListResponse(items=items, total=total, page=page, pageSize=page_size)


@router.get("/pedido/{pedido_id}/detalle", response_model=PedidoDetalleResponse)
def obtener_detalle_pedido(pedido_id: int, db: Session = Depends(get_db)):
    row = (
        db.query(Pedido, Cliente, Entrega, EstadoPedido)
        .join(Cliente, Cliente.idCliente == Pedido.clienteID)
        .outerjoin(Entrega, Entrega.pedidoID == Pedido.idPedido)
        .outerjoin(EstadoPedido, EstadoPedido.idEstadoPedido == Pedido.estadoPedidoID)
        .filter(Pedido.idPedido == pedido_id)
        .first()
    )

    if not row:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    pedido, cliente, entrega, estado_db = row

    detalles = (
        db.query(PedidoDetalle, Producto)
        .join(Producto, Producto.idProducto == PedidoDetalle.productoID)
        .filter(PedidoDetalle.pedidoID == pedido.idPedido)
        .all()
    )

    productos = [
        PedidoDetalleProducto(
            productoID=int(producto.idProducto),
            nombreProducto=str(producto.nombreProducto or "Producto"),
            cantidad=float(detalle.cantidad or 0),
            precioUnitario=float(detalle.precioUnitario or 0),
            subtotal=float(detalle.subtotal or 0),
        )
        for detalle, producto in detalles
    ]

    return PedidoDetalleResponse(
        pedidoID=int(pedido.idPedido),
        numeroPedido=_numero_pedido_humano(int(pedido.idPedido)),
        fecha=pedido.fechaPedido,
        estado=str((estado_db.nombreEstado if estado_db else "SIN_ESTADO") or "SIN_ESTADO"),
        empresaID=int(pedido.empresaID),
        sucursalID=int(pedido.sucursalID),
        motivoRechazo=pedido.motivoRechazo,
        cliente={
            "nombre": cliente.nombreCompleto,
            "telefono": cliente.telefono,
            "telefonoCompleto": getattr(cliente, "telefonoCompleto", None),
            "email": cliente.email,
            "identificacion": cliente.identificacion,
            "tipoIdent": getattr(cliente, "tipoIdent", None),
        },
        destinatario={
            "nombre": entrega.destinatario if entrega else None,
            "telefono": entrega.telefonoDestino if entrega else None,
            "direccion": entrega.direccion if entrega else None,
            "barrio": entrega.barrioNombre if entrega else None,
            "fechaEntrega": entrega.fechaEntrega.isoformat() if entrega and entrega.fechaEntrega else None,
            "horaEntrega": entrega.rangoHora if entrega else None,
            "mensajeTarjeta": entrega.mensaje if entrega else None,
        },
        financiero={
            "subtotal": float(pedido.totalBruto or 0),
            "iva": float(pedido.totalIva or 0),
            "domicilio": 0.0,
            "total": float(pedido.totalNeto or 0),
            "estadoPago": None,
            "metodoPago": None,
            "cuentaBancaria": None,
        },
        productos=productos,
    )


@router.put("/pedido/{pedido_id}/aprobar")
def aprobar_pedido(pedido_id: int, db: Session = Depends(get_db)):
    pedido = db.query(Pedido).filter(Pedido.idPedido == pedido_id).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    pendientes = _ids_estado_pendiente(db)
    if pendientes and int(pedido.estadoPedidoID) not in pendientes:
        raise HTTPException(status_code=400, detail="Solo se pueden aprobar pedidos en estado Pendiente")

    estado_aprobado = _buscar_estado_por_nombre(db, "APROBADO", "PAGADO")
    if not estado_aprobado:
        raise HTTPException(status_code=400, detail="No existe estado de aprobación activo (APROBADO/PAGADO)")

    pedido.estadoPedidoID = estado_aprobado.idEstadoPedido
    pedido.motivoRechazo = None
    pedido.updatedAt = datetime.now(timezone.utc)
    db.commit()

    return {
        "status": "ok",
        "pedidoID": pedido_id,
        "estado": str(estado_aprobado.nombreEstado),
        "notificaProduccion": True,
    }


@router.put("/pedido/{pedido_id}/rechazar")
def rechazar_pedido(pedido_id: int, payload: RechazarPedidoRequest, db: Session = Depends(get_db)):
    motivo = (payload.motivo or "").strip()
    if not motivo:
        raise HTTPException(status_code=400, detail="El motivo de rechazo es obligatorio")

    pedido = db.query(Pedido).filter(Pedido.idPedido == pedido_id).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    pendientes = _ids_estado_pendiente(db)
    if pendientes and int(pedido.estadoPedidoID) not in pendientes:
        raise HTTPException(status_code=400, detail="Solo se pueden rechazar pedidos en estado Pendiente")

    estado_rechazado = _buscar_estado_por_nombre(db, "RECHAZADO", "CANCELADO")
    if not estado_rechazado:
        raise HTTPException(status_code=400, detail="No existe estado de rechazo activo (RECHAZADO/CANCELADO)")

    pedido.estadoPedidoID = estado_rechazado.idEstadoPedido
    pedido.motivoRechazo = motivo[:300]
    pedido.updatedAt = datetime.now(timezone.utc)
    db.commit()

    return {
        "status": "ok",
        "pedidoID": pedido_id,
        "estado": str(estado_rechazado.nombreEstado),
        "motivo": pedido.motivoRechazo,
    }


@router.post("/pedido/checkout", response_model=PedidoCheckoutResponse)
def checkout(data: PedidoCheckoutRequest, db: Session = Depends(get_db)):
    """Endpoint de checkout: delega la lógica transaccional al servicio de pedidos."""
    return checkout_pedido(db=db, payload=data)


@router.post("/pedido")
def crear_pedido(data: PedidoCreate, db: Session = Depends(get_db)):

    try:

        # 1️⃣ Validar productos
        productos_db = (
            db.query(Producto)
            .filter(
                Producto.idProducto.in_([i.productoId for i in data.items]),
                Producto.activo == True,
                Producto.empresaID == data.empresaId
            )
            .all()
        )

        if len(productos_db) != len(data.items):
            raise HTTPException(status_code=400, detail="Producto inválido")

        # 2️⃣ Calcular totales
        subtotal = 0
        total_iva = 0

        for item in data.items:
            producto = next(p for p in productos_db if p.idProducto == item.productoId)

            precio = float(producto.precioBase)
            linea = precio * item.cantidad

            subtotal += linea

        total = subtotal  # luego agregamos IVA real

        # 3️⃣ Crear cliente (simplificado)
        cliente = Cliente(
            empresaID=data.empresaId,
            nombres=data.cliente.nombres,
            telefono=data.cliente.telefono,
            email=data.cliente.email,
            activo=True
        )

        db.add(cliente)
        db.flush()  # obtiene idCliente sin commit

        # 4️⃣ Crear pedido
        pedido = Pedido(
            empresaID=data.empresaId,
            sucursalID=data.sucursalId,
            clienteID=cliente.idCliente,
            fechaPedido=datetime.now(timezone.utc),
            estadoPedidoID=1,  # Pedido Registrado
            totalBruto=subtotal,
            totalIva=total_iva,
            totalNeto=total
        )

        db.add(pedido)
        db.flush()

        # 5️⃣ Crear detalles
        for item in data.items:
            producto = next(p for p in productos_db if p.idProducto == item.productoId)

            detalle = PedidoDetalle(
                pedidoID=pedido.idPedido,
                productoID=producto.idProducto,
                cantidad=item.cantidad,
                precioUnitario=producto.precioBase,
                totalLinea=float(producto.precioBase) * item.cantidad
            )

            db.add(detalle)

        db.commit()

        return {
            "status": "ok",
            "idPedido": pedido.idPedido,
            "total": total
        }

    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    
@router.put("/pedido/{pedido_id}/estado/{nuevo_estado_id}")
def cambiar_estado(
    pedido_id: int,
    nuevo_estado_id: int,
    db: Session = Depends(get_db)
):
    # 1️⃣ Buscar pedido
    pedido = db.query(Pedido).filter(Pedido.idPedido == pedido_id).first()

    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    estado_actual = pedido.estadoPedidoID

    # 2️⃣ Validar transición permitida
    transicion = db.query(TransicionEstadoPedido).filter(
        TransicionEstadoPedido.empresaID == pedido.empresaID,
        TransicionEstadoPedido.estadoOrigenID == estado_actual,
        TransicionEstadoPedido.estadoDestinoID == nuevo_estado_id
    ).first()

    if not transicion:
        raise HTTPException(
            status_code=400,
            detail="Transición de estado no permitida"
        )

    # 3️⃣ Actualizar estado
    pedido.estadoPedidoID = nuevo_estado_id

    db.commit()

    return {"status": "ok", "nuevoEstado": nuevo_estado_id}