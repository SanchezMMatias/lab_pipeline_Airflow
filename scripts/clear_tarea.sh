#!/usr/bin/env bash
# Equivalente al boton "Clear" de la UI (con downstream) via API REST v2 de Airflow 3.
#   bash scripts/clear_tarea.sh <run_id> <task_id>      ej: ... 01-validos__X ventas.validar_precarga
# Usuario/clave de la UI: AIRFLOW_API_USER / AIRFLOW_API_PASS (por defecto los del compose oficial).
set -euo pipefail
API=http://localhost:8080
TOKEN=$(curl -s -X POST "$API/auth/token" -H 'Content-Type: application/json' \
  -d "{\"username\":\"${AIRFLOW_API_USER:-airflow}\",\"password\":\"${AIRFLOW_API_PASS:-airflow}\"}" \
  | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)
curl -s -X POST "$API/api/v2/dags/lab_archivos/clearTaskInstances" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"dry_run\":false,\"dag_run_id\":\"$1\",\"task_ids\":[\"$2\"],\"include_downstream\":true,\"only_failed\":false,\"reset_dag_runs\":true}" \
  | grep -o '"task_id":"[^"]*"' | cut -d'"' -f4 | sort | tr '\n' ' '
echo
