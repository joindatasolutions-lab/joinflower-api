-- Correctivo: NO eliminar petalops.empleado.password_hash en produccion.
-- La autenticacion oficial usa petalops.usuario.passwordhash.
-- empleado.password_hash queda como columna legacy nullable para compatibilidad con versiones desplegadas.
-- Cuando todo el backend desplegado deje de mapear esta columna, se podra evaluar un DROP en una migracion futura.

-- Backfill defensivo: si existiera algun usuario sin hash y el empleado legacy lo tiene,
-- copiar el valor hacia usuario.passwordhash, que es la fuente oficial.
UPDATE petalops.usuario u
SET passwordhash = e.password_hash,
    updated_at = CURRENT_TIMESTAMP
FROM petalops.empleado e
WHERE e.usuario_id = u.id_usuario
  AND e.password_hash IS NOT NULL
  AND btrim(e.password_hash) <> ''
  AND (u.passwordhash IS NULL OR btrim(u.passwordhash) = '');