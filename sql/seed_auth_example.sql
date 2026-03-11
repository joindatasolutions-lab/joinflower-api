-- Datos de ejemplo para arranque de autenticación multi-tenant.
-- Ajusta IDs y hashes antes de usar en producción.

-- Plan 1 (Básico): pedidos y producción
INSERT INTO PlanModulo (planID, modulo, activo) VALUES
(1, 'pedidos', 1),
(1, 'produccion', 1),
(1, 'domicilios', 1),
(1, 'catalogo', 1)
ON DUPLICATE KEY UPDATE activo = VALUES(activo);

-- Rol Admin para empresa 1
INSERT INTO Rol (idRol, empresaID, nombreRol)
VALUES (1, 1, 'Admin')
ON DUPLICATE KEY UPDATE nombreRol = VALUES(nombreRol);

-- Permisos completos para Admin
INSERT INTO PermisoModulo (rolID, modulo, puedeVer, puedeCrear, puedeEditar, puedeEliminar) VALUES
(1, 'pedidos', 1, 1, 1, 1),
(1, 'produccion', 1, 1, 1, 1),
(1, 'domicilios', 1, 1, 1, 1),
(1, 'catalogo', 1, 1, 1, 1)
ON DUPLICATE KEY UPDATE
  puedeVer = VALUES(puedeVer),
  puedeCrear = VALUES(puedeCrear),
  puedeEditar = VALUES(puedeEditar),
  puedeEliminar = VALUES(puedeEliminar);

-- Usuario demo (password hash de ejemplo, reemplazar por hash real bcrypt)
INSERT INTO Usuario (idUsuario, empresaID, sucursalID, nombre, login, email, passwordHash, rolID, estado, createdAt)
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
  NOW()
)
ON DUPLICATE KEY UPDATE
  nombre = VALUES(nombre),
  rolID = VALUES(rolID),
  estado = VALUES(estado);
