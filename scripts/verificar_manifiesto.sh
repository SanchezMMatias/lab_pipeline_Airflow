#!/usr/bin/env bash
# Verificacion independiente del manifiesto: no usa Python ni el codigo del pipeline.
# Recalcula conteos, sumas y sha256 con tail/wc/awk/sha256sum y los compara con lo que
# declara datos/validos/manifiesto.json.
# Uso: bash scripts/verificar_manifiesto.sh [datos/validos]
set -u
DIR="${1:-datos/validos}"
MAN="$DIR/manifiesto.json"
fallas=0

# Extrae "clave": valor dentro del bloque del archivo indicado (manifiesto con indent=2)
valor() {  # $1 archivo, $2 clave
  awk -v a="\"$1\"" -v k="\"$2\"" '
    index($0, a) { dentro = 1 }
    dentro && index($0, k) { sub(/^[^:]*: */, ""); gsub(/[",]/, ""); print; exit }
    dentro && /^    }/ { dentro = 0 }' "$MAN"
}

comparar() {  # $1 descripcion, $2 esperado, $3 obtenido
  if [ "$2" = "$3" ]; then printf '  OK         %-28s %s\n' "$1" "$3"
  else printf '  DIFERENCIA %-28s manifiesto=%s calculado=%s\n' "$1" "$2" "$3"; fallas=$((fallas + 1)); fi
}

for f in "$DIR"/esperados/*.dat; do
  a=$(basename "$f")
  echo "== $a (normalizado esperado)"
  comparar registros "$(valor "$a" registros)" "$(tail -n +2 "$f" | wc -l | tr -d ' ')"
  comparar sha256_esperado "$(valor "$a" sha256_esperado)" "$(sha256sum "$f" | cut -d' ' -f1)"
  comparar sha256_original "$(valor "$a" sha256_original)" "$(sha256sum "$DIR/originales/$a" | cut -d' ' -f1)"
  if [[ "$a" == lab_ventas_* ]]; then
    # col 4 = cantidad, col 5 = importe_total. awk usa punto flotante: alcanza como referencia.
    read -r c i < <(tail -n +2 "$f" | awk -F'|' '{c+=$4; i+=$5} END {printf "%d %.2f\n", c, i}')
    comparar suma_cantidad "$(valor "$a" suma_cantidad)" "$c"
    comparar suma_importe_total "$(valor "$a" suma_importe_total)" "$i"
    # todas las ventas referencian clientes existentes del archivo de clientes
    huerfanas=$(tail -n +2 "$f" | cut -d'|' -f2 | sort -u | \
      grep -vxF -f <(tail -n +2 "$DIR/esperados/lab_clientes_${a#lab_ventas_}" | cut -d'|' -f1) | wc -l | tr -d ' ')
    comparar ventas_con_cliente_inexistente 0 "$huerfanas"
  fi
done
echo
if [ "$fallas" -eq 0 ]; then echo "Manifiesto verificado: sin diferencias."; else echo "$fallas diferencias"; exit 1; fi
