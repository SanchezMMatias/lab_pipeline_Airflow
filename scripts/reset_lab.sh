#!/usr/bin/env bash
# Deja el laboratorio vacio: tablas lab.* (datos, no estructura), zonas de lab_data y Mailpit.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose exec -T airflow-worker python -c "
from airflow.providers.odbc.hooks.odbc import OdbcHook
c = OdbcHook(odbc_conn_id='mssql_lab').get_conn(); cur = c.cursor()
for t in ('lab.audit_error', 'lab.audit_lote', 'lab.ventas', 'lab.clientes', 'lab.stg_ventas', 'lab.stg_clientes'):
    cur.execute(f'DELETE FROM {t}'); print(t, cur.rowcount, 'filas borradas')
c.commit()" 2>/dev/null | grep borradas
for z in entrada raw curated rejected; do find "lab_data/$z" -mindepth 1 -delete; done
curl -s -X DELETE http://localhost:8025/api/v1/messages > /dev/null
echo "lab vacio"
