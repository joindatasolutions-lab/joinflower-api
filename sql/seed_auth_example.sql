-- Datos de ejemplo para arranque de autenticación multi-tenant.
-- Ajusta IDs y hashes antes de usar en producción.

-- Plan 1 (Básico): pedidos y producción
INSERT INTO "PlanModulo" ("planID", "modulo", "activo") VALUES
(1, 'pedidos', TRUE),
(1, 'produccion', TRUE),
(1, 'domicilios', TRUE),
(1, 'catalogo', TRUE)
ON CONFLICT ("planID", "modulo") DO UPDATE SET "activo" = EXCLUDED."activo";

-- Rol Admin para empresa 1
INSERT INTO "Rol" ("idRol", "empresaID", "nombreRol")
VALUES (1, 1, 'Admin')
ON CONFLICT ("idRol") DO UPDATE SET "nombreRol" = EXCLUDED."nombreRol";

-- Permisos completos para Admin
INSERT INTO "PermisoModulo" ("rolID", "modulo", "puedeVer", "puedeCrear", "puedeEditar", "puedeEliminar") VALUES
(1, 'pedidos', TRUE, TRUE, TRUE, TRUE),
(1, 'produccion', TRUE, TRUE, TRUE, TRUE),
(1, 'domicilios', TRUE, TRUE, TRUE, TRUE),
(1, 'catalogo', TRUE, TRUE, TRUE, TRUE)
ON CONFLICT ("rolID", "modulo") DO UPDATE SET
  "puedeVer" = EXCLUDED."puedeVer",
  "puedeCrear" = EXCLUDED."puedeCrear",
  "puedeEditar" = EXCLUDED."puedeEditar",
  "puedeEliminar" = EXCLUDED."puedeEliminar";

-- Usuario demo (password hash de ejemplo, reemplazar por hash real bcrypt)
INSERT INTO "Usuario" ("idusuario", "empresaID", "sucursalID", "nombre", "login", "email", "passwordHash", "rolID", "estado", "createdAt")
VALUES (
  1,
  1,
  1,
  'Admin Demo',
  'joinadmin',
  'admin@empresa1.com',
  '$2b$12$7fQj9M6f7mS8gI4wJk1B9OwD2yxm3Y0w9.sW2xU4kmv7mpI0rTQ9u',
  1,
  'Activo',
  CURRENT_TIMESTAMP
)
ON CONFLICT ("idusuario") DO UPDATE SET
  "nombre" = EXCLUDED."nombre",
  "rolID" = EXCLUDED."rolID",
  "estado" = EXCLUDED."estado";
