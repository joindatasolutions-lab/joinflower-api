# Punto 17 — router de domicilios duplicado (resuelto, con riesgo de deploy pendiente)

Relacionado con el punto 17 de [mejoras-arquitectura.md](./mejoras-arquitectura.md).

## Que habia y por que existia

`app/main.py` registraba el mismo router de domicilios dos veces:
```python
app.include_router(domicilios.router)              # /domicilios/...
app.include_router(domicilios.router, prefix="/api")  # /api/domicilios/... (mismo codigo)
```

Se valido con logs reales de Cloud Run (solo lectura, ultimos 30 dias) que **ambas rutas tenian trafico activo real**, de dos clientes distintos:

- `/domicilios/*` (sin prefijo): usado por el frontend web `Petalops_Modulos-main` (confirmado leyendo `src/infrastructure/apiClient.js`).
- `/api/domicilios/*`: trafico activo y reciente con el patron tipico de una app movil de domiciliarios (ej. `GET /api/domicilios/pedidos/disponibles`, `POST /api/domicilios/pedidos/{id}/asignar`, `GET /api/domicilios/contadores`) — casi seguro la app "DomiApp" (el dominio `domiapp.joindata.com.co` ya esta en la lista de CORS permitidos).

## Decision tomada

El usuario decidio explicitamente remover `/api/domicilios` ahora, aceptando el riesgo: **no se tiene acceso al codigo de la app movil DomiApp en esta sesion** para actualizarla primero a usar `/domicilios` sin prefijo. Se elimino el registro duplicado en `app/main.py`.

## Por que esto NO rompe nada hoy

Se confirmo que este repositorio no tiene un pipeline de auto-deploy a Cloud Run (`.github/workflows/` solo corre `ci-pytest.yml`, ningun workflow de deploy). El deploy a produccion es manual y separado. **Este cambio de codigo, mientras no se despliegue, no afecta a nadie.**

## RIESGO REAL al momento del proximo deploy manual

Si esta rama se despliega a Cloud Run **sin antes actualizar la app movil DomiApp** para que llame a `/domicilios` (sin prefijo) en vez de `/api/domicilios`, **todos los repartidores van a recibir 404 en cada llamada** de la app (ver pedidos disponibles, asignar pedidos, contadores) desde el instante del deploy.

**Antes de desplegar esta rama a produccion, se debe:**
1. Confirmar si existe codigo de DomiApp y donde esta.
2. Actualizar sus llamadas de `/api/domicilios/...` a `/domicilios/...`.
3. Publicar y esperar que los domiciliarios actualicen la app (o forzar actualizacion segun el mecanismo de distribucion que tenga esa app).
4. Solo despues, desplegar este cambio del backend con confianza.

Si eso no se puede confirmar antes del proximo deploy, la alternativa segura es revertir este commit especifico (o volver a agregar la linea `app.include_router(domicilios.router, prefix="/api")`) antes de desplegar, y resolver esto en un cambio separado y coordinado.

## Validado

- Sintaxis OK, `app.main` importa sin errores.
- Se conto rutas registradas en la app: `/api/domicilios` = 0 (eliminado correctamente), `/domicilios` = 21 (intacto, el frontend web no se ve afectado).
