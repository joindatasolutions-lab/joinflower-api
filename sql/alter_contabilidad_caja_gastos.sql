CREATE TABLE IF NOT EXISTS petalops.caja_gasto (
    id_caja_gasto BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL,
    sucursal_id BIGINT NOT NULL,
    fecha_operacion DATE NOT NULL,
    concepto VARCHAR(80) NOT NULL,
    descripcion VARCHAR(500),
    monto NUMERIC(14, 2) NOT NULL,
    usuario_id BIGINT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT caja_gasto_monto_positivo_ck CHECK (monto > 0),
    CONSTRAINT caja_gasto_empresa_fk FOREIGN KEY (empresa_id) REFERENCES petalops.empresa(id_empresa),
    CONSTRAINT caja_gasto_sucursal_fk FOREIGN KEY (sucursal_id) REFERENCES petalops.sucursal(id_sucursal),
    CONSTRAINT caja_gasto_usuario_fk FOREIGN KEY (usuario_id) REFERENCES petalops.usuario(id_usuario)
);

CREATE INDEX IF NOT EXISTS idx_caja_gasto_empresa_sucursal_fecha
    ON petalops.caja_gasto (empresa_id, sucursal_id, fecha_operacion DESC);

-- Conserva el total historico como un movimiento detallado sin inventar conceptos.
INSERT INTO petalops.caja_gasto (
    empresa_id, sucursal_id, fecha_operacion, concepto, descripcion, monto, usuario_id, created_at
)
SELECT
    c.empresa_id,
    c.sucursal_id,
    c.fecha,
    'Gasto historico',
    'Importado automaticamente desde el cierre consolidado.',
    c.gasto,
    c.usuario_id,
    COALESCE(c.created_at, CURRENT_TIMESTAMP)
FROM petalops.caja c
WHERE c.gasto > 0
  AND NOT EXISTS (
      SELECT 1
      FROM petalops.caja_gasto cg
      WHERE cg.empresa_id = c.empresa_id
        AND cg.sucursal_id = c.sucursal_id
        AND cg.fecha_operacion = c.fecha
  );
