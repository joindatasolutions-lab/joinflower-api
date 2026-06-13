# Pruebas Manuales - Endpoints de Caja

Reemplaza `<TOKEN>` por un JWT valido con acceso al modulo `contabilidad`.

## Listar cierres

```bash
curl "http://127.0.0.1:8001/contabilidad/caja?empresaID=1&sucursalID=1&fechaDesde=2026-06-01&fechaHasta=2026-06-30" \
  -H "Authorization: Bearer <TOKEN>"
```

## Consultar cierre de un dia

```bash
curl "http://127.0.0.1:8001/contabilidad/caja/dia?empresaID=1&sucursalID=1&fecha=2026-06-30" \
  -H "Authorization: Bearer <TOKEN>"
```

## Guardar cierre

```bash
curl -X PUT "http://127.0.0.1:8001/contabilidad/caja/cierre" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "empresaID": 1,
    "sucursalID": 1,
    "fechaOperacion": "2026-06-30",
    "fecha_operacion": "2026-06-30",
    "baseInicial": 100000,
    "base_inicial": 100000,
    "efectivo": 70000,
    "gasto": 0,
    "totalGastos": 0,
    "total_gastos": 0,
    "totalEfectivo": 170000,
    "total_efectivo": 170000,
    "montoGuardado": 40000,
    "monto_guardado": 40000,
    "nuevaBase": 130000,
    "nueva_base": 130000,
    "observacion": "",
    "usuarioID": 1,
    "usuario_id": 1
  }'
```

El campo `efectivo` se calcula en backend desde pagos en efectivo de pedidos para la empresa/sucursal/fecha. El frontend debe cargarlo desde `GET /contabilidad/caja/dia` y tratarlo como solo lectura. Al guardar, el backend persiste en `petalops.caja.efectivo` el valor real calculado desde base de datos.

Los campos editables que vienen del cierre se guardan en `petalops.caja`: `fecha`, `base`, `gasto`, `guardado` y `observacion`. `total_efectivo` y `nueva_base` se recalculan en backend con el efectivo real.
