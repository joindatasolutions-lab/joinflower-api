# Punto 13 — fallback de contraseñas en texto plano eliminado

Relacionado con el punto 13 de [mejoras-arquitectura.md](./mejoras-arquitectura.md).

## Validado contra la BD real antes de tocar código (solo lectura, sin exponer ningún valor)

Se contó cuántos de los 32 usuarios reales en `petalops.usuario` tienen un `passwordhash` que NO es un hash bcrypt (es decir, candidatos a estar usando el fallback de texto plano):

| Métrica | Valor |
|---|---|
| Total usuarios | 32 |
| Con hash bcrypt (`$2...`) | 32 |
| Sin `passwordhash` (nulo/vacío) | 0 |
| Candidatos a texto plano | **0** |

**Los 32 usuarios reales ya tienen hash bcrypt correcto.** El fallback de texto plano en `verify_password` (`app/core/security.py`) era código completamente muerto en la práctica — nadie lo necesitaba.

## Cambio aplicado

`app/core/security.py`, función `verify_password`:

Antes:
```python
def verify_password(plain_password: str, password_hash: str) -> bool:
    if not plain_password or not password_hash:
        return False
    if password_hash.startswith("$2"):
        try:
            return pwd_context.verify(plain_password, password_hash)
        except (exc.UnknownHashError, ValueError):
            return False
    # Transitional fallback for legacy records with plain passwords.
    return plain_password == password_hash
```

Después:
```python
def verify_password(plain_password: str, password_hash: str) -> bool:
    if not plain_password or not password_hash:
        return False
    try:
        return pwd_context.verify(plain_password, password_hash)
    except (exc.UnknownHashError, ValueError):
        return False
```

Cualquier `passwordhash` que no sea un hash bcrypt válido ahora falla la verificación de forma segura (`UnknownHashError` capturado, devuelve `False`) en vez de comparar en texto plano.

## Por qué no hizo falta una migración de datos

El fix sugerido en el documento original incluía "forzar reset de contraseña para cuentas legacy o hashearlas en una migración de datos". No fue necesario: no existen cuentas legacy con contraseña en texto plano hoy en la BD real. Si en el futuro se crea una cuenta con un `passwordhash` no-bcrypt (por un bug o una migración manual mal hecha), ahora falla el login de forma segura en vez de aceptar comparación en texto plano — el comportamiento correcto.

## Validado

- Sintaxis OK, `app.main` importa sin errores.
- Prueba funcional: contraseña bcrypt correcta verifica OK, contraseña bcrypt incorrecta se rechaza, y un `passwordhash` en texto plano (`"abc123"` comparado contra `"abc123"`) **ya no se acepta** (antes del cambio, sí se hubiera aceptado).
