-- Indice para resolver estados asincronos de Meta por wamid/meta_message_id.
-- No altera datos existentes.
CREATE INDEX IF NOT EXISTS idx_whatsapp_notificacion_meta_message_id
ON petalops.whatsapp_notificacion (meta_message_id)
WHERE meta_message_id IS NOT NULL;
