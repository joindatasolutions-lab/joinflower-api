-- Override de modulos por usuario (subset de acceso efectivo por rol/plan)

CREATE TABLE IF NOT EXISTS UsuarioModulo (
  userID BIGINT NOT NULL,
  modulo VARCHAR(80) NOT NULL,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  updatedAt DATETIME NOT NULL,
  PRIMARY KEY (userID, modulo),
  INDEX idx_usuariomodulo_activo (userID, activo),
  CONSTRAINT fk_usuariomodulo_usuario FOREIGN KEY (userID) REFERENCES Usuario(idUsuario)
);
