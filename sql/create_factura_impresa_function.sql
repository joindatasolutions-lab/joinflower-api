-- Apply before deploying the SQL-paginated pedidos endpoint.
-- raw_respuesta may contain legacy non-JSON payment responses.
CREATE OR REPLACE FUNCTION petalops.factura_impresa(raw_value text)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE value jsonb;
BEGIN
    value := raw_value::jsonb #> '{_petalopsMetadata,facturaImpresa}';
    IF value IS NULL OR value = 'null'::jsonb THEN RETURN false; END IF;
    CASE jsonb_typeof(value)
      WHEN 'boolean' THEN RETURN value = 'true'::jsonb;
      WHEN 'number' THEN RETURN (value::text)::numeric <> 0;
      WHEN 'string' THEN RETURN value <> '""'::jsonb;
      WHEN 'array' THEN RETURN value <> '[]'::jsonb;
      WHEN 'object' THEN RETURN value <> '{}'::jsonb;
      ELSE RETURN false;
    END CASE;
EXCEPTION WHEN invalid_text_representation THEN
    RETURN false;
END;
$$;
