from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.models.pedido import Pedido
from app.models.pedidodetalle import PedidoDetalle


def run_smoke_test() -> None:
    db = SessionLocal()
    try:
        pedido = (
            db.query(Pedido)
            .options(
                selectinload(Pedido.empresa),
                selectinload(Pedido.sucursal),
                selectinload(Pedido.cliente),
                selectinload(Pedido.detalles).selectinload(PedidoDetalle.producto),
                selectinload(Pedido.pagos),
                selectinload(Pedido.facturas),
                selectinload(Pedido.entrega),
            )
            .order_by(Pedido.idPedido.desc())
            .first()
        )

        if not pedido:
            print("SMOKE ORM: no hay pedidos para probar relaciones.")
            return

        print(f"Pedido: {pedido.idPedido}")
        print(f"Empresa: {pedido.empresa.nombreEmpresa if pedido.empresa else 'N/A'}")
        print(f"Sucursal: {pedido.sucursal.nombreSucursal if pedido.sucursal else 'N/A'}")
        print(f"Cliente: {pedido.cliente.nombreCompleto if pedido.cliente else 'N/A'}")
        print(f"Detalles: {len(pedido.detalles)}")
        print(f"Pagos: {len(pedido.pagos)}")
        print(f"Facturas: {len(pedido.facturas)}")
        print(f"Entrega: {'SI' if pedido.entrega else 'NO'}")

        if pedido.detalles:
            primer_detalle = pedido.detalles[0]
            producto_nombre = (
                primer_detalle.producto.nombreProducto
                if primer_detalle.producto
                else "N/A"
            )
            print(f"Primer producto en detalle: {producto_nombre}")

        print("SMOKE ORM: OK")
    finally:
        db.close()


if __name__ == "__main__":
    run_smoke_test()
