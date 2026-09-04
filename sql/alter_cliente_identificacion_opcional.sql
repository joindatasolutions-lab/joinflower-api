-- Fix: no se podian crear/editar clientes sin numero de documento.
--
-- La columna cliente.identificacion era NOT NULL, pero el codigo (schema
-- Optional, frontend sin campo obligatorio, backend que convierte "" -> NULL)
-- ya trata el documento como opcional. Al guardar un cliente sin documento se
-- violaba la restriccion NOT NULL (error 500 NotNullViolation) en TODAS las
-- empresas cuyos usuarios registran clientes solo con nombre + telefono
-- (caso tipico de floristeria).
--
-- Se relaja la restriccion. El indice unico uk_cliente_empresa_identificacion
-- sigue evitando documentos reales duplicados por empresa: en Postgres los
-- valores NULL son distintos entre si, asi que varios clientes sin documento
-- conviven sin chocar, y el chequeo de duplicados del backend solo corre
-- cuando hay identificacion no vacia.

ALTER TABLE petalops.cliente
ALTER COLUMN identificacion DROP NOT NULL;
