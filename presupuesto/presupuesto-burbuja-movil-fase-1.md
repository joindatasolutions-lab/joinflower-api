# Presupuesto nube - Burbuja Movil Fase 1

Fecha de analisis: 2026-08-21

## Base usada

Se revisaron los CSV descargados desde Google Cloud Billing en la carpeta `presupuesto`.

Archivos revisados:

- `Mi cuenta de facturación_Informes, 2026-07-01 — 2026-07-31.csv`
- `Mi cuenta de facturación_Informes, 2026-07-01 — 2026-07-31 (1).csv`
- `Mi cuenta de facturación_Informes, 2026-08-01 — 2026-08-31.csv`

El presupuesto es para Burbuja Movil Fase 1 con 1 sucursal.

## Gasto real observado

### Julio 2026 completo

Total del proyecto `flora-471805`: COP 117.623

Desglose por servicio:

| Servicio | Costo COP |
|---|---:|
| Cloud Run | 82.049 |
| Cloud SQL | 32.671 |
| Artifact Registry | 2.898 |
| Cloud Build | 5 |
| Total | 117.623 |

### Agosto 2026 parcial

Total observado al 2026-08-21: COP 218.577

Desglose por servicio:

| Servicio | Costo COP |
|---|---:|
| Cloud SQL | 161.411 |
| Cloud Run | 54.292 |
| Artifact Registry | 2.872 |
| Cloud Build | 2 |
| Total parcial | 218.577 |

Proyeccion simple de agosto, si el consumo continuara igual hasta el 31 de agosto:

COP 218.577 / 21 dias * 31 dias = COP 322.947 aproximados.

Nota: la facturacion de Google Cloud puede tener retrasos o ajustes durante el mes, por lo que esta proyeccion debe verse como referencia, no como cierre contable.

## Lectura tecnica

El costo real no esta cerca de USD 150-180 mensuales para el escenario actual observado. Con la facturacion descargada, el proyecto se esta moviendo aproximadamente entre:

- COP 117.623 mensuales en julio.
- COP 320.000 aproximados proyectados para agosto si se mantiene la tendencia actual.

El aumento de agosto viene principalmente de Cloud SQL. En julio Cloud SQL costo COP 32.671; en agosto parcial ya va en COP 161.411.

Esto sugiere que hubo cambio de configuracion, mas horas activas, instancia mas grande, backups, almacenamiento, o alguna condicion de facturacion distinta en Cloud SQL.

## Presupuesto recomendado para Burbuja Movil - 1 sucursal

Para una primera fase con 1 sucursal, POS, inventario, clientes, informes y usuarios, sin Redis y sin servicios premium adicionales:

| Concepto | Presupuesto mensual COP |
|---|---:|
| Cloud Run backend | 50.000 - 90.000 |
| Cloud SQL PostgreSQL | 40.000 - 170.000 |
| Artifact Registry | 3.000 - 5.000 |
| Cloud Build | 0 - 5.000 |
| Logs / monitoreo basico | 0 - 10.000 |
| Almacenamiento archivos basico | 0 - 10.000 |
| Total estimado optimizado | 100.000 - 180.000 |
| Total con margen de produccion | 180.000 - 280.000 |

## Valor a cotizar

Recomendacion comercial para 1 sucursal:

COP 250.000 mensuales de infraestructura cloud.

Este valor cubre el comportamiento real observado, deja margen frente a crecimiento moderado y evita vender la nube demasiado ajustada.

Si el cliente pide un valor mas economico para arranque:

COP 180.000 mensuales.

Ese valor es viable solo si se controla Cloud SQL, se evita sobredimensionar la instancia, y se monitorea el consumo durante el primer mes.

## Recomendacion de arquitectura inicial

Para 1 sucursal no se recomienda Redis al inicio.

Arquitectura sugerida:

- Cloud Run para backend.
- Cloud SQL PostgreSQL para base de datos.
- Artifact Registry para imagenes Docker.
- Cloud Storage solo si se guardaran archivos, imagenes, reportes exportados o soportes.
- Cloud Logging y Monitoring basico.

Redis se recomienda dejarlo como fase posterior si aparecen problemas reales de rendimiento, muchas consultas repetidas, reportes pesados, concurrencia alta o crecimiento a varias sucursales.

## Puntos a validar antes de cerrar precio

- Revisar por que Cloud SQL subio de COP 32.671 en julio a COP 161.411 parcial en agosto.
- Confirmar si Burbuja Movil tendra ambiente unico o separados dev/prod.
- Confirmar si el sistema guardara imagenes de productos, PDFs, soportes o archivos Excel.
- Confirmar numero estimado de usuarios concurrentes en POS.
- Confirmar si los reportes se calculan en tiempo real o se pueden precalcular.

