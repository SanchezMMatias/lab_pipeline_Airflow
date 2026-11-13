import hashlib
import json
from datetime import date, datetime

import pytest

from lab_pipeline import control
from lab_pipeline.errores import ErrorCalidad, ErrorIntegridad
from lab_pipeline.nombres import calcular_lote_id, parsear_nombre, rutas_lote
from lab_pipeline.normalizacion import escribir_dat, normalizar_filas
from lab_pipeline.storage.base import escribir_inmutable
from lab_pipeline.storage.local import LocalStorage

from conftest import DATOS

ENC_V = b"venta_id|cliente_id|fecha_venta|cantidad|importe_total|moneda|observacion\n"


def test_sha256_contra_hashlib():
    datos = "hola|mundo\ná".encode("utf-8")
    assert control.sha256_bytes(datos) == hashlib.sha256(datos).hexdigest()
    assert control.sha256_bytes(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_conteo_sin_encabezado_y_sumas_decimal(ventas):
    datos = ENC_V + b"1|1|2026-11-09|2|0.10|ARS|\n2|1|2026-11-09|3|0.20|ARS|x\n"
    filas = control.parsear_estructura(datos, ventas)
    assert len(filas) == 2
    # con float daria 0.30000000000000004
    assert control.calcular_sumas(ventas, filas) == {"cantidad": "5", "importe_total": "0.30"}


@pytest.mark.parametrize("datos,motivo", [
    (b"", "0 bytes"),
    (b"\xef\xbb\xbf" + ENC_V, "BOM"),
    (ENC_V + b"1|1|2026-11-09|2|\xff|ARS|\n", "UTF-8 invalido"),
    (b"venta_id|cliente|fecha_venta|cantidad|importe_total|moneda|observacion\n", "encabezado"),
    (ENC_V + b"1|1|2026-11-09|2|1.00|ARS\n", "6 columnas"),
    (ENC_V + b"1|1|2026-11-09|2|1.00|ARS||extra\n", "8 columnas"),
    (ENC_V + b'1|1|2026-11-09|2|1.00|ARS|"linea\nnueva"\n', "salto de linea"),
    (ENC_V + b'1|1|2026-11-09|2|1.00|ARS|"abierta\n', "CSV mal formado"),
])
def test_estructura_invalida(ventas, datos, motivo):
    with pytest.raises(ErrorCalidad) as e:
        control.parsear_estructura(datos, ventas)
    assert any(motivo in x.motivo for x in e.value.errores), e.value.errores


def _armar(ventas):
    info = parsear_nombre("lab_ventas_20261109.dat")
    original = (DATOS / "validos" / "originales" / info.archivo).read_bytes()
    filas = control.parsear_estructura(original, ventas)
    lote = calcular_lote_id(info, control.sha256_bytes(original))
    ctl_raw = control.control_raw(info, ventas, lote, original, len(filas))
    res = normalizar_filas(ventas, filas)
    curated = escribir_dat(ventas.encabezado, res.filas)
    ctl_cur = control.control_curated(ctl_raw, ventas, curated, res.filas)
    return info, lote, ctl_raw, curated, ctl_cur


def test_ctl_una_linea_utc_y_sumatorias(ventas):
    info, lote, ctl_raw, curated, ctl_cur = _armar(ventas)
    b = control.ctl_a_bytes(ctl_cur)
    assert b.count(b"\n") == 1 and b.endswith(b"\n")
    leido = json.loads(b)
    assert datetime.fromisoformat(leido["timestamp_proceso"]).utcoffset().total_seconds() == 0
    assert leido["timestamp_proceso"].endswith("+00:00")
    assert leido["sumatorias"] == {"cantidad": "633", "importe_total": "1207807.85"}  # = manifiesto verificado
    assert leido["sha256_origen"] == ctl_raw["sha256"] and leido["archivo_origen"] == info.archivo
    assert lote == f"lab.ventas-20261109-{ctl_raw['sha256'][:12]}"
    control.validar_precarga(ventas, curated, leido, ctl_raw)  # no lanza


def test_un_byte_modificado_hace_fallar_la_precarga(ventas):
    _, _, ctl_raw, curated, ctl_cur = _armar(ventas)
    alterado = curated.replace(b"|45.34|", b"|45.35|", 1)
    assert alterado != curated
    with pytest.raises(ErrorIntegridad, match="pre-carga"):
        control.validar_precarga(ventas, alterado, ctl_cur, ctl_raw)


def test_ctl_alterado_hace_fallar_la_precarga(ventas):
    _, _, ctl_raw, curated, ctl_cur = _armar(ventas)
    ctl_cur["cantidad_registros"] = 99
    with pytest.raises(ErrorIntegridad) as e:
        control.validar_precarga(ventas, curated, ctl_cur, ctl_raw)
    assert any("conteo" in x.motivo for x in e.value.errores)


def test_local_storage_atomico_y_sin_sobrescribir(tmp_path):
    s = LocalStorage(tmp_path)
    s.escribir_bytes("raw/a/b.dat", b"uno")
    assert s.existe("raw/a/b.dat") and s.leer_bytes("raw/a/b.dat") == b"uno"
    with pytest.raises(FileExistsError):
        s.escribir_bytes("raw/a/b.dat", b"dos")
    s.escribir_bytes("raw/a/b.dat", b"dos", sobrescribir=True)
    assert s.leer_bytes("raw/a/b.dat") == b"dos"
    assert s.listar("raw/") == ["raw/a/b.dat"]           # sin temporales
    escribir_inmutable(s, "raw/a/b.dat", b"dos")         # reintento con mismo contenido: OK
    with pytest.raises(ErrorIntegridad):
        escribir_inmutable(s, "raw/a/b.dat", b"tres")
    with pytest.raises(ValueError):
        s.leer_bytes("../fuera.txt")


@pytest.mark.parametrize("nombre", ["lab_ventas_20260231.dat", "Lab_ventas_20261109.dat",
                                    "lab_ventas_2026119.dat", "lab_ventas_20261109.csv",
                                    "lab_productos_20261109.dat"])
def test_nombres_invalidos(contratos, nombre):
    with pytest.raises(ErrorCalidad):
        parsear_nombre(nombre, contratos)


def test_rutas_por_zona():
    info = parsear_nombre("lab_ventas_20261109.dat")
    r = rutas_lote({"entrada": "entrada", "raw": "raw", "curated": "curated", "rejected": "rejected"},
                   info, "lab.ventas-20261109-abc")
    assert info.fecha == date(2026, 11, 9)
    assert r["raw_ctl"] == "raw/fecha=2026-11-09/lote=lab.ventas-20261109-abc/lab_ventas_20261109.ctl"
    assert r["rejected"].endswith("/lab_ventas_20261109.errores.json")
