"""Archivos de control (.ctl), sha256, estructura, conteos y sumatorias."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from decimal import Decimal

from .contrato import Contrato
from .errores import ErrorCalidad, ErrorIntegridad, ErrorRegistro
from .nombres import ArchivoEntrada

BOM = b"\xef\xbb\xbf"
DELIMITADOR = "|"


def sha256_bytes(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def ahora_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ctl_a_bytes(ctl: dict) -> bytes:
    """Una sola linea JSON compacta, UTF-8 sin escapar acentos."""
    return (json.dumps(ctl, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def ctl_desde_bytes(datos: bytes) -> dict:
    return json.loads(datos.decode("utf-8"))


def parsear_estructura(datos: bytes, contrato: Contrato) -> list[list[str]]:
    """Valida UTF-8, BOM, encabezado, saltos de linea internos y cantidad de columnas.
    Devuelve los registros (sin encabezado). Lanza ErrorCalidad con todos los problemas."""
    def falla(motivo, valor=None):
        return ErrorCalidad("estructura invalida", [ErrorRegistro(None, None, valor, motivo)], etapa="estructura")

    if not datos:
        raise falla("archivo vacio (0 bytes)")
    if datos.startswith(BOM):
        raise falla("el archivo tiene BOM UTF-8")
    try:
        texto = datos.decode("utf-8")
    except UnicodeDecodeError as e:
        raise falla(f"UTF-8 invalido en el byte {e.start}") from None

    lector = csv.reader(io.StringIO(texto, newline=""), delimiter=DELIMITADOR, quotechar='"',
                        doublequote=True, strict=True)
    filas: list[list[str]] = []
    try:
        for fila in lector:
            filas.append(fila)
    except csv.Error as e:
        raise falla(f"CSV mal formado cerca de la linea {lector.line_num}: {e}") from None

    if not filas:
        raise falla("archivo sin encabezado")
    errores = []
    if filas[0] != contrato.encabezado:
        errores.append(ErrorRegistro(0, None, DELIMITADOR.join(filas[0]),
                                     f"encabezado distinto al contrato: {DELIMITADOR.join(contrato.encabezado)}"))
    n = contrato.cantidad_columnas
    for nro, fila in enumerate(filas[1:], start=1):
        if any("\n" in c or "\r" in c for c in fila):
            errores.append(ErrorRegistro(nro, None, None, "salto de linea dentro de un campo"))
        elif len(fila) != n:
            errores.append(ErrorRegistro(nro, None, None, f"tiene {len(fila)} columnas, se esperan {n}"))
    if errores:
        raise ErrorCalidad(f"estructura invalida ({len(errores)} problemas)", errores, etapa="estructura")
    return filas[1:]


def calcular_sumas(contrato: Contrato, filas_normalizadas: list[list[str]]) -> dict[str, str]:
    """Sumatorias con Decimal, como string para no perder precision en el JSON."""
    sumas = {}
    for nombre in contrato.columnas_suma:
        col = contrato.columna(nombre)
        i = contrato.encabezado.index(nombre)
        total = sum((Decimal(f[i]) for f in filas_normalizadas if f[i] != ""), Decimal(0))
        sumas[nombre] = str(int(total)) if col.tipo == "int" else f"{total:.{col.escala}f}"
    return sumas


def control_raw(info: ArchivoEntrada, contrato: Contrato, lote_id: str, datos: bytes,
                registros: int) -> dict:
    return {
        "archivo": info.archivo,
        "schema": info.schema,
        "tabla": info.tabla,
        "fecha_negocio": info.fecha.isoformat(),
        "lote_id": lote_id,
        "version_contrato": contrato.version_contrato,
        "sha256": sha256_bytes(datos),
        "bytes": len(datos),
        "encoding": "UTF-8",
        "delimitador": DELIMITADOR,
        "columnas": contrato.encabezado,
        "cantidad_registros": registros,
        "timestamp_proceso": ahora_utc_iso(),
    }


def control_curated(ctl_raw: dict, contrato: Contrato, datos_curated: bytes,
                    filas_normalizadas: list[list[str]]) -> dict:
    ctl = dict(ctl_raw)
    ctl.update({
        "archivo_origen": ctl_raw["archivo"],
        "sha256_origen": ctl_raw["sha256"],
        "sha256": sha256_bytes(datos_curated),
        "bytes": len(datos_curated),
        "cantidad_registros": len(filas_normalizadas),
        "sumatorias": calcular_sumas(contrato, filas_normalizadas),
        "timestamp_proceso": ahora_utc_iso(),
    })
    return ctl


def validar_precarga(contrato: Contrato, datos_curated: bytes, ctl_curated: dict, ctl_raw: dict) -> None:
    """Relee el curated y lo compara contra su .ctl y contra el control raw.
    Detecta un control alterado o un archivo modificado despues de generarlo."""
    errores = []

    def err(motivo, esperado, obtenido):
        errores.append(ErrorRegistro(None, None, f"esperado={esperado} obtenido={obtenido}", motivo))

    sha = sha256_bytes(datos_curated)
    if sha != ctl_curated.get("sha256"):
        err("sha256 del curated no coincide con su .ctl", ctl_curated.get("sha256"), sha)
    try:
        filas = parsear_estructura(datos_curated, contrato)
    except ErrorCalidad as e:
        raise ErrorIntegridad("el curated no respeta la estructura", e.errores, etapa="precarga") from None
    if len(filas) != ctl_curated.get("cantidad_registros"):
        err("conteo del curated distinto al .ctl", ctl_curated.get("cantidad_registros"), len(filas))
    sumas = calcular_sumas(contrato, filas)
    if sumas != ctl_curated.get("sumatorias"):
        err("sumatorias del curated distintas al .ctl", ctl_curated.get("sumatorias"), sumas)
    for clave, esperado in (("columnas", ctl_raw.get("columnas")),
                            ("cantidad_registros", ctl_raw.get("cantidad_registros")),
                            ("lote_id", ctl_raw.get("lote_id")),
                            ("sha256_origen", ctl_raw.get("sha256"))):
        if ctl_curated.get(clave) != esperado:
            err(f"{clave} del .ctl curated distinto al control raw", esperado, ctl_curated.get(clave))
    if ctl_curated.get("columnas") != contrato.encabezado:
        err("columnas del .ctl distintas al contrato", contrato.encabezado, ctl_curated.get("columnas"))
    if errores:
        raise ErrorIntegridad(f"validacion pre-carga fallida ({len(errores)} diferencias)", errores,
                              etapa="precarga")
