# Prompt 1: datos validos con anomalias corregibles

Generá datos sintéticos siguiendo este contrato:

- Archivos `schema_tabla_YYYYMMDD.dat`, UTF-8 sin BOM, delimitador `|`, comillas `"` con
  comillas internas duplicadas (`""`), salto de línea `\n`, encabezado obligatorio.
- `lab_clientes`: cliente_id int >0 | nombre text ≤100 obligatorio | email (minúsculas, ≤254) |
  fecha_alta date | pais_codigo code(2) en AR, CL, UY | activo bool.
- `lab_ventas`: venta_id int >0 | cliente_id int (FK a clientes) | fecha_venta date |
  cantidad int >0 | importe_total decimal(14,2) ≥0 | moneda code(3) = ARS | observacion text ≤200 opcional.
- Normalización: trim externo; email en minúsculas; códigos en mayúsculas; fechas
  YYYY-MM-DD, DD/MM/YYYY o DD-MM-YYYY → YYYY-MM-DD; booleanos sí/si/true/1 → 1 y no/false/0 → 0;
  decimales con coma o punto → punto con 2 decimales; NULL, N/A o vacío en opcional → vacío.

Quiero 20 clientes y 100 ventas con fecha de negocio 2026-11-09, todas las ventas referenciando
clientes existentes. Introducí anomalías corregibles: espacios externos, emails en mayúsculas,
país en minúsculas, fechas en los tres formatos admitidos, booleanos sí/true/1, importes con coma
decimal, NULL y N/A en observación, comillas internas duplicadas.

Entregá por separado: (1) los .dat originales, (2) los .dat normalizados esperados, (3) un
manifiesto JSON con conteos, suma de cantidad, suma de importe_total y la lista de anomalías por
registro y columna.

---
**Nota de ejecución.** La IA (Claude, en Claude Code) respondió entregando un generador
determinístico (`datos/generar_sinteticos.py`, semilla fija) en lugar de pegar 120 filas a mano:
parte de los valores limpios (la verdad), de ahí escribe el normalizado esperado y "ensucia"
cada valor para producir el original. Así el esperado no depende del código de normalización del
pipeline y el manifiesto se puede regenerar. Las sumas y conteos del manifiesto se verificaron
igual con `scripts/verificar_manifiesto.sh` (awk/sha256sum), sin creerle al generador.
