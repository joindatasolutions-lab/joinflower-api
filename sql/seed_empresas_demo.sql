-- Seed rapido de empresas para pruebas multi-tenant
-- Ejecutar sobre la base activa (ejemplo: joindata_app)
-- Nota: usa IDs explicitos para facilitar pruebas y filtros.

-- Variante principal (schema con nombreComercial, planID, estado)
INSERT INTO Empresa (idEmpresa, nombreComercial, planID, estado)
VALUES
  (2, 'Rosa Norte', 1, 'Activo'),
  (3, 'Flora Express', 2, 'Activo'),
  (4, 'Garden Elite', 3, 'Inactivo')
ON DUPLICATE KEY UPDATE
  nombreComercial = VALUES(nombreComercial),
  planID = VALUES(planID),
  estado = VALUES(estado);

-- Si tu tabla Empresa solo tiene idEmpresa (schema minimo), usa esta variante:
-- INSERT INTO Empresa (idEmpresa)
-- VALUES (2), (3), (4)
-- ON DUPLICATE KEY UPDATE idEmpresa = VALUES(idEmpresa);
