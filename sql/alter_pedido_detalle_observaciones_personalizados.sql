ALTER TABLE petalops.pedido_detalle
ADD COLUMN IF NOT EXISTS observaciones_personalizados TEXT NULL;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'petalops'
      AND table_name = 'pedido_detalle'
      AND column_name = 'observaciones'
  ) THEN
    EXECUTE '
      UPDATE petalops.pedido_detalle
      SET observaciones_personalizados = COALESCE(observaciones_personalizados, observaciones)
      WHERE observaciones IS NOT NULL
    ';
  END IF;
END $$;
