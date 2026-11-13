"""Carga y valida los contratos de tabla (config/tablas/*.yaml).

Un contrato define columnas, orden, tipos y reglas de una tabla destino.
Es la unica fuente de verdad: el pipeline nunca infiere tipos a partir de los datos.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

TIPOS_VALIDOS = {"int", "decimal", "text", "email", "code", "date", "bool"}
TIPOS_SUMABLES = {"int", "decimal"}
DIR_TABLAS = Path(__file__).parent / "config" / "tablas"


class ContratoInvalido(ValueError):
    """La configuracion de una tabla es inconsistente. Es un error de desarrollo, no de datos."""


@dataclass(frozen=True)
class Columna:
    nombre: str
    tipo: str
    obligatorio: bool
    largo: int | None = None          # largo exacto (code)
    largo_max: int | None = None      # largo maximo (text, email)
    min: int | None = None
    max: int | None = None
    precision: int | None = None      # decimal
    escala: int | None = None         # decimal
    permitidos: tuple[str, ...] | None = None
    referencia: dict[str, str] | None = None


@dataclass(frozen=True)
class Contrato:
    schema: str
    tabla: str
    version_contrato: int
    columnas: tuple[Columna, ...]
    clave_primaria: tuple[str, ...]
    columnas_suma: tuple[str, ...] = ()
    depende_de: tuple[str, ...] = field(default_factory=tuple)

    @property
    def nombre_completo(self) -> str:
        return f"{self.schema}.{self.tabla}"

    @property
    def encabezado(self) -> list[str]:
        return [c.nombre for c in self.columnas]

    @property
    def cantidad_columnas(self) -> int:
        return len(self.columnas)

    def columna(self, nombre: str) -> Columna:
        for c in self.columnas:
            if c.nombre == nombre:
                return c
        raise KeyError(nombre)


def _columna_desde_dict(d: dict[str, Any], origen: str) -> Columna:
    faltan = {"nombre", "tipo", "obligatorio"} - d.keys()
    if faltan:
        raise ContratoInvalido(f"{origen}: columna sin {sorted(faltan)}: {d}")
    desconocidas = d.keys() - set(Columna.__dataclass_fields__)
    if desconocidas:
        raise ContratoInvalido(f"{origen}: columna {d['nombre']!r} con claves desconocidas {sorted(desconocidas)}")
    if d["tipo"] not in TIPOS_VALIDOS:
        raise ContratoInvalido(f"{origen}: columna {d['nombre']!r} con tipo desconocido {d['tipo']!r}")
    if d["tipo"] == "decimal" and (d.get("precision") is None or d.get("escala") is None):
        raise ContratoInvalido(f"{origen}: decimal {d['nombre']!r} requiere precision y escala")
    datos = dict(d)
    if datos.get("permitidos") is not None:
        datos["permitidos"] = tuple(str(v) for v in datos["permitidos"])
    return Columna(**datos)


def cargar_contrato(ruta: str | Path) -> Contrato:
    ruta = Path(ruta)
    with ruta.open(encoding="utf-8") as f:
        crudo = yaml.safe_load(f)
    origen = ruta.name

    for clave in ("schema", "tabla", "version_contrato", "columnas", "clave_primaria"):
        if clave not in crudo:
            raise ContratoInvalido(f"{origen}: falta '{clave}'")

    for parte in ("schema", "tabla"):
        if "_" in crudo[parte]:
            # El nombre de archivo es schema_tabla_YYYYMMDD.dat: un '_' extra lo haria ambiguo
            raise ContratoInvalido(f"{origen}: '{parte}' no puede contener '_'")

    columnas = tuple(_columna_desde_dict(c, origen) for c in crudo["columnas"])
    nombres = [c.nombre for c in columnas]
    if len(set(nombres)) != len(nombres):
        raise ContratoInvalido(f"{origen}: nombres de columna repetidos")

    for pk in crudo["clave_primaria"]:
        if pk not in nombres:
            raise ContratoInvalido(f"{origen}: clave_primaria {pk!r} no es una columna")

    for s in crudo.get("columnas_suma") or []:
        if s not in nombres:
            raise ContratoInvalido(f"{origen}: columnas_suma {s!r} no es una columna")
        col = next(c for c in columnas if c.nombre == s)
        if col.tipo not in TIPOS_SUMABLES:
            raise ContratoInvalido(f"{origen}: columnas_suma {s!r} no es numerica")
        if s in crudo["clave_primaria"] or col.referencia:
            raise ContratoInvalido(f"{origen}: columnas_suma {s!r} es un identificador")

    esperado = f"{crudo['schema']}_{crudo['tabla']}.yaml"
    if ruta.name != esperado:
        raise ContratoInvalido(f"{origen}: el archivo deberia llamarse {esperado}")

    return Contrato(
        schema=crudo["schema"],
        tabla=crudo["tabla"],
        version_contrato=int(crudo["version_contrato"]),
        columnas=columnas,
        clave_primaria=tuple(crudo["clave_primaria"]),
        columnas_suma=tuple(crudo.get("columnas_suma") or ()),
        depende_de=tuple(crudo.get("depende_de") or ()),
    )


def cargar_contratos(directorio: str | Path = DIR_TABLAS) -> dict[str, Contrato]:
    """Devuelve {'lab.clientes': Contrato, ...} y valida que las dependencias existan."""
    contratos = {}
    for ruta in sorted(Path(directorio).glob("*.yaml")):
        c = cargar_contrato(ruta)
        contratos[c.nombre_completo] = c
    if not contratos:
        raise ContratoInvalido(f"No hay contratos en {directorio}")
    for c in contratos.values():
        for dep in c.depende_de:
            if dep not in contratos:
                raise ContratoInvalido(f"{c.nombre_completo} depende de {dep}, que no tiene contrato")
        for col in c.columnas:
            if col.referencia and col.referencia["tabla"] not in contratos:
                raise ContratoInvalido(f"{c.nombre_completo}.{col.nombre} referencia una tabla sin contrato")
    return contratos


def orden_de_carga(contratos: dict[str, Contrato]) -> list[str]:
    """Ordena las tablas para que cada una se procese despues de sus dependencias."""
    orden, visitando = [], set()

    def visitar(nombre: str) -> None:
        if nombre in orden:
            return
        if nombre in visitando:
            raise ContratoInvalido(f"Dependencia circular en {nombre}")
        visitando.add(nombre)
        for dep in contratos[nombre].depende_de:
            visitar(dep)
        visitando.discard(nombre)
        orden.append(nombre)

    for nombre in sorted(contratos):
        visitar(nombre)
    return orden
