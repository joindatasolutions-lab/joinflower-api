-- Reconstruye vista tipo REGISTRO desde tablas normalizadas.
-- Ajusta @empresa_id segun la empresa que quieras consultar.

USE joindata_app;

SET @empresa_id := 3;

SELECT
    p.idPedido AS PedidoID,
    p.fechaPedido AS Fecha,
    c.identificacion AS Identificacion,
    c.nombreCompleto AS Cliente,
    c.telefono AS Telefono,
    COALESCE(pg.proveedor, '') AS FormaPago,
    e.destinatario AS Destinatario,
    e.barrioNombre AS Barrio,
    e.direccion AS Direccion,
    e.telefonoDestino AS telefonoDestino,
    e.fechaEntrega AS `Fecha de Entrega`,
    e.fechaEntrega AS `Hora de Entrega`,
    GROUP_CONCAT(
        CONCAT(
            CASE
                WHEN MOD(pd.cantidad, 1) = 0 THEN CAST(CAST(pd.cantidad AS UNSIGNED) AS CHAR)
                ELSE CAST(pd.cantidad AS CHAR)
            END,
            'x ',
            pr.nombreProducto
        )
        ORDER BY pd.idPedidoDetalle
        SEPARATOR ' | '
    ) AS Producto,
    SUM(pd.cantidad) AS Cantidad,
    p.totalBruto AS Precio,
    p.totalIva AS Iva,
    CASE
        WHEN LOWER(TRIM(COALESCE(e.tipoEntrega, ''))) = 'recoger en tienda' THEN 0
        ELSE COALESCE(b.costoDomicilio, 0)
    END AS Domicilio,
    p.totalNeto AS Total,
    e.mensaje AS Mensaje,
    ep.nombreEstado AS Estado,
    COALESCE(pg.referencia, '') AS Cuenta,
    CASE WHEN COALESCE(TRIM(e.firma), '') <> '' THEN 'SI' ELSE 'NO' END AS Firmado,
    COALESCE(e.firma, '') AS NombreFirma,
    '' AS `Celular Flora`,
    COALESCE(e.observacionGeneral, '') AS Observaciones,
    COALESCE(pg.checkoutUrl, '') AS FacturaURL,
    COALESCE(e.updatedAt, p.updatedAt, p.createdAt) AS LastModified,
    p.idPedido AS Pedido
FROM Pedido p
JOIN Cliente c
    ON c.idCliente = p.clienteID
LEFT JOIN Entrega e
    ON e.pedidoID = p.idPedido
   AND e.empresaID = p.empresaID
LEFT JOIN Barrio b
    ON b.idBarrio = e.barrioID
   AND b.empresaID = p.empresaID
LEFT JOIN EstadoPedido ep
    ON ep.idEstadoPedido = p.estadoPedidoID
LEFT JOIN (
    SELECT x.pedidoID, x.proveedor, x.referencia, x.checkoutUrl
    FROM Pago x
    INNER JOIN (
        SELECT pedidoID, MAX(idPago) AS idPago
        FROM Pago
        GROUP BY pedidoID
    ) u ON u.idPago = x.idPago
) pg ON pg.pedidoID = p.idPedido
LEFT JOIN PedidoDetalle pd
    ON pd.pedidoID = p.idPedido
   AND pd.empresaID = p.empresaID
LEFT JOIN Producto pr
    ON pr.idProducto = pd.productoID
WHERE p.empresaID = @empresa_id
GROUP BY
    p.idPedido,
    p.fechaPedido,
    c.identificacion,
    c.nombreCompleto,
    c.telefono,
    pg.proveedor,
    e.destinatario,
    e.barrioNombre,
    e.direccion,
    e.telefonoDestino,
    e.fechaEntrega,
    p.totalBruto,
    p.totalIva,
    p.totalNeto,
    e.tipoEntrega,
    b.costoDomicilio,
    e.mensaje,
    ep.nombreEstado,
    pg.referencia,
    e.firma,
    e.observacionGeneral,
    pg.checkoutUrl,
    e.updatedAt,
    p.updatedAt,
    p.createdAt
ORDER BY p.fechaPedido DESC;
