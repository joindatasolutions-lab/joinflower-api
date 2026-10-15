from sqlalchemy import String, and_, cast, exists, func, or_, text
from app.models.pedido import Pedido
from app.models.cliente import Cliente
from app.models.entrega import Entrega
from app.models.pedidodetalle import PedidoDetalle
from app.models.producto import Producto
from app.models.sucursal import Sucursal


def order_search_condition(term):
    payment_and_channel_search = text(
        """
        (
            EXISTS (
                SELECT 1
                FROM petalops.pago p
                LEFT JOIN petalops.pago_metodo pm
                  ON pm.pago_id = p.id_pago
                 AND pm.empresa_id = p.empresa_id
                LEFT JOIN petalops.metodo_pago_catalogo mpc
                  ON mpc.id_metodo_pago = pm.metodo_pago_id
                 AND mpc.empresa_id = p.empresa_id
                WHERE p.empresa_id = petalops.pedido.empresa_id
                  AND p.pedido_id = petalops.pedido.id_pedido
                  AND (
                      COALESCE(p.metodo_pago, '') ILIKE :search_term
                      OR COALESCE(p.proveedor, '') ILIKE :search_term
                      OR COALESCE(p.referencia, '') ILIKE :search_term
                      OR COALESCE(mpc.nombre, '') ILIKE :search_term
                  )
            )
            OR EXISTS (
                SELECT 1
                FROM petalops.pedido_canal_venta pcv
                JOIN petalops.canal_venta cv
                  ON cv.id_canal_venta = pcv.canal_venta_id
                 AND cv.empresa_id = pcv.empresa_id
                WHERE pcv.empresa_id = petalops.pedido.empresa_id
                  AND pcv.pedido_id = petalops.pedido.id_pedido
                  AND COALESCE(cv.nombre, '') ILIKE :search_term
            )
        )
        """
    ).bindparams(search_term=term)
    product_search = exists().where(and_(
        PedidoDetalle.pedidoID == Pedido.idPedido,
        PedidoDetalle.empresaID == Pedido.empresaID,
        or_(
            func.coalesce(PedidoDetalle.observacionesPersonalizados, "").ilike(term),
            exists().where(and_(
                Producto.idProducto == PedidoDetalle.productoID,
                Producto.empresaID == PedidoDetalle.empresaID,
                or_(Producto.nombreProducto.ilike(term), Producto.codigoProducto.ilike(term), Producto.codigoCatalogo.ilike(term)),
            )),
        ),
    ))
    branch_search = exists().where(and_(
        Sucursal.idSucursal == Pedido.sucursalID, Sucursal.empresaID == Pedido.empresaID,
        Sucursal.telefono.ilike(term),
    ))
    return or_(
        cast(Pedido.idPedido, String).ilike(term),
        cast(Pedido.numeroPedido, String).ilike(term),
        func.coalesce(Pedido.codigoPedido, "").ilike(term),
        func.coalesce(Cliente.nombreCompleto, "").ilike(term),
        func.coalesce(Cliente.telefono, "").ilike(term),
        func.coalesce(Cliente.telefonoCompleto, "").ilike(term),
        func.coalesce(Cliente.identificacion, "").ilike(term),
        func.coalesce(Entrega.destinatario, "").ilike(term),
        func.coalesce(Entrega.telefonoDestino, "").ilike(term),
        func.coalesce(Entrega.direccion, "").ilike(term),
        func.coalesce(Entrega.barrioNombre, "").ilike(term),
        func.coalesce(Entrega.mensaje, "").ilike(term),
        func.coalesce(Entrega.firma, "").ilike(term),
        func.coalesce(Entrega.firmaNombre, "").ilike(term),
        func.coalesce(Entrega.observacionGeneral, "").ilike(term),
        func.coalesce(Entrega.observaciones, "").ilike(term),
        product_search, branch_search, payment_and_channel_search,
    )
