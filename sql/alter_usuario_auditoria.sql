-- Auditoria de cambios de seguridad en usuarios

CREATE TABLE IF NOT EXISTS "UsuarioAuditoria" (
  "idAudit" BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  "empresaID" BIGINT NOT NULL,
  "actorUserID" BIGINT NOT NULL,
  "actorLogin" VARCHAR(80) NOT NULL,
  "accion" VARCHAR(60) NOT NULL,
  "targetUserID" BIGINT NOT NULL,
  "targetLogin" VARCHAR(80) NOT NULL,
  "detalleJSON" TEXT,
  "createdAt" TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_empresa_fecha ON "UsuarioAuditoria" ("empresaID", "createdAt");
CREATE INDEX IF NOT EXISTS idx_audit_target_fecha ON "UsuarioAuditoria" ("targetUserID", "createdAt");
