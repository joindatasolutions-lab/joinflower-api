-- Auditoria de cambios de seguridad en usuarios

CREATE TABLE IF NOT EXISTS UsuarioAuditoria (
  idAudit BIGINT PRIMARY KEY AUTO_INCREMENT,
  empresaID BIGINT NOT NULL,
  actorUserID BIGINT NOT NULL,
  actorLogin VARCHAR(80) NOT NULL,
  accion VARCHAR(60) NOT NULL,
  targetUserID BIGINT NOT NULL,
  targetLogin VARCHAR(80) NOT NULL,
  detalleJSON TEXT NULL,
  createdAt DATETIME NOT NULL,
  INDEX idx_audit_empresa_fecha (empresaID, createdAt),
  INDEX idx_audit_target_fecha (targetUserID, createdAt)
);
