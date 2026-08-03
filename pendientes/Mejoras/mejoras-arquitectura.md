ad 100 floristerias · MD
Análisis de escalabilidad — PetalOps para 100 floristerías
Resumen ejecutivo

El sistema tiene una base multitenant sólida y bien pensada, pero presenta falencias concretas en infraestructura, seguridad, deuda técnica de código y arquitectura que deben resolverse antes de escalar a 100 tenants simultáneos. Se clasifican en críticos (bloquean el escalado), importantes (degradan la experiencia) y mejoras (deuda que crece con cada tenant nuevo).

🔴 CRÍTICOS — bloquean el escalado
1. Pool de conexiones insuficiente

Archivo: app/database.py

python
DB_POOL_SIZE = max(1, int(os.getenv("DB_POOL_SIZE", "3")))
DB_MAX_OVERFLOW = max(0, int(os.getenv("DB_MAX_OVERFLOW", "2")))

Con 100 floristerías operando concurrentemente, el pool de 3 conexiones base + 2 overflow = 5 conexiones máximas por instancia. Con picos de tráfico por floristería (apertura de jornada, pedidos matutinos), esto genera colas de espera y timeouts en cascada.

Fix: Aumentar a DB_POOL_SIZE=20, DB_MAX_OVERFLOW=10 como mínimo. Evaluar PgBouncer en modo transaction para conexiones reales a PostgreSQL.

2. Caché en memoria — no funciona con múltiples instancias

Archivo: app/services/cache.py

python
_MEMORY_CACHE: dict[str, tuple[float, str]] = {}

El caché es un diccionario Python en memoria del proceso. Con Cloud Run (múltiples instancias), cada instancia tiene su propio caché aislado. Resultado: invalidaciones no se propagan, datos inconsistentes entre instancias, y el caché es inútil como protección real contra carga en BD.

Fix: Reemplazar por Redis (Cloud Memorystore) o al menos aceptar que el caché actual solo funciona en instancia única y documentarlo explícitamente.

3. Rate limiting en memoria — no distribuido

Archivo: app/middlewares/rate_limit.py

python
limiter = Limiter(key_func=get_remote_address)

SlowAPI con almacenamiento en memoria local. Con múltiples instancias en Cloud Run, una IP puede hacer N_instancias × límite requests antes de ser bloqueada. El rate limiting actual no protege nada en producción multi-instancia.

Fix: Configurar SlowAPI con backend Redis: Limiter(key_func=get_remote_address, storage_uri="redis://...").

4. Lógica hardcodeada para empresa específica (Flora = empresa 3)

Archivo: app/routers/pedido.py

python
FLORA_EMPRESA_ID = 3

if int(empresa_id) == FLORA_EMPRESA_ID:
    ...  # comportamiento especial en PDFs, métodos de pago, subtítulo

Hay al menos 3 puntos en el router de pedidos donde el comportamiento cambia si empresa_id == 3. Esto significa que la empresa 3 tiene funcionalidades que las otras 99 no pueden activar, y que agregar comportamientos similares para otras empresas requiere modificar código. No es escalable como modelo.

Fix: Mover estas configuraciones a empresa_menu o a campos de configuración por empresa en BD. La configuración de métodos de pago (FLORA_PAYMENT_METHODS) debería venir de metodo_pago_catalogo.

5. CORS hardcodeado con dominios de clientes específicos

Archivo: app/main.py

python
ALLOWED_ORIGINS = [
    "https://petalops.joindata.com.co",
    "https://domiapp.joindata.com.co",
    ...
]

Con 100 floristerías cada una con su dominio propio, esta lista requiere un deploy por cada floristería nueva. La variable ALLOWED_ORIGINS del entorno es la válvula de escape, pero requiere reinicio del servicio.

Fix: Gestionar CORS dinámicamente desde BD (tabla empresa con campo dominio) o usar un wildcard controlado para subdominios propios (*.joindata.com.co).

6. Deuda ORM — modelos desincronizados con la BD real

Archivo: docs/deuda_tecnica_modelos_orm_desincronizados.md (ya documentado internamente)

