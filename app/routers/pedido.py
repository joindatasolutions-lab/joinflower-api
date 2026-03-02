from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timezone
from app.database import get_db
from app.models.producto import Producto
from app.models.cliente import Cliente
from app.models.pedido import Pedido
from app.models.pedidodetalle import PedidoDetalle
from app.models.transicionestadopedido import TransicionEstadoPedido

from app.schemas.pedido import PedidoCheckoutRequest, PedidoCheckoutResponse, PedidoCreate
from app.services.pedido_service import checkout_pedido

router = APIRouter()


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