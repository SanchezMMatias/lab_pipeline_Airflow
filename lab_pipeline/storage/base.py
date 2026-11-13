"""Interfaz minima de almacenamiento. local.py la implementa; luego azure.py (Blob) y gcs.py.

Las rutas son siempre relativas y con '/', por ejemplo 'raw/fecha=2026-11-09/lote=.../x.dat'.
"""
from __future__ import annotations

from typing import Protocol


class Storage(Protocol):
    def listar(self, prefijo: str) -> list[str]: ...

    def leer_bytes(self, ruta: str) -> bytes: ...

    def escribir_bytes(self, ruta: str, datos: bytes, sobrescribir: bool = False) -> None: ...

    def existe(self, ruta: str) -> bool: ...


def escribir_inmutable(storage: Storage, ruta: str, datos: bytes) -> None:
    """Escribe si no existe. Si ya existe con el mismo contenido no hace nada (reintento);
    si existe con otro contenido es un error: nunca se pisa un archivo de datos."""
    from ..errores import ErrorIntegridad

    if storage.existe(ruta):
        if storage.leer_bytes(ruta) == datos:
            return
        raise ErrorIntegridad(f"{ruta} ya existe con otro contenido", etapa="storage")
    storage.escribir_bytes(ruta, datos, sobrescribir=False)