Modelos con columnas que no existen en la BD real:

Categoria — columnas completamente distintas
TransicionEstadoPedido — nombre de tabla en PascalCase, BD en snake_case
Empleado — redundante y roto (tabla cubierta por Domiciliario/Florista)
SucursalContadorPedido — tabla que no existe en BD
PlanModulo — columna empresa_id que no existe en la tabla

Si alguien usa cualquiera de estos modelos con ORM (sin SQL crudo), cae toda la plataforma para los 100 tenants a la vez.

Fix por prioridad:

Borrar empleado.py (ya cubierto por otros modelos)
Corregir categoria.py (mayor riesgo si se activa la relación)
Limpiar TransicionEstadoPedido (import muerto)
Decidir sobre SucursalContadorPedido y Zona
🟡 IMPORTANTES — degradan la experiencia a escala
7. Sin sistema de migraciones (Alembic)

No existe Alembic ni ningún sistema de migraciones automatizado. Los cambios de esquema se manejan con archivos SQL sueltos en /sql/ que se ejecutan manualmente. Con 100 tenants compartiendo la misma BD, una migración mal ejecutada o a medias afecta a todos simultáneamente, y no hay forma de rollback automatizado.

Fix: Integrar Alembic. Generar el estado inicial desde el SCHEMA actual y migrar los archivos SQL sueltos a versiones Alembic.

8. Sin versiones en la API

Todos los endpoints son /pedidos, /auth/login, etc. sin prefijo de versión. Si se necesita cambiar un contrato de API (añadir campo obligatorio, cambiar formato de respuesta), no hay forma de hacerlo sin romper clientes existentes.

Fix: Agregar prefijo /v1/ a todos los routers. Costo bajo ahora, altísimo cuando hay 100 clientes activos.

9. Sin paginación consistente en todos los endpoints

El endpoint de pedidos tiene paginación (page, pageSize, máximo 300). Pero endpoints de catálogo, barrios, empleados, domiciliarios, clientes, inventario devuelven listas completas sin límite. Con 100 floristerías, una floristería con 10.000 clientes puede hacer un request a /clientes y devolver 10.000 registros de una sola vez.

Fix: Agregar paginación obligatoria con límite máximo a todos los endpoints de lista.

10. tenantConfig hardcodeado en el frontend

Archivo: src/config/tenantConfig.js

javascript
export const tenantConfig = {
  empresaId: 1,
  sucursalId: 1,
  apiBaseUrl,
};

empresaId: 1 y sucursalId: 1 están fijos en el código fuente del frontend. El frontend actual es una SPA single-tenant. Para 100 floristerías se necesita o un build por floristería (inmanejable) o que estos valores vengan del token JWT post-login (que el backend ya provee).

Fix: El frontend ya recibe empresaID y sucursalID en el JWT al hacer login. Reemplazar tenantConfig.empresaId por los valores del token, eliminando el hardcoding.

11. Módulos sin fuente canónica única

Archivo: pendientes/001-normalizacion-modulos-permisos.md (ya documentado)

Los módulos activos se calculan desde DEFAULT_MODULES (lista hardcodeada en security.py), plan_modulo, empresa_modulo, permiso_modulo y usuario_modulo. Con 100 empresas cada una con planes diferentes, esta lógica de composición es difícil de auditar y depurar.

Fix: Implementar el modelo propuesto en el pendiente 001: tabla modulo como fuente canónica, y flujo de resolución lineal y auditable.

12. JWT sin refresh token — expiración de 480 minutos

Archivo: app/core/security.py

python
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))

8 horas de expiración sin refresh token. Si se necesita revocar el acceso de un usuario (empleado despedido, cuenta comprometida), no hay mecanismo de invalidación — el token sigue válido hasta expirar. Con 100 empresas esto es un riesgo de seguridad real.

Fix: Implementar refresh tokens con rotación, o una tabla de tokens revocados (blacklist) con TTL igual al tiempo de expiración.

13. Contraseñas en texto plano como fallback

Archivo: app/core/security.py

