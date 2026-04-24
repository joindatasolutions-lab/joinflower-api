BEGIN;

CREATE TABLE IF NOT EXISTS petalops.empresa_menu (
    id_empresa_menu BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL,
    codigo VARCHAR(80) NOT NULL,
    titulo VARCHAR(120) NOT NULL,
    seccion VARCHAR(80) NOT NULL DEFAULT 'pedido_detalle',
    tipo_control VARCHAR(40) NOT NULL,
    opciones_json JSONB NULL,
    requerido_aprobacion BOOLEAN NOT NULL DEFAULT FALSE,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    orden INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_empresa_menu_empresa_codigo_seccion
    ON petalops.empresa_menu (empresa_id, codigo, seccion);

INSERT INTO petalops.empresa_menu (
    empresa_id,
    codigo,
    titulo,
    seccion,
    tipo_control,
    opciones_json,
    requerido_aprobacion,
    activo,
    orden
)
VALUES
(
    3,
    'pedido_metodos_pago',
    'Métodos de pago',
    'pedido_detalle',
    'multi_select',
    '[
      "Cuenta por cobrar",
      "Efectivo",
      "Canje",
      "Contraentrega",
      "Cotizacion",
      "Obsequio",
      "Paypal",
      "Link bold",
      "Link payu",
      "Link wompi",
      "Datafono credibanco",
      "Datafono Bold",
      "Transferencia 0257",
      "Transferencia 0005",
      "Transferencia 3220",
      "Transferencia 4038",
      "Transferencia 4966",
      "Transferencia 3671",
      "Transferencia 6913",
      "Transferencia 5431",
      "Transferencia 1340",
      "Transferencia Jaque",
      "Transferencia QR",
      "Anulado"
    ]'::jsonb,
    TRUE,
    TRUE,
    10
),
(
    3,
    'pedido_canal_venta',
    'Celular Flora',
    'pedido_detalle',
    'select',
    '[
      "Huawei",
      "Samsung",
      "Andrea",
      "Página Web",
      "Presencial",
      "Rappi"
    ]'::jsonb,
    TRUE,
    TRUE,
    20
)
ON CONFLICT (empresa_id, codigo, seccion)
DO UPDATE SET
    titulo = EXCLUDED.titulo,
    tipo_control = EXCLUDED.tipo_control,
    opciones_json = EXCLUDED.opciones_json,
    requerido_aprobacion = EXCLUDED.requerido_aprobacion,
    activo = EXCLUDED.activo,
    orden = EXCLUDED.orden,
    updated_at = NOW();

COMMIT;
