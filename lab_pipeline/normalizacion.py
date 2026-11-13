"""Reglas de limpieza y validacion por tipo logico del contrato.

Cada funcion recibe el valor crudo (str) y la Columna, y devuelve el valor normalizado
como str (lo que se escribe en curated) o lanza ValorInvalido con el motivo.
Los errores se acumulan por registro y columna; nunca se corta en el primero.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .contrato import Columna, Contrato
from .errores import ErrorRegistro

NULOS = {"", "NULL", "N/A"}
VERDADEROS = {"sí", "si", "true", "1"}
FALSOS = {"no", "false", "0"}
RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RE_INT = re.compile(r"^-?\d+$")
FORMATOS_FECHA = (
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"), "%Y-%m-%d"),
    (re.compile(r"^\d{2}/\d{2}/\d{4}$"), "%d/%m/%Y"),
    (re.compile(r"^\d{2}-\d{2}-\d{4}$"), "%d-%m-%Y"),
)
INT_SQL_MIN, INT_SQL_MAX = -(2**31), 2**31 - 1


class ValorInvalido(ValueError):
    pass


def _rango(valor, col: Columna) -> None:
    if col.min is not None and valor < col.min:
        raise ValorInvalido(f"menor que el minimo {col.min}")
    if col.max is not None and valor > col.max:
        raise ValorInvalido(f"mayor que el maximo {col.max}")


def norm_text(v: str, col: Columna) -> str:
    v = v.strip()
    if col.largo_max is not None and len(v) > col.largo_max:
        raise ValorInvalido(f"largo {len(v)} supera el maximo {col.largo_max}")
    return v


def norm_email(v: str, col: Columna) -> str:
    v = v.strip().lower()
    if not RE_EMAIL.match(v):
        raise ValorInvalido("email con formato invalido")
    if len(v) > (col.largo_max or 254):
        raise ValorInvalido(f"email supera {col.largo_max or 254} caracteres")
    return v


def norm_code(v: str, col: Columna) -> str:
    v = v.strip().upper()
    if col.largo is not None and len(v) != col.largo:
        raise ValorInvalido(f"largo {len(v)}, se espera exactamente {col.largo}")
    if col.permitidos is not None and v not in col.permitidos:
        raise ValorInvalido(f"valor no permitido (permitidos: {', '.join(col.permitidos)})")
    return v


def norm_date(v: str, col: Columna) -> str:
    v = v.strip()
    for patron, formato in FORMATOS_FECHA:
        if patron.match(v):
            try:
                return datetime.strptime(v, formato).date().isoformat()
            except ValueError:
                raise ValorInvalido("fecha inexistente") from None
    raise ValorInvalido("formato de fecha no admitido (YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY)")


def norm_bool(v: str, col: Columna) -> str:
    v = v.strip().casefold()
    if v in VERDADEROS:
        return "1"
    if v in FALSOS:
        return "0"
    raise ValorInvalido("booleano no reconocido (si/sí/true/1, no/false/0)")


def norm_int(v: str, col: Columna) -> str:
    v = v.strip()
    if not RE_INT.match(v):
        raise ValorInvalido("no es un entero")
    n = int(v)
    if not INT_SQL_MIN <= n <= INT_SQL_MAX:
        raise ValorInvalido("fuera del rango de INT")
    _rango(n, col)
    return str(n)


def norm_decimal(v: str, col: Columna) -> str:
    v = v.strip()
    escala = col.escala if col.escala is not None else 2
    # Sin separador de miles y con a lo sumo `escala` decimales: 12,345 es un rechazo, no un redondeo.
    if not re.fullmatch(rf"\d+([.,]\d{{1,{escala}}})?", v):
        raise ValorInvalido(f"decimal invalido (sin separador de miles, hasta {escala} decimales)")
    d = Decimal(v.replace(",", "."))
    if col.precision is not None:
        digitos_enteros = len(str(int(d))) if int(d) else 0
        if digitos_enteros > col.precision - escala:
            raise ValorInvalido(f"excede DECIMAL({col.precision},{escala})")
    _rango(d, col)
    return f"{d:.{escala}f}"


NORMALIZADORES = {
    "text": norm_text,
    "email": norm_email,
    "code": norm_code,
    "date": norm_date,
    "bool": norm_bool,
    "int": norm_int,
    "decimal": norm_decimal,
}


def normalizar_valor(v: str, col: Columna) -> str:
    """'' / NULL / N/A solo se aceptan en columnas opcionales y se emiten como ''."""
    if v.strip().upper() in NULOS:
        if col.obligatorio:
            raise ValorInvalido("obligatorio vacio")
        return ""
    return NORMALIZADORES[col.tipo](v, col)


@dataclass
class ResultadoNormalizacion:
    filas: list[list[str]] = field(default_factory=list)
    errores: list[ErrorRegistro] = field(default_factory=list)


def normalizar_filas(contrato: Contrato, filas: list[list[str]]) -> ResultadoNormalizacion:
    """filas: registros sin encabezado, ya validados en cantidad de columnas."""
    res = ResultadoNormalizacion()
    for nro, fila in enumerate(filas, start=1):
        salida = []
        for col, valor in zip(contrato.columnas, fila):
            try:
                salida.append(normalizar_valor(valor, col))
            except ValorInvalido as e:
                res.errores.append(ErrorRegistro(nro, col.nombre, valor, str(e)))
                salida.append(valor)
        res.filas.append(salida)

    # Validaciones sobre el archivo completo
    if not filas:
        res.errores.append(ErrorRegistro(None, None, None, "archivo sin registros (solo encabezado)"))
    idx = [contrato.encabezado.index(c) for c in contrato.clave_primaria]
    vistos: dict[tuple, int] = {}
    for nro, fila in enumerate(res.filas, start=1):
        clave = tuple(fila[i] for i in idx)
        if clave in vistos:
            res.errores.append(ErrorRegistro(nro, ",".join(contrato.clave_primaria), "|".join(clave),
                                             f"clave duplicada (ya aparece en el registro {vistos[clave]})"))
        else:
            vistos[clave] = nro
    return res


def escribir_dat(encabezado: list[str], filas: list[list[str]]) -> bytes:
    """Mismo delimitador, QUOTE_MINIMAL, '\\n' y UTF-8 sin BOM."""
    buf = io.StringIO(newline="")
    w = csv.writer(buf, delimiter="|", quotechar='"', doublequote=True,
                   quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writerow(encabezado)
    w.writerows(filas)
    return buf.getvalue().encode("utf-8")
