#!/usr/bin/env bash
# Corre en serie los escenarios que no requieren intervencion manual y deja un resumen.
#   bash scripts/correr_escenarios.sh [carpeta_destino_dentro_de_evidencias/local]
# (6, 9 y 10 necesitan editar un .ctl, pausar SQL Server o un UPDATE: ver README.)
set -uo pipefail
cd "$(dirname "$0")/.."
P="${1:-reproceso}"
V=datos/validos/originales; N=datos/negativos
run() { bash scripts/escenario.sh "$P/$1" "${@:2}" > /dev/null; }
run 01-validos            2026-11-09 $V/lab_clientes_20261109.dat $V/lab_ventas_20261109.dat
run 07-reejecucion        2026-11-09
sed -i '2s/|45,34|/|45,35|/' lab_data/entrada/lab_ventas_20261109.dat
run 08-conflicto          2026-11-09
cp $V/lab_ventas_20261109.dat lab_data/entrada/
run 02a-fecha-imposible   2026-11-10 $N/lab_clientes_20261110.dat
run 02b-obligatorio-vacio 2026-11-11 $N/lab_clientes_20261111.dat
run 03-columnas-faltantes 2026-11-12 $N/lab_ventas_20261112.dat
run 04a-clave-duplicada   2026-11-13 $N/lab_ventas_20261113.dat
run 04b-cliente-inexistente 2026-11-14 $N/lab_ventas_20261114.dat
run 05-solo-encabezado    2026-11-16 $N/lab_clientes_20261116.dat
run 11-falla-clientes     2026-11-18 $N/lab_clientes_20261118.dat $N/lab_ventas_20261118.dat
run 12-extra-importe-3-decimales 2026-11-15 $N/lab_ventas_20261115.dat
run 13-extra-moneda-usd   2026-11-17 $N/lab_ventas_20261117.dat
run 19-clientes-nuevos-mismo-dia 2026-11-19 $V/lab_clientes_20261119.dat $V/lab_ventas_20261119.dat
{
  printf '%-34s %-8s %s\n' escenario run "estados en audit_lote"
  for d in evidencias/local/$P/*/; do
    e=$(basename "$d")
    estados=$(grep -E '^ +(archivo|estado):' "$d/audit_lote.txt" | awk '{print $2}' | paste -d= - - | tr '\n' ' ')
    printf '%-34s %-8s %s\n' "$e" "$(cat "$d/estado_run.txt")" "$estados"
  done
} | tee "evidencias/local/$P/RESUMEN.txt"
