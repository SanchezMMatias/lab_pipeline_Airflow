"""Conciliacion SQL vs control curated, solo sobre el lote."""
from __future__ import annotations

from decimal import Decimal

from .carga_sql import _id, tabla_destino
from .contrato import Contrato


def conciliar(conn, contrato: Contrato, lote_id: str, ctl_curated: dict) -> dict:
    exprs = ["COUNT(*)"]
    for s in contrato.columnas_suma:
        col = contrato.columna(s)
        exprs.append(f"SUM(CAST({_id(s)} AS BIGINT))" if col.tipo == "int" else f"SUM({_id(s)})")
    cur = conn.cursor()
    fila = cur.execute(f"SELECT {', '.join(exprs)} FROM {tabla_destino(contrato)} WHERE lote_id = ?",
                       lote_id).fetchone()
    conn.commit()

    esperado = {"registros": Decimal(ctl_curated["cantidad_registros"])}
    obtenido = {"registros": Decimal(fila[0])}
    for i, s in enumerate(contrato.columnas_suma, start=1):
        esperado[s] = Decimal(ctl_curated["sumatorias"][s])
        obtenido[s] = Decimal(fila[i] if fila[i] is not None else 0)
    diferencias = {k: obtenido[k] - esperado[k] for k in esperado if obtenido[k] != esperado[k]}
    return {"esperado": esperado, "obtenido": obtenido, "diferencias": diferencias, "ok": not diferencias}
