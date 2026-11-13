"""Acceso a lab.audit_lote / lab.audit_error. Una fila por intento (ejecucion x archivo)."""
from __future__ import annotations

from dataclasses import dataclass

from .errores import MAX_MOTIVO, ErrorRegistro
from .nombres import ArchivoEntrada

TABLA = "lab.audit_lote"
ESTADOS_OK = {"CORRECTO", "YA_PROCESADO"}
ESTADOS_ABIERTOS = ("EN_PROCESO", "PUBLICADO")
# columnas_suma del contrato -> columnas de audit_lote
MAPA_SUMAS = {"cantidad": "suma_cantidad", "importe_total": "suma_importe"}
ACTUALIZABLES = {
    "estado", "motivo", "sha256_curated", "registros_esp", "registros_obt",
    "suma_cantidad_esp", "suma_cantidad_obt", "suma_importe_esp", "suma_importe_obt",
}


@dataclass(frozen=True)
class Previo:
    audit_id: int
    sha256: str
    estado: str
    dag_run_id: str


def decidir_recepcion(previos: list[Previo], sha256: str, dag_run_id: str) -> tuple[str, int | None]:
    """Idempotencia. Devuelve (estado, audit_id a reutilizar o None).

    - nombre nuevo                                   -> EN_PROCESO
    - mismo nombre, sha256 distinto                  -> CONFLICTO (no se toca raw ni SQL)
    - mismo nombre y sha256, ya CORRECTO             -> YA_PROCESADO
    - mismo nombre y sha256, estado previo no OK     -> EN_PROCESO (reintento)
    Las filas CONFLICTO no cuentan como historia del archivo.
    """
    relevantes = [p for p in previos if p.estado != "CONFLICTO"]
    if any(p.sha256 != sha256 for p in relevantes):
        return "CONFLICTO", None
    if any(p.estado == "CORRECTO" for p in relevantes):
        return "YA_PROCESADO", None
    # Reintento de la propia tarea de recepcion dentro del mismo run: reutilizar la fila
    for p in reversed(relevantes):
        if p.dag_run_id == dag_run_id and p.estado == "EN_PROCESO":
            return "EN_PROCESO", p.audit_id
    return "EN_PROCESO", None


def previos(conn, archivo: str) -> list[Previo]:
    cur = conn.cursor()
    filas = cur.execute(
        f"SELECT audit_id, sha256_origen, estado, dag_run_id FROM {TABLA} WHERE archivo = ? ORDER BY audit_id",
        archivo).fetchall()
    conn.commit()
    return [Previo(int(f[0]), f[1], f[2], f[3]) for f in filas]


def insertar(conn, info: ArchivoEntrada, lote_id: str, sha256: str, dag_id: str, dag_run_id: str,
             estado: str, motivo: str | None = None, terminal: bool = False) -> int:
    cur = conn.cursor()
    audit_id = cur.execute(
        f"""INSERT INTO {TABLA} (archivo, schema_destino, tabla_destino, fecha_negocio, lote_id,
                sha256_origen, dag_id, dag_run_id, estado, motivo, fin_utc)
            OUTPUT INSERTED.audit_id
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? = 1 THEN SYSUTCDATETIME() END)""",
        info.archivo, info.schema, info.tabla, info.fecha, lote_id, sha256, dag_id, dag_run_id,
        estado, (motivo or None) and motivo[:MAX_MOTIVO], 1 if terminal else 0).fetchval()
    conn.commit()
    return int(audit_id)


def actualizar(conn, audit_id: int, fin: bool = False, **campos) -> None:
    desconocidos = set(campos) - ACTUALIZABLES
    if desconocidos:
        raise ValueError(f"columnas no actualizables: {desconocidos}")
    if "motivo" in campos and campos["motivo"]:
        campos["motivo"] = campos["motivo"][:MAX_MOTIVO]
    sets = [f"{c} = ?" for c in campos]
    if fin:
        sets.append("fin_utc = SYSUTCDATETIME()")
    if not sets:
        return
    cur = conn.cursor()
    cur.execute(f"UPDATE {TABLA} SET {', '.join(sets)} WHERE audit_id = ?", *campos.values(), audit_id)
    conn.commit()


def registrar_errores(conn, audit_id: int, errores: list[ErrorRegistro], maximo: int = 500) -> None:
    """Reemplaza el detalle de la fila: al hacer Clear de una tarea se reutiliza el audit_id
    y no deben quedar errores de un intento anterior."""
    cur = conn.cursor()
    cur.execute("DELETE FROM lab.audit_error WHERE audit_id = ?", audit_id)
    if not errores:
        conn.commit()
        return
    cur.executemany(
        "INSERT INTO lab.audit_error (audit_id, nro_registro, columna, valor, motivo) VALUES (?, ?, ?, ?, ?)",
        [(audit_id, e.registro, (e.columna or None) and e.columna[:128],
          None if e.valor is None else str(e.valor)[:400], e.motivo[:400]) for e in errores[:maximo]])
    conn.commit()


def marcar_fallido_si_abierto(conn, audit_id: int, motivo: str) -> None:
    """Para on_failure_callback: no pisa estados terminales ya informados (RECHAZADO, etc.)."""
    cur = conn.cursor()
    cur.execute(
        f"""UPDATE {TABLA} SET estado = 'FALLIDO', motivo = ?, fin_utc = SYSUTCDATETIME()
            WHERE audit_id = ? AND estado IN ('EN_PROCESO', 'PUBLICADO')""",
        motivo[:MAX_MOTIVO], audit_id)
    conn.commit()


def ultimo_estado(conn, schema: str, tabla: str, fecha) -> str | None:
    """Estado del ultimo intento para una tabla y fecha de negocio (cualquier run)."""
    cur = conn.cursor()
    fila = cur.execute(
        f"""SELECT TOP 1 estado FROM {TABLA}
            WHERE schema_destino = ? AND tabla_destino = ? AND fecha_negocio = ? AND estado <> 'CONFLICTO'
            ORDER BY audit_id DESC""", schema, tabla, fecha).fetchone()
    conn.commit()
    return fila[0] if fila else None


COLUMNAS_RESUMEN = [
    "audit_id", "archivo", "schema_destino", "tabla_destino", "fecha_negocio", "lote_id", "estado",
    "registros_esp", "registros_obt", "suma_cantidad_esp", "suma_cantidad_obt",
    "suma_importe_esp", "suma_importe_obt", "motivo", "inicio_utc", "fin_utc",
]


def filas_del_run(conn, dag_run_id: str) -> list[dict]:
    cur = conn.cursor()
    filas = cur.execute(
        f"SELECT {', '.join(COLUMNAS_RESUMEN)} FROM {TABLA} WHERE dag_run_id = ? ORDER BY audit_id",
        dag_run_id).fetchall()
    conn.commit()
    return [dict(zip(COLUMNAS_RESUMEN, f)) for f in filas]
