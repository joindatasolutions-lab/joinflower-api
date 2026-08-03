# CRITICO — JWT_SECRET no configurado en produccion (pendiente de aplicar)

**Estado: NO RESUELTO A PROPOSITO.** Se decidio posponer la rotacion porque las floristerias estaban trabajando activamente al momento del hallazgo (2026-08-03) y rotar el secreto invalida todas las sesiones activas de inmediato. Aplicar en cuanto haya una ventana de mantenimiento (fuera de horario operativo).

Relacionado con el punto 12 de [mejoras-arquitectura.md](./mejoras-arquitectura.md) ("JWT sin refresh token"), encontrado al revisar ese punto.

## El problema

`app/core/security.py:20`:
```python
JWT_SECRET = os.getenv("JWT_SECRET", "dev-change-this-secret")
```

Se verifico (solo lectura, gcloud, sin exponer valores) que el servicio `join-flower` en Cloud Run (proyecto `flora-471805`, region `us-central1`, revision activa `join-flower-00207-6t7`, 100% del trafico) **no tiene ni `JWT_SECRET` ni `JWT_SECRET_KEY` configurados**. Las unicas env vars del servicio son: `INSTANCE_CONNECTION_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE`, `TEXMEBOT_ENABLED`, `TEXMEBOT_API_KEY`.

**Consecuencia:** produccion esta firmando y validando todos los JWT con el valor por defecto hardcodeado en el codigo fuente (`"dev-change-this-secret"`), visible para cualquiera con acceso de lectura al repositorio. Cualquiera que conozca ese valor puede firmar un JWT valido para cualquier usuario y cualquier rol, incluyendo super admin (`esGlobalJoin=true`), sin ninguna credencial real — acceso completo a las 4 empresas.

## Causa raiz

`.env.example` documentaba la variable como `JWT_SECRET_KEY`, pero el codigo real lee `JWT_SECRET` (nombres distintos). Quien configuro Cloud Run probablemente siguio el `.env.example` y configuro el nombre equivocado, o simplemente nunca se configuro. **Ya corregido** en `.env.example` (este commit) para que diga `JWT_SECRET`.

## Que falta hacer (accion sobre infraestructura, requiere ventana sin usuarios activos)

Correr, en una terminal con `gcloud` autenticado contra el proyecto `flora-471805`:

```bash
JWT_SECRET_NEW=$(python -c "import secrets; print(secrets.token_urlsafe(64))")

gcloud run services update join-flower \
  --project=flora-471805 \
  --region=us-central1 \
  --update-env-vars="JWT_SECRET=${JWT_SECRET_NEW}"
```

**Efecto esperado, no un bug:** todas las sesiones activas quedan invalidadas de inmediato — todos los usuarios logueados (de las 4 empresas) tienen que volver a iniciar sesion. Por eso se pospuso: hacerlo en horario operativo interrumpe a las floristerias trabajando.

**Recomendacion:** aplicar fuera de horario (ej. de madrugada o en un momento de bajo trafico), avisando de antemano que todos deberan volver a loguearse.

## Notas

- No se modifico nada en Cloud Run. El unico cambio aplicado fue el nombre de la variable en `.env.example` (repo, sin efecto en produccion).
- Se intento aplicar la rotacion directamente vía `gcloud run services update`, pero fue bloqueada por el modo automatico del asistente (proteccion esperada para cambios de infraestructura de produccion) — se le paso el comando al usuario para que lo ejecute cuando decida, o autorice explicitamente.
