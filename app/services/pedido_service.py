from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.cliente import Cliente
from app.models.entrega import Entrega
from app.models.estadopedido import EstadoPedido
from app.models.pedido import Pedido
from app.models.pedidodetalle import PedidoDetalle
from app.models.producto import Producto
from app.schemas.pedido import PedidoCheckoutRequest


def checkout_pedido(db: Session, payload: PedidoCheckoutRequest) -> dict:
    """Registra un pedido completo en transacción y retorna pedidoID, total y estado."""
    if not payload.productos:
        raise HTTPException(status_code=400, detail="productos no puede estar vacío")

    for item in payload.productos:
        if item.cantidad <= 0:
            raise HTTPException(status_code=400, detail="cantidad debe ser mayor que 0")

    try:
        estado_creado = (
            db.query(EstadoPedido)
            .filter(
                EstadoPedido.nombreEstado == "CREADO",
                EstadoPedido.activo == True,
            )
            .first()
        )

        if not estado_creado:
            raise HTTPException(
                status_code=400,
                detail="No existe un estado inicial activo 'CREADO' en EstadoPedido",
            )

        producto_ids = list({item.productoID for item in payload.productos})
        productos_db = (
            db.query(Producto)
            .filter(
                Producto.idProducto.in_(producto_ids),
                Producto.activo == True,
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
                Cliente.telefono == payload.cliente.telefono,
            )
            .first()
        )

        if not cliente:
            cliente = Cliente(
                empresaID=payload.empresaID,
                nombreCompleto=payload.cliente.nombreCompleto,
                telefono=payload.cliente.telefono,
                email=payload.cliente.email,
                activo=True,
            )
            db.add(cliente)
            db.flush()

        pedido = Pedido(
            empresaID=payload.empresaID,
            sucursalID=payload.sucursalID,
            clienteID=cliente.idCliente,
            fechaPedido=datetime.now(timezone.utc),
            estadoPedidoID=estado_creado.idEstadoPedido,
            totalBruto=Decimal("0.00"),
            totalIva=Decimal("0.00"),
            totalNeto=Decimal("0.00"),
        )
        db.add(pedido)
        db.flush()

        total_bruto = Decimal("0.00")
        total_iva = Decimal("0.00")

        for item in payload.productos:
            producto = productos_map[item.productoID]
            precio_unitario = Decimal(producto.precioBase or 0)
            cantidad = Decimal(item.cantidad)
            subtotal = precio_unitario * cantidad

            detalle = PedidoDetalle(
                empresaID=payload.empresaID,
                sucursalID=payload.sucursalID,
                pedidoID=pedido.idPedido,
                productoID=producto.idProducto,
                cantidad=cantidad,
                precioUnitario=precio_unitario,
                ivaUnitario=Decimal("0.00"),
                subtotal=subtotal,
            )
            db.add(detalle)
            total_bruto += subtotal

        pedido.totalBruto = total_bruto
        pedido.totalIva = total_iva
        pedido.totalNeto = total_bruto + total_iva

        entrega = Entrega(
            empresaID=payload.empresaID,
            pedidoID=pedido.idPedido,
            estadoEntregaID=1,
            fechaEntrega=payload.entrega.fechaEntrega,
        )
        db.add(entrega)

        db.commit()

        return {
            "pedidoID": pedido.idPedido,
            "total": float(pedido.totalNeto or 0),
            "estado": "CREADO",
        }

    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error registrando checkout: {exc}")
