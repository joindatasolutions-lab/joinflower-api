BEGIN;

CREATE TABLE IF NOT EXISTS petalops.metodo_pago_catalogo (
    id_metodo_pago BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL,
    codigo VARCHAR(80) NOT NULL,
    nombre VARCHAR(120) NOT NULL,
    orden INTEGER NOT NULL DEFAULT 0,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_metodo_pago_catalogo_empresa_codigo
    ON petalops.metodo_pago_catalogo (empresa_id, codigo);

CREATE UNIQUE INDEX IF NOT EXISTS ux_metodo_pago_catalogo_empresa_nombre
    ON petalops.metodo_pago_catalogo (empresa_id, nombre);

CREATE TABLE IF NOT EXISTS petalops.pago_metodo (
    id_pago_metodo BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL,
    pago_id BIGINT NOT NULL REFERENCES petalops.pago(id_pago) ON DELETE CASCADE,
    pedido_id BIGINT NOT NULL REFERENCES petalops.pedido(id_pedido) ON DELETE CASCADE,
    metodo_pago_id BIGINT NOT NULL REFERENCES petalops.metodo_pago_catalogo(id_metodo_pago),
    monto NUMERIC NOT NULL DEFAULT 0,
    orden INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NULL
);

ALTER TABLE petalops.pago_metodo
    ADD COLUMN IF NOT EXISTS monto NUMERIC NOT NULL DEFAULT 0;

CREATE UNIQUE INDEX IF NOT EXISTS ux_pago_metodo_empresa_pedido_metodo
    ON petalops.pago_metodo (empresa_id, pedido_id, metodo_pago_id);

CREATE INDEX IF NOT EXISTS ix_pago_metodo_empresa_pedido
    ON petalops.pago_metodo (empresa_id, pedido_id);

CREATE TABLE IF NOT EXISTS petalops.canal_venta (
    id_canal_venta BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL,
    codigo VARCHAR(80) NOT NULL,
    nombre VARCHAR(120) NOT NULL,
    orden INTEGER NOT NULL DEFAULT 0,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_canal_venta_empresa_codigo
    ON petalops.canal_venta (empresa_id, codigo);

CREATE UNIQUE INDEX IF NOT EXISTS ux_canal_venta_empresa_nombre
    ON petalops.canal_venta (empresa_id, nombre);

CREATE TABLE IF NOT EXISTS petalops.pedido_canal_venta (
    id_pedido_canal_venta BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL,
    pedido_id BIGINT NOT NULL REFERENCES petalops.pedido(id_pedido) ON DELETE CASCADE,
    canal_venta_id BIGINT NOT NULL REFERENCES petalops.canal_venta(id_canal_venta),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_pedido_canal_venta_empresa_pedido
    ON petalops.pedido_canal_venta (empresa_id, pedido_id);

INSERT INTO petalops.metodo_pago_catalogo (empresa_id, codigo, nombre, orden, activo)
VALUES
    (3, 'cuenta_por_cobrar', 'Cuenta por cobrar', 1, TRUE),
    (3, 'efectivo', 'Efectivo', 2, TRUE),
    (3, 'canje', 'Canje', 3, TRUE),
    (3, 'contraentrega', 'Contraentrega', 4, TRUE),
    (3, 'cotizacion', 'Cotizacion', 5, TRUE),
    (3, 'obsequio', 'Obsequio', 6, TRUE),
    (3, 'paypal', 'Paypal', 7, TRUE),
    (3, 'link_bold', 'Link bold', 8, TRUE),
    (3, 'link_payu', 'Link payu', 9, TRUE),
    (3, 'link_wompi', 'Link wompi', 10, TRUE),
    (3, 'datafono_credibanco', 'Datafono credibanco', 11, TRUE),
    (3, 'datafono_bold', 'Datafono Bold', 12, TRUE),
    (3, 'transferencia_0257', 'Transferencia 0257', 13, TRUE),
    (3, 'transferencia_0005', 'Transferencia 0005', 14, TRUE),
    (3, 'transferencia_3220', 'Transferencia 3220', 15, TRUE),
    (3, 'transferencia_4038', 'Transferencia 4038', 16, TRUE),
    (3, 'transferencia_4966', 'Transferencia 4966', 17, TRUE),
    (3, 'transferencia_3671', 'Transferencia 3671', 18, TRUE),
    (3, 'transferencia_6913', 'Transferencia 6913', 19, TRUE),
    (3, 'transferencia_5431', 'Transferencia 5431', 20, TRUE),
    (3, 'transferencia_1340', 'Transferencia 1340', 21, TRUE),
    (3, 'transferencia_jaque', 'Transferencia Jaque', 22, TRUE),
    (3, 'transferencia_qr', 'Transferencia QR', 23, TRUE),
    (3, 'anulado', 'Anulado', 24, TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO petalops.canal_venta (empresa_id, codigo, nombre, orden, activo)
VALUES
    (3, 'huawei', 'Huawei', 1, TRUE),
    (3, 'samsung', 'Samsung', 2, TRUE),
    (3, 'andrea', 'Andrea', 3, TRUE),
    (3, 'pagina_web', 'Página Web', 4, TRUE),
    (3, 'presencial', 'Presencial', 5, TRUE),
    (3, 'rappi', 'Rappi', 6, TRUE)
ON CONFLICT DO NOTHING;

COMMIT;
