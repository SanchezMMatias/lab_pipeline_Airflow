"""Imprime audit_lote y audit_error de un dag_run (se ejecuta dentro del worker).

    docker compose exec -T airflow-worker python - <run_id> < scripts/evidencia_sql.py
La ultima linea es 'LOTES: <lote_id> ...' para que el script de evidencias copie los .ctl.
"""
import sys

from airflow.providers.odbc.hooks.odbc import OdbcHook

run_id = sys.argv[1]
conn = OdbcHook(odbc_conn_id="mssql_lab").get_conn()
cur = conn.cursor()

cols = ["audit_id", "archivo", "estado", "lote_id", "registros_esp", "registros_obt",
        "suma_cantidad_esp", "suma_cantidad_obt", "suma_importe_esp", "suma_importe_obt",
        "inicio_utc", "fin_utc", "motivo"]
filas = cur.execute(f"SELECT {', '.join(cols)} FROM lab.audit_lote WHERE dag_run_id = ? ORDER BY audit_id",
                    run_id).fetchall()
print(f"-- SELECT * FROM lab.audit_lote WHERE dag_run_id = '{run_id}'")
for f in filas:
    print("-" * 80)
    for c, v in zip(cols, f):
        print(f"{c:>18}: {v}")
errores = cur.execute(
    "SELECT e.audit_id, e.nro_registro, e.columna, e.valor, e.motivo FROM lab.audit_error e "
    "JOIN lab.audit_lote a ON a.audit_id = e.audit_id WHERE a.dag_run_id = ? ORDER BY e.error_id",
    run_id).fetchall()
if errores:
    print("\n-- lab.audit_error")
    for e in errores:
        print(f"audit_id={e[0]} registro={e[1]} columna={e[2]} valor={e[3]!r} motivo={e[4]}")
print("\n-- conteos en destino")
for t in ("lab.clientes", "lab.ventas"):
    n, lotes = cur.execute(f"SELECT COUNT(*), COUNT(DISTINCT lote_id) FROM {t}").fetchone()
    print(f"{t}: {n} filas en {lotes} lotes")
print("LOTES: " + " ".join(sorted({f[3] for f in filas})))
