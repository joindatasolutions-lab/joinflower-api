from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.cliente import Cliente
from app.models.empleado import Empleado
from app.models.empresa import Empresa
from app.models.entrega import Entrega
from app.models.estadopedido import EstadoPedido
from app.models.pedido import Pedido
from app.models.pedidodetalle import PedidoDetalle
from app.models.producto import Producto
from app.models.sucursal import Sucursal
from app.models.sucursal_contador_pedido import SucursalContadorPedido
from app.schemas.pedido import PedidoCheckoutRequest


def _normalizar_telefono_completo(indicativo: str | None, telefono: str | None) -> str | None:
    prefijo = str(indicativo or "").strip().replace(" ", "")
    numero = str(telefono or "").strip().replace(" ", "")

    if not prefijo and not numero:
        return None

    if prefijo and not prefijo.startswith("+"):
        prefijo = f"+{prefijo}"

    return f"{prefijo}{numero}"


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
            INSERT INTO SucursalContadorPedido (empresaID, sucursalID, ultimoPedido, updatedAt)
            VALUES (:empresa_id, :sucursal_id, 0, :updated_at)
            ON DUPLICATE KEY UPDATE updatedAt = updatedAt
            """
        ),
        {
            "empresa_id": int(empresa_id),
            "sucursal_id": int(sucursal_id),
            "updated_at": now_utc,
        },
    )

    contador = (
        db.query(SucursalContadorPedido)
        .filter(
            SucursalContadorPedido.empresaID == empresa_id,
            SucursalContadorPedido.sucursalID == sucursal_id,
        )
        .with_for_update()
        .one()
    )

    contador.ultimoPedido = int(contador.ultimoPedido or 0) + 1
    contador.updatedAt = now_utc

    numero_pedido = int(contador.ultimoPedido)
    codigo_pedido = f"{prefijo}-{numero_pedido}"
    return numero_pedido, codigo_pedido


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
                tipoIdent=payload.cliente.tipoIdent,
                identificacion=payload.cliente.identificacion,
                indicativo=payload.cliente.indicativo,
                telefonoCompleto=_normalizar_telefono_completo(
                    payload.cliente.indicativo,
                    payload.cliente.telefono,
                ),
                nombreCompleto=payload.cliente.nombreCompleto,
                telefono=payload.cliente.telefono,
                email=payload.cliente.email,
                activo=True,
                createdAt=datetime.now(timezone.utc),
            )
            db.add(cliente)
            db.flush()
        else:
            cliente.tipoIdent = payload.cliente.tipoIdent or cliente.tipoIdent
            cliente.identificacion = payload.cliente.identificacion or cliente.identificacion
            cliente.indicativo = payload.cliente.indicativo or cliente.indicativo
            cliente.nombreCompleto = payload.cliente.nombreCompleto or cliente.nombreCompleto
            cliente.telefono = payload.cliente.telefono or cliente.telefono
            cliente.telefonoCompleto = _normalizar_telefono_completo(
                payload.cliente.indicativo or cliente.indicativo,
                payload.cliente.telefono or cliente.telefono,
            )
            cliente.email = payload.cliente.email if payload.cliente.email is not None else cliente.email

        fecha_pedido = datetime.now(timezone.utc)

        numero_pedido, codigo_pedido = generar_numeracion_pedido(
            db=db,
            empresa_id=int(payload.empresaID),
            sucursal_id=int(payload.sucursalID),
        )

        pedido = Pedido(
            empresaID=payload.empresaID,
            sucursalID=payload.sucursalID,
            numeroPedido=numero_pedido,
            codigoPedido=codigo_pedido,
            clienteID=cliente.idCliente,
            fechaPedido=fecha_pedido,
            fechaPedidoDate=fecha_pedido.date(),
            horaPedido=fecha_pedido.time().replace(microsecond=0),
            estadoPedidoID=estado_creado.idEstadoPedido,
            totalBruto=Decimal("0.00"),
            totalIva=Decimal("0.00"),
            totalNeto=Decimal("0.00"),
            createdAt=datetime.now(timezone.utc),
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
            sucursalID=payload.sucursalID,
            pedidoID=pedido.idPedido,
            estadoEntregaID=1,
            estado="Pendiente",
            tipoEntrega=payload.entrega.tipoEntrega,
            destinatario=payload.entrega.destinatario,
            telefonoDestino=payload.entrega.telefonoDestino,
            direccion=payload.entrega.direccion,
            barrioID=payload.entrega.barrioID,
            barrioNombre=payload.entrega.barrioNombre,
            rangoHora=payload.entrega.rangoHora,
            mensaje=payload.entrega.mensaje,
            firma=payload.entrega.firma,
            observacionGeneral=payload.entrega.observacionGeneral,
            fechaEntregaProgramada=payload.entrega.fechaEntrega,
            fechaEntrega=payload.entrega.fechaEntrega,
            intentoNumero=1,
            createdAt=datetime.now(timezone.utc),
        )
        db.add(entrega)

        db.commit()

        return {
            "pedidoID": pedido.idPedido,
            "numeroPedido": int(pedido.numeroPedido),
            "codigoPedido": str(pedido.codigoPedido),
            "total": float(pedido.totalNeto or 0),
            "estado": "CREADO",
        }

    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error registrando checkout: {exc}")
