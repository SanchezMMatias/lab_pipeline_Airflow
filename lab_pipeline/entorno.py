"""Configuracion por entorno (config/entornos/<nombre>.yaml) y fabrica de storage.

El DAG nunca importa storage/local.py: pide crear_storage() y este elige segun el YAML.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .storage import Storage

DIR_ENTORNOS = Path(__file__).parent / "config" / "entornos"
ZONAS = ("entrada", "raw", "curated", "rejected")


@dataclass(frozen=True)
class Entorno:
    nombre: str
    storage_cfg: dict
    zonas: dict[str, str]
    conn_sql: str
    conn_correo: str
    destinatarios: tuple[str, ...]
    asunto_prefijo: str = ""

    def storage(self) -> Storage:
        return crear_storage(self.storage_cfg)


def cargar_entorno(nombre: str, directorio: str | Path = DIR_ENTORNOS) -> Entorno:
    ruta = Path(directorio) / f"{nombre}.yaml"
    if not ruta.is_file():
        raise ValueError(f"No existe el entorno {nombre!r} ({ruta.name})")
    d = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    zonas = d["storage"]["zonas"]
    faltan = set(ZONAS) - set(zonas)
    if faltan:
        raise ValueError(f"{ruta.name}: faltan zonas {sorted(faltan)}")
    return Entorno(
        nombre=d["entorno"],
        storage_cfg=d["storage"],
        zonas=zonas,
        conn_sql=d["conexiones"]["sql"],
        conn_correo=d["conexiones"]["correo"],
        destinatarios=tuple(d["correo"]["destinatarios"]),
        asunto_prefijo=d["correo"].get("asunto_prefijo", ""),
    )


def crear_storage(cfg: dict) -> Storage:
    tipo = cfg["tipo"]
    if tipo == "local":
        from .storage.local import LocalStorage
        return LocalStorage(cfg["base"])
    # Azure y Google: escribir storage/azure.py y storage/gcs.py y agregarlos aqui.
    raise NotImplementedError(f"storage {tipo!r} todavia no implementado")
