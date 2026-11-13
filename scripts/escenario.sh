#!/usr/bin/env bash
# Dispara lab_archivos para una fecha, espera el fin del run y junta las evidencias en
# evidencias/local/<escenario>/.
#
#   bash scripts/escenario.sh <escenario> <fecha YYYY-MM-DD> [archivos a copiar a entrada/ ...]
#   bash scripts/escenario.sh evidencia <escenario> <run_id>   # solo junta evidencias de un run
#
# Ejemplo: bash scripts/escenario.sh 01-validos 2026-11-09 datos/validos/originales/*_20261109.dat
set -euo pipefail
cd "$(dirname "$0")/.."
DC="docker compose"

esperar() {  # $1 run_id
  local estado=""
  for _ in $(seq 1 180); do
    estado=$($DC exec -T airflow-scheduler airflow dags list-runs lab_archivos -o plain 2>/dev/null \
             | awk -v r="$1" '$2 == r {print $3}')
    case "$estado" in success|failed) echo "$estado"; return 0 ;; esac
    sleep 5
  done
  echo "timeout"
}

evidencia() {  # $1 escenario, $2 run_id
  local dir="evidencias/local/$1"
  mkdir -p "$dir"
  echo "$2" > "$dir/run_id.txt"
  # Estado de cada tarea (equivalente textual de la vista Grid)
  $DC exec -T airflow-scheduler airflow tasks states-for-dag-run lab_archivos "$2" -o table \
    2>/dev/null | grep -v -i warning > "$dir/tareas.txt" || true
  # Auditoria del run
  $DC exec -T airflow-worker python - "$2" < scripts/evidencia_sql.py 2>/dev/null \
    | grep -v -E "^\S+Z \[|warn" > "$dir/audit_lote.txt"
  # .ctl raw y curated + detalle de rejected de los lotes del run
  for lote in $(sed -n 's/^LOTES: //p' "$dir/audit_lote.txt"); do
    find lab_data/raw lab_data/curated lab_data/rejected -path "*lote=$lote/*" \
      \( -name '*.ctl' -o -name '*.errores.json' \) 2>/dev/null | while read -r f; do
        zona=$(echo "$f" | cut -d/ -f2)
        cp "$f" "$dir/${zona}__$(basename "$f")"
      done
  done
  # Ultimo correo recibido en Mailpit (HTML renderizado)
  local id
  id=$(curl -s "http://localhost:8025/api/v1/messages?limit=1" | grep -o '"ID":"[^"]*"' | head -1 | cut -d'"' -f4)
  if [ -n "$id" ]; then
    curl -s "http://localhost:8025/view/$id.html" > "$dir/correo.html"
    curl -s "http://localhost:8025/api/v1/message/$id" | grep -o '"Subject":"[^"]*"' | head -1 > "$dir/correo_asunto.txt"
  fi
  echo "evidencias en $dir"
}

if [ "$1" = "evidencia" ]; then
  evidencia "$2" "$3"
  exit 0
fi

escenario=$1; fecha=$2; shift 2
for f in "$@"; do cp "$f" lab_data/entrada/; done
run="$(echo "$escenario" | tr "/" "_")__$(date -u +%Y%m%dT%H%M%S)"   # "/" no es valido en un run_id
if ! $DC exec -T airflow-scheduler airflow dags trigger lab_archivos -r "$run" \
     -c "{\"fecha_negocio\": \"$fecha\"}" > /dev/null 2>&1; then
  echo "no se pudo disparar el run $run" >&2; exit 1
fi
echo "run $run disparado"
estado=$(esperar "$run")
echo "run terminado: $estado"
evidencia "$escenario" "$run"
echo "$estado" > "evidencias/local/$escenario/estado_run.txt"
