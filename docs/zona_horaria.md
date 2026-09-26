# Fechas y horas de Colombia

Los campos DateTime de todos los modelos usan `ColombiaDateTime`: las entradas
con zona horaria se convierten a `America/Bogota` antes de almacenarse. Los
timestamps sin zona se interpretan como hora local de Colombia y conservan su
valor. Las respuestas de esos campos mantienen el formato sin offset existente.

Las conexiones de la API a PostgreSQL configuran `timezone=America/Bogota`,
incluyendo los valores generados por `CURRENT_TIMESTAMP`, `NOW()` y
`CURRENT_DATE`. Reiniciar o desplegar la API aplica esta configuración a sus
nuevas conexiones. No cambia la configuración de clientes externos de la BD.

Para generar fechas de negocio se usan `colombia_now_naive()` y
`colombia_today()`. Los JWT conservan sus instantes UTC de emisión y expiración.

Este cambio no convierte registros históricos. Hay código previo que guardaba
UTC y otro que ya guardaba hora colombiana en columnas sin zona. Para migrar
históricos se debe identificar el origen y periodo de cada campo; restar cinco
horas a todas las tablas dañaría los valores que ya eran locales.
