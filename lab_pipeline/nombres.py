"""Nombres de archivo, lote_id y rutas por zona."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from .errores import ErrorCalidad, ErrorRegistro

PATRON = re.compile(r"^([a-z0-9]+)_([a-z0-9]+)_(\d{8})\.dat$")


@dataclass(frozen=True)
class ArchivoEntrada:
    archivo: str
    schema: str
    tabla: str
    fecha: date

    @property
    def nombre_completo(self) -> str:
        return f"{self.schema}.{self.tabla}"


def parsear_nombre(archivo: str, contratos: dict | None = None) -> ArchivoEntrada:
    m = PATRON.match(archivo)
    if not m:
        raise ErrorCalidad("nombre de archivo invalido", [ErrorRegistro(None, None, archivo,
                           "se espera schema_tabla_YYYYMMDD.dat en minusculas")], etapa="recepcion")
    schema, tabla, yyyymmdd = m.groups()
    try:
        fecha = datetime.strptime(yyyymmdd, "%Y%m%d").date()
    except ValueError:
        raise ErrorCalidad("fecha del nombre invalida", [ErrorRegistro(None, None, archivo,
                           f"{yyyymmdd} no es una fecha real")], etapa="recepcion") from None
    info = ArchivoEntrada(archivo, schema, tabla, fecha)
    if contratos is not None and info.nombre_completo not in contratos:
        raise ErrorCalidad("tabla sin contrato", [ErrorRegistro(None, None, archivo,
                           f"{info.nombre_completo} no tiene YAML en config/tablas")], etapa="recepcion")
    return info


def nombre_archivo(schema: str, tabla: str, fecha: date) -> str:
    return f"{schema}_{tabla}_{fecha:%Y%m%d}.dat"


def calcular_lote_id(info: ArchivoEntrada, sha256: str) -> str:
    """Deterministico: mismo archivo -> mismo lote, y un reproceso cae en el mismo lugar."""
    return f"{info.nombre_completo}-{info.fecha:%Y%m%d}-{sha256[:12]}"


def nombre_ctl(archivo: str) -> str:
    return archivo[: -len(".dat")] + ".ctl" if archivo.endswith(".dat") else archivo + ".ctl"


def ruta_zona(zona: str, fecha: date, lote_id: str, nombre: str) -> str:
    return f"{zona}/fecha={fecha.isoformat()}/lote={lote_id}/{nombre}"


def rutas_lote(zonas: dict[str, str], info: ArchivoEntrada, lote_id: str) -> dict[str, str]:
    a, ctl = info.archivo, nombre_ctl(info.archivo)
    f = info.fecha
    return {
        "entrada": f"{zonas['entrada']}/{a}",
        "raw": ruta_zona(zonas["raw"], f, lote_id, a),
        "raw_ctl": ruta_zona(zonas["raw"], f, lote_id, ctl),
        "curated": ruta_zona(zonas["curated"], f, lote_id, a),
        "curated_ctl": ruta_zona(zonas["curated"], f, lote_id, ctl),
        "rejected": ruta_zona(zonas["rejected"], f, lote_id, a[: -len(".dat")] + ".errores.json"),
    }
