"""Staging, validacion en staging y publicacion transaccional. Recibe una conexion DB-API
(pyodbc) ya abierta con autocommit=False; no sabe nada de Airflow.

Siempre SQL parametrizado: los valores nunca se concatenan. Los nombres de tabla/columna
salen del contrato y se validan con una regex antes de usarse.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from .contrato import Contrato
from .errores import ErrorCalidad, ErrorRegistro

AUDIT = "lab.audit_lote"
_RE_IDENT = re.compile(r"[a-z][a-z0-9_]*")


def _id(nombre: str) -> str:
    if not _RE_IDENT.fullmatch(nombre):
        raise ValueError(f"identificador invalido: {nombre!r}")
    return f"[{nombre}]"


def tabla_destino(c: Contrato) -> str:
    return f"{_id(c.schema)}.{_id(c.tabla)}"


def tabla_staging(c: Contrato) -> str:
    return f"{_id(c.schema)}.{_id('stg_' + c.tabla)}"


def _tabla_ref(nombre_completo: str) -> str:
    schema, tabla = nombre_completo.split(".")
    return f"{_id(schema)}.{_id(tabla)}"


def valores_sql(contrato: Contrato, fila: list[str]) -> list:
    """De string normalizado a tipo Python para pyodbc."""
    salida = []
    for col, v in zip(contrato.columnas, fila):
        if v == "":
            salida.append(None)
        elif col.tipo == "int":
            salida.append(int(v))
        elif col.tipo == "decimal":
            salida.append(Decimal(v))
        elif col.tipo == "date":
            salida.append(date.fromisoformat(v))
        elif col.tipo == "bool":
            salida.append(v == "1")
        else:
            salida.append(v)
    return salida


def _input_sizes(contrato: Contrato) -> list:
    """Tipos explicitos para fast_executemany: evita que un None en la primera fila
    haga adivinar mal el tipo o el largo de la columna."""
    import pyodbc

    tamanos = [(pyodbc.SQL_VARCHAR, 80, 0), (pyodbc.SQL_INTEGER, 0, 0)]
    for col in contrato.columnas:
        if col.tipo == "int":
            tamanos.append((pyodbc.SQL_INTEGER, 0, 0))
        elif col.tipo == "decimal":
            tamanos.append((pyodbc.SQL_DECIMAL, col.precision, col.escala))
        elif col.tipo == "date":
            tamanos.append((pyodbc.SQL_TYPE_DATE, 0, 0))
        elif col.tipo == "bool":
            tamanos.append((pyodbc.SQL_BIT, 0, 0))
        else:
            tamanos.append((pyodbc.SQL_WVARCHAR, col.largo_max or col.largo or 254, 0))
    return tamanos


def cargar_staging(conn, contrato: Contrato, lote_id: str, filas: list[list[str]]) -> int:
    """Reintentable: borra lo que haya dejado un intento anterior del mismo lote."""
    stg = tabla_staging(contrato)
    columnas = ["lote_id", "nro_registro", *contrato.encabezado]
    sql = (f"INSERT INTO {stg} ({', '.join(_id(c) for c in columnas)}) "
           f"VALUES ({', '.join('?' * len(columnas))})")
    parametros = [[lote_id, nro, *valores_sql(contrato, f)] for nro, f in enumerate(filas, start=1)]
    cur = conn.cursor()
    try:
        cur.execute(f"DELETE FROM {stg} WHERE lote_id = ?", lote_id)
        if parametros:
            cur.fast_executemany = True
            cur.setinputsizes(_input_sizes(contrato))
            cur.executemany(sql, parametros)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(parametros)


def validar_staging(conn, contrato: Contrato, lote_id: str, registros_esperados: int) -> None:
    """Errores de calidad que se explican con una consulta en lugar de un error del motor."""
    stg, dest = tabla_staging(contrato), tabla_destino(contrato)
    cur = conn.cursor()
    errores: list[ErrorRegistro] = []

    n = cur.execute(f"SELECT COUNT(*) FROM {stg} WHERE lote_id = ?", lote_id).fetchval()
    if n != registros_esperados:
        errores.append(ErrorRegistro(None, None, str(n),
                                     f"staging tiene {n} registros y el control curated {registros_esperados}"))

    pk = contrato.clave_primaria
    union = " AND ".join(f"d.{_id(c)} = s.{_id(c)}" for c in pk)
    for fila in cur.execute(
            f"SELECT s.nro_registro, {', '.join('s.' + _id(c) for c in pk)}, d.lote_id "
            f"FROM {stg} s JOIN {dest} d ON {union} WHERE s.lote_id = ? AND d.lote_id <> ? "
            f"ORDER BY s.nro_registro", lote_id, lote_id).fetchall():
        errores.append(ErrorRegistro(fila[0], ",".join(pk), "|".join(str(v) for v in fila[1:-1]),
                                     f"identificador existente en {contrato.nombre_completo} (lote {fila[-1]})"))

    # Referencias a tablas que NO estan en depende_de se validan ya; las de depende_de se validan
    # despues de que la dependencia publique (pueden llegar clientes nuevos el mismo dia).
    errores += _errores_referencias(cur, contrato, lote_id, solo_dependencias=False)
    conn.commit()
    if errores:
        raise ErrorCalidad(f"validacion en staging fallida ({len(errores)} errores)", errores, etapa="staging")


def _errores_referencias(cur, contrato: Contrato, lote_id: str, solo_dependencias: bool) -> list[ErrorRegistro]:
    stg = tabla_staging(contrato)
    errores: list[ErrorRegistro] = []
    for col in contrato.columnas:
        if not col.referencia or (col.referencia["tabla"] in contrato.depende_de) != solo_dependencias:
            continue
        ref, ref_col = _tabla_ref(col.referencia["tabla"]), _id(col.referencia["columna"])
        faltantes = cur.execute(
            f"SELECT s.nro_registro, s.{_id(col.nombre)} FROM {stg} s WHERE s.lote_id = ? "
            f"AND NOT EXISTS (SELECT 1 FROM {ref} r WHERE r.{ref_col} = s.{_id(col.nombre)}) "
            f"ORDER BY s.nro_registro", lote_id).fetchall()
        ids = sorted({f[1] for f in faltantes})
        for f in faltantes:
            errores.append(ErrorRegistro(f[0], col.nombre, str(f[1]),
                                         f"{col.nombre} inexistente en {col.referencia['tabla']}"))
        if ids:
            errores.insert(0, ErrorRegistro(None, col.nombre, ",".join(map(str, ids)),
                                            f"{len(ids)} {col.nombre} inexistentes en {col.referencia['tabla']}"))
    return errores


def validar_referencias(conn, contrato: Contrato, lote_id: str) -> None:
    """FK hacia tablas de depende_de, una vez que la dependencia del dia ya publico."""
    errores = _errores_referencias(conn.cursor(), contrato, lote_id, solo_dependencias=True)
    conn.commit()
    if errores:
        raise ErrorCalidad(f"referencias inexistentes ({len(errores)} errores)", errores, etapa="referencias")


def publicar(conn, contrato: Contrato, lote_id: str, audit_id: int, demora_s: int = 0) -> bool:
    """Una transaccion por tabla con XACT_ABORT ON: cualquier error (PK, FK, CHECK, corte de
    conexion o timeout del cliente) revierte todo; nunca queda una carga parcial.

    Devuelve True si publico ahora, False si el lote ya estaba publicado (reintento despues
    de un commit exitoso): en ese caso no duplica y se sigue a conciliar.
    demora_s solo sirve para el escenario 9 (pausar SQL Server en plena publicacion).
    """
    stg, dest = tabla_staging(contrato), tabla_destino(contrato)
    columnas = ", ".join(_id(c) for c in [*contrato.encabezado, "lote_id"])
    cur = conn.cursor()
    try:
        cur.execute("SET XACT_ABORT ON")
        ya = cur.execute(f"SELECT TOP 1 1 FROM {dest} WITH (UPDLOCK, HOLDLOCK) WHERE lote_id = ?",
                         lote_id).fetchone()
        if ya:
            # No duplicar; solo limpiar el staging que haya recargado este reintento.
            cur.execute(f"DELETE FROM {stg} WHERE lote_id = ?", lote_id)
            conn.commit()
            return False
        cur.execute(f"INSERT INTO {dest} ({columnas}) SELECT {columnas} FROM {stg} WHERE lote_id = ?",
                    lote_id)
        if demora_s:
            cur.execute(f"WAITFOR DELAY '00:00:{max(0, min(int(demora_s), 59)):02d}'")
        cur.execute(f"DELETE FROM {stg} WHERE lote_id = ?", lote_id)
        cur.execute(f"UPDATE {AUDIT} SET estado = 'PUBLICADO' WHERE audit_id = ?", audit_id)
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    return True
