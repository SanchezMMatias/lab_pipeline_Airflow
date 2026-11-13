"""Integracion contra el SQL Server del compose. Se corre dentro del worker (tiene el driver ODBC
y la conexion mssql_lab). Copiar SIEMPRE a un directorio nuevo: docker cp copia como root y si el
destino ya existe anida la copia y se terminan corriendo tests viejos.

    bash scripts/test_integracion.sh

Usa IDs 900001+ y lotes 'test.*', y los borra antes y despues: no ensucia los escenarios.
"""
import pytest

pyodbc = pytest.importorskip("pyodbc")

from lab_pipeline import carga_sql, conciliacion  # noqa: E402
from lab_pipeline.errores import ErrorCalidad  # noqa: E402

LOTE_C = "test.clientes-20990101-000000000000"
LOTE_V = "test.ventas-20990101-000000000000"
CLIENTES = [[str(900000 + i), f"Test {i}", f"t{i}@ejemplo.com", "2026-01-01", "AR", "1"] for i in range(1, 4)]
VENTAS = [[str(900000 + i), str(900001 + i % 3), "2026-11-09", str(i), f"{i}0.50", "ARS", ""] for i in range(1, 6)]


def _conexion():
    try:
        from airflow.providers.odbc.hooks.odbc import OdbcHook
        conn = OdbcHook(odbc_conn_id="mssql_lab").get_conn()
    except Exception as e:  # fuera del contenedor no hay conexion
        pytest.skip(f"sin SQL Server: {type(e).__name__}")
    conn.timeout = 30
    return conn


def _limpiar(conn):
    cur = conn.cursor()
    for t in ("lab.ventas", "lab.stg_ventas", "lab.clientes", "lab.stg_clientes"):
        cur.execute(f"DELETE FROM {t} WHERE lote_id LIKE 'test.%'")
    conn.commit()


@pytest.fixture
def conn():
    c = _conexion()
    _limpiar(c)
    yield c
    _limpiar(c)
    c.close()


def _contar(conn, tabla, lote):
    n = conn.cursor().execute(f"SELECT COUNT(*) FROM {tabla} WHERE lote_id = ?", lote).fetchval()
    conn.commit()
    return n


def test_cargar_dos_veces_no_duplica(conn, clientes):
    assert carga_sql.cargar_staging(conn, clientes, LOTE_C, CLIENTES) == 3
    assert carga_sql.cargar_staging(conn, clientes, LOTE_C, CLIENTES) == 3   # reintento de staging
    assert _contar(conn, "lab.stg_clientes", LOTE_C) == 3
    carga_sql.validar_staging(conn, clientes, LOTE_C, 3)
    assert carga_sql.publicar(conn, clientes, LOTE_C, audit_id=-1) is True
    carga_sql.cargar_staging(conn, clientes, LOTE_C, CLIENTES)              # reintento completo
    assert carga_sql.publicar(conn, clientes, LOTE_C, audit_id=-1) is False  # ya publicado
    assert _contar(conn, "lab.clientes", LOTE_C) == 3
    assert _contar(conn, "lab.stg_clientes", LOTE_C) == 0                   # y staging limpio


def test_falla_entre_staging_y_publicacion_no_duplica(conn, clientes, ventas):
    carga_sql.cargar_staging(conn, clientes, LOTE_C, CLIENTES)
    carga_sql.publicar(conn, clientes, LOTE_C, audit_id=-1)
    carga_sql.cargar_staging(conn, ventas, LOTE_V, VENTAS)

    # Simula la conexion muriendo en plena publicacion: INSERT hecho, sin commit, conexion cerrada.
    otra = _conexion()
    cur = otra.cursor()
    cur.execute("SET XACT_ABORT ON")
    cur.execute("INSERT INTO lab.ventas (venta_id, cliente_id, fecha_venta, cantidad, importe_total, moneda, "
                "observacion, lote_id) SELECT venta_id, cliente_id, fecha_venta, cantidad, importe_total, "
                "moneda, observacion, lote_id FROM lab.stg_ventas WHERE lote_id = ?", LOTE_V)
    otra.close()
    assert _contar(conn, "lab.ventas", LOTE_V) == 0          # el motor revirtio todo

    assert carga_sql.publicar(conn, ventas, LOTE_V, audit_id=-1) is True   # el reintento publica
    assert carga_sql.publicar(conn, ventas, LOTE_V, audit_id=-1) is False  # y un segundo no duplica
    assert _contar(conn, "lab.ventas", LOTE_V) == 5
    assert _contar(conn, "lab.stg_ventas", LOTE_V) == 0      # staging se limpia en la misma transaccion

    ctl = {"cantidad_registros": 5, "sumatorias": {"cantidad": "15", "importe_total": "152.50"}}
    assert conciliacion.conciliar(conn, ventas, LOTE_V, ctl)["ok"]


def test_error_en_publicacion_revierte_todo(conn, clientes, ventas):
    """Una FK rota dentro de la transaccion: no queda ni una fila (XACT_ABORT ON)."""
    carga_sql.cargar_staging(conn, clientes, LOTE_C, CLIENTES)
    carga_sql.publicar(conn, clientes, LOTE_C, audit_id=-1)
    malas = [list(v) for v in VENTAS]
    malas[-1][1] = "999999"   # cliente inexistente en la ultima fila
    carga_sql.cargar_staging(conn, ventas, LOTE_V, malas)
    carga_sql.validar_staging(conn, ventas, LOTE_V, 5)        # conteo y PK OK; la FK a clientes...
    with pytest.raises(ErrorCalidad, match="referencias") as e:
        carga_sql.validar_referencias(conn, ventas, LOTE_V)   # ...se explica despues de la dependencia
    assert e.value.errores[0].valor == "999999"
    with pytest.raises(pyodbc.Error):
        carga_sql.publicar(conn, ventas, LOTE_V, audit_id=-1)  # ...y la FK es la red final
    assert _contar(conn, "lab.ventas", LOTE_V) == 0
    assert _contar(conn, "lab.stg_ventas", LOTE_V) == 5      # staging intacto para diagnosticar


def test_identificador_existente_en_otro_lote(conn, clientes):
    carga_sql.cargar_staging(conn, clientes, LOTE_C, CLIENTES)
    carga_sql.publicar(conn, clientes, LOTE_C, audit_id=-1)
    otro = "test.clientes-20990102-111111111111"
    carga_sql.cargar_staging(conn, clientes, otro, CLIENTES[:1])
    with pytest.raises(ErrorCalidad) as e:
        carga_sql.validar_staging(conn, clientes, otro, 1)
    assert "identificador existente" in e.value.errores[0].motivo
