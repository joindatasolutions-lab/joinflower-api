# Punto 12 — JWT: revalidacion en vivo + revocacion de token individual (implementado)

Relacionado con el punto 12 de [mejoras-arquitectura.md](./mejoras-arquitectura.md) ("JWT sin refresh token").

## Hallazgo: el riesgo principal ya estaba cubierto

Antes de escribir codigo se reviso `_build_auth_context` (`app/core/security.py`), que corre en **cada** request autenticado (no solo en login). Ya revalida en vivo contra la BD:

- `usuario.estado != 'ACTIVO'` -> 401 inmediato, sin importar que el JWT siga sin expirar.
- `is_empresa_activa(empresa.estado)` -> 403 inmediato si la empresa se desactiva.

Esto significa que el escenario que mas preocupaba al documento ("empleado despedido, cuenta comprometida") **ya se resuelve solo**: desactivar al usuario en BD corta su acceso en la siguiente request, no hay que esperar a que expire el token de 480 minutos.

## Lo que faltaba y se implemento: revocar UN token especifico

El caso que no cubria la revalidacion por `estado`: un token filtrado/robado mientras el usuario sigue siendo legitimo y debe seguir teniendo acceso desde otro dispositivo. Para eso no sirve desactivar la cuenta (bloquearia tambien el acceso legitimo). Se implemento una tabla de revocacion por token individual.

### Cambios

**Migracion** (`sql/alter_token_revocado.sql`, repo `joinflower-api/sql`, **ya ejecutada** contra dev):
```sql
CREATE TABLE petalops.token_revocado (
    jti VARCHAR(64) PRIMARY KEY,
    usuario_id BIGINT NOT NULL,
    revocado_en TIMESTAMP NOT NULL DEFAULT NOW(),
    expira_en TIMESTAMP NOT NULL
);
CREATE INDEX idx_token_revocado_expira ON petalops.token_revocado (expira_en);
```
Creacion de tabla nueva: cero riesgo para tablas existentes, se ejecuto de inmediato (no requiere ventana de mantenimiento).

**`app/core/security.py`**:
- `create_access_token` ahora incluye un claim `jti` (`secrets.token_hex(16)`, 32 caracteres hex) unico por token emitido.
- Nuevas funciones `is_token_revoked(db, jti)` y `revoke_token(db, jti=..., usuario_id=..., expira_en=...)`, con el mismo patron defensivo ya usado en `_mostrar_codigo_catalogo` (verifica si la tabla existe antes de consultarla; si no existe, se comporta como no-op seguro — permite desplegar este codigo antes de correr la migracion sin romper el login).
- `get_current_auth_context` ahora rechaza con 401 si el `jti` del token esta en la tabla de revocados, antes de construir el contexto de autenticacion.

**`app/routers/auth.py`**:
- Nuevo endpoint `POST /auth/logout`: decodifica el token actual, inserta su `jti` en `token_revocado`. A partir de ahi ese token especifico deja de servir, aunque no haya expirado — sin tocar la cuenta del usuario.

### Validado (con datos y usuario reales, no simulado)

1. Confirmado que sin la migracion aplicada, `is_token_revoked` siempre devuelve `False` y `revoke_token` no falla (no-op) — el codigo es seguro de desplegar en cualquier orden respecto a la migracion.
2. Migracion aplicada contra dev. Prueba directa de las funciones: token nuevo no revocado -> `revoke_token` -> mismo `jti` ahora revocado -> un `jti` distinto sigue libre (la revocacion es por token, no por usuario).
3. **Prueba end-to-end HTTP real**, con un usuario activo real de la BD (`emandados`, empresa 3):
   - `GET /auth/me` con token valido -> `200`.
   - `POST /auth/logout` -> `200 {"status": "ok"}`.
   - `GET /auth/me` con el **mismo token**, despues del logout -> `401 Token invalido o expirado`.
   - Se vio en el log de la request rechazada `empresa=3` (confirma de paso que el trabajo del punto 14 funciona en este flujo real tambien).
4. Se limpiaron todos los registros de prueba de `token_revocado` despues de validar (la tabla quedo vacia, lista para uso real).

## Que NO se implemento (fuera de alcance de esta fase)

- **Refresh tokens con rotacion**: seguiria siendo un cambio de flujo mas grande (el frontend tendria que manejar un segundo token y renovarlo). No se hizo porque el problema de seguridad real (revocar acceso) ya quedo resuelto con lo anterior; esto quedaria como mejora de UX de sesion, no de seguridad.
- **Limpieza automatica de `token_revocado`**: la tabla tiene un indice por `expira_en` preparado para poder borrar filas viejas (el token ya habria expirado de todas formas), pero no se agrego un job de limpieza automatico. A la escala actual (32 usuarios, logouts ocasionales) esto no es urgente; se puede agregar despues como un `DELETE WHERE expira_en < NOW()` periodico si la tabla crece.
- No se agrego un boton de "logout" en ningun frontend — el endpoint del backend esta listo, pero el frontend tendria que empezar a llamarlo al cerrar sesion (hoy probablemente solo borra el token del lado del cliente sin avisar al backend).
