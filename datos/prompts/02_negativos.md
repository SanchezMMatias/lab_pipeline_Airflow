# Prompt 2: variantes no corregibles (un archivo por caso)

Con el mismo contrato del prompt 1, generá un archivo pequeño por caso, válido en todo lo
demás, con IDs que no choquen con los del 2026-11-09 (clientes 1-20, ventas 1-100):

| Archivo | Error |
|---|---|
| lab_clientes_20261110.dat | fecha 31/02/2026 |
| lab_clientes_20261111.dat | nombre vacío |
| lab_ventas_20261112.dat | un registro con una columna de menos |
| lab_ventas_20261113.dat | venta_id duplicado |
| lab_ventas_20261114.dat | cliente_id inexistente |
| lab_ventas_20261115.dat | importe 12,345 (3 decimales) |
| lab_clientes_20261116.dat | solo encabezado |
| lab_ventas_20261117.dat | moneda USD |

Agregado para los escenarios 9 y 11 del paso 8:

| Archivo | Uso |
|---|---|
| lab_clientes_20261118.dat + lab_ventas_20261118.dat | clientes con un email inválido y ventas válidas del mismo día → ventas BLOQUEADO_DEPENDENCIA |
| lab_clientes_20261119.dat + lab_ventas_20261119.dat | lote válido nuevo para la falla transitoria (docker pause en la publicación) |
