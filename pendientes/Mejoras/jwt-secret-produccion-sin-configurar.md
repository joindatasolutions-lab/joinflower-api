# RESUELTO — JWT_SECRET rotado en produccion

**Estado: RESUELTO (2026-08-03).** Se rotó el secreto en Cloud Run con autorización explícita del usuario. Revisión desplegada: `join-flower-00208-rgs`, sirviendo el 100% del tráfico. Verificado: `JWT_SECRET` aparece en las env vars del servicio (solo se confirmó el nombre, nunca se expuso el valor) y `/health` responde `200 OK`.

Relacionado con el punto 12 de [mejoras-arquitectura.md](./mejoras-arquitectura.md) ("JWT sin refresh token"), encontrado al revisar ese punto.

## El problema que se corrigió

`app/core/security.py:20`:
```python
JWT_SECRET = os.getenv("JWT_SECRET", "dev-change-this-secret")
```

Se había verificado (2026-08-03, solo lectura) que el servicio `join-flower` en Cloud Run (proyecto `flora-471805`, región `us-central1`) **no tenía ni `JWT_SECRET` ni `JWT_SECRET_KEY` configurados**. Producción estaba firmando y validando todos los JWT con el valor por defecto hardcodeado en el código fuente (`"dev-change-this-secret"`), visible para cualquiera con acceso de lectura al repositorio — cualquiera que conociera ese valor podía firmar un JWT válido para cualquier usuario y cualquier rol, incluyendo super admin (`esGlobalJoin=true`), sin ninguna credencial real.

## Causa raíz (corregida en el repo)

`.env.example` documentaba la variable como `JWT_SECRET_KEY`, pero el código real lee `JWT_SECRET` (nombres distintos). Corregido en `.env.example` para que diga `JWT_SECRET`.

## Qué se hizo

Se generó un secreto aleatorio de 64 bytes (`secrets.token_urlsafe(64)`) y se aplicó directamente en Cloud Run:

```bash
JWT_SECRET_NEW=$(python -c "import secrets; print(secrets.token_urlsafe(64))")

gcloud run services update join-flower \
  --project=flora-471805 \
  --region=us-central1 \
  --update-env-vars="JWT_SECRET=${JWT_SECRET_NEW}"
```

**Efecto aplicado, esperado:** todas las sesiones activas al momento de la rotación quedaron invalidadas — todos los usuarios de las 4 empresas necesitaron volver a iniciar sesión después del deploy (~19:xx del 2026-08-03).

## Validación posterior

- `gcloud run services describe` (solo nombres de variables, ningún valor expuesto): `JWT_SECRET` aparece en la lista de env vars del servicio.
- `GET /health` → `200`.
- `GET /` → `200`.
- Revisión activa: `join-flower-00208-rgs`, 100% del tráfico.

## Nota sobre el intento inicial

En un primer intento (mismo día, más temprano), el modo automático del asistente bloqueó el comando `gcloud run services update` por ser un cambio de infraestructura de producción — protección esperada. El usuario decidió posponer la rotación en ese momento porque las floristerías estaban trabajando activamente. Más tarde, el mismo día, el usuario confirmó explícitamente que era buen momento y se aplicó sin bloqueo.
