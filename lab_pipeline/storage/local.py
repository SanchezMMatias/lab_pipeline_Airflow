"""Storage sobre el sistema de archivos (un volumen compartido por todos los workers)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


class LocalStorage:
    def __init__(self, base: str | os.PathLike):
        self.base = Path(base).resolve()

    def _ruta(self, ruta: str) -> Path:
        p = (self.base / ruta).resolve()
        if p != self.base and self.base not in p.parents:
            raise ValueError(f"ruta fuera del storage: {ruta}")
        return p

    def listar(self, prefijo: str = "") -> list[str]:
        if not self.base.exists():
            return []
        salida = []
        for p in self.base.rglob("*"):
            if p.is_file() and not p.name.startswith(".tmp-"):
                rel = p.relative_to(self.base).as_posix()
                if rel.startswith(prefijo):
                    salida.append(rel)
        return sorted(salida)

    def leer_bytes(self, ruta: str) -> bytes:
        return self._ruta(ruta).read_bytes()

    def existe(self, ruta: str) -> bool:
        return self._ruta(ruta).is_file()

    def escribir_bytes(self, ruta: str, datos: bytes, sobrescribir: bool = False) -> None:
        """Escribe a un temporal en la misma carpeta y despues os.replace (atomico):
        un reintento o un corte nunca deja un archivo a medias en el destino."""
        destino = self._ruta(ruta)
        if not sobrescribir and destino.exists():
            raise FileExistsError(ruta)
        destino.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=destino.parent, prefix=".tmp-", suffix=".part")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(datos)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, destino)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