python
# Transitional fallback for legacy records with plain passwords.
return plain_password == password_hash

Hay un path de código que compara contraseñas en texto plano. Aunque es "transitional", si existe en producción con 100 tenants hay cuentas con contraseñas sin hashear.

Fix: Eliminar este fallback. Forzar reset de contraseña para cuentas legacy o hashearlas en una migración de datos.

🔵 MEJORAS — deuda que crece con cada tenant
14. Sin observabilidad/trazabilidad de errores por tenant

Los logs actuales tienen request_id (middleware RequestContextMiddleware), pero no incluyen empresa_id ni tenant en el contexto de log. Si hay un error en producción, no hay forma rápida de saber qué empresa lo está experimentando sin revisar el payload del JWT o los parámetros de cada request.

Fix: Agregar empresa_id al contexto de log en el middleware de autenticación.

15. Job de auto-asignación de producción — instancia única

Archivo: app/jobs/produccion_autoassign_job.py

El job corre dentro del proceso FastAPI. Con múltiples instancias Cloud Run, el job corre en paralelo en cada instancia y puede generar asignaciones duplicadas o condiciones de carrera.

Fix: Mover a Cloud Scheduler + endpoint protegido, o usar un lock distribuido (Redis) para garantizar ejecución única.

16. Sin índices documentados para queries frecuentes

Con 100 floristerías el volumen de pedidos crece 100x. Las queries más frecuentes (/pedidos?empresaID=X&fechaDesde=Y&fechaHasta=Z) necesitan índices compuestos sobre (empresa_id, fecha_pedido), (empresa_id, sucursal_id, estado_pedido_id). No hay evidencia de estos índices en los SQL de migración.

Fix: Revisar y agregar índices compuestos en las tablas de mayor volumen: pedido, entrega, produccion, movimiento_inventario.

17. domicilios router registrado dos veces

Archivo: app/main.py

python
app.include_router(domicilios.router)
app.include_router(domicilios.router, prefix="/api")

El mismo router está registrado dos veces. Esto duplica las rutas en /docs, puede generar conflictos y es indicativo de deuda de compatibilidad con el cliente móvil (/api/domicilios).

Fix: Definir una sola URL canónica y deprecar la alternativa con una redirección temporal.

18. Sin estrategia de backup ni retención de auditoría

Las tablas pedido_auditoria, domicilio_auditoria y usuario_auditoria no tienen política de retención ni archivado. Con 100 floristerías y operación diaria, estas tablas crecerán a millones de registros en meses, sin ningún plan de limpieza.

Fix: Definir política de retención (ej: 90 días online, archivado a cold storage) e implementar job de limpieza periódica.

Resumen de prioridades
#	Falencia	Severidad	Esfuerzo
1	Pool de conexiones insuficiente	🔴 Crítico	Bajo
2	Caché en memoria (no distribuido)	🔴 Crítico	Medio
3	Rate limiting no distribuido	🔴 Crítico	Bajo
4	Lógica hardcodeada empresa Flora (id=3)	🔴 Crítico	Medio
5	CORS hardcodeado por cliente	🔴 Crítico	Bajo
6	Modelos ORM desincronizados	🔴 Crítico	Medio
7	Sin migraciones (Alembic)	🟡 Importante	Alto
8	Sin versiones en API	🟡 Importante	Bajo
9	Sin paginación en todos los endpoints	🟡 Importante	Medio
10	tenantConfig hardcodeado en frontend	🟡 Importante	Bajo
11	Módulos sin fuente canónica	🟡 Importante	Alto
12	JWT sin refresh / revocación	🟡 Importante	Medio
13	Contraseñas en texto plano (fallback)	🟡 Importante	Bajo
14	Sin tenant_id en logs	🔵 Mejora	Bajo
15	Job de producción en instancia múltiple	🔵 Mejora	Medio
16	Sin índices para queries de alto volumen	🔵 Mejora	Bajo
17	Router domicilios duplicado	🔵 Mejora	Bajo
18	Sin retención de tablas de auditoría	🔵 Mejora	Medio