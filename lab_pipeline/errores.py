"""Excepciones propias del nucleo.

La capa de Airflow las traduce:
  ErrorCalidad (y subclases)  -> AirflowFailException (falla sin reintentar)
  LoteYaProcesado / SinArchivo -> AirflowSkipException
  cualquier otra (pyodbc, I/O)  -> se deja subir y aplican los retries
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

MAX_MOTIVO = 4000


@dataclass(frozen=True)
class ErrorRegistro:
    """Un error puntual: (numero_registro, columna, valor_original, motivo)."""

    registro: int | None
    columna: str | None
    valor: str | None
    motivo: str

    def a_dict(self) -> dict:
        return asdict(self)


class ErrorPipeline(Exception):
    """Base de todas las excepciones del nucleo."""


class ErrorCalidad(ErrorPipeline):
    """Los datos no cumplen el contrato. Reintentar no lo arregla."""

    estado = "RECHAZADO"

    def __init__(self, mensaje: str, errores: list[ErrorRegistro] | None = None, etapa: str = ""):
        super().__init__(mensaje)
        self.errores = list(errores or [])
        self.etapa = etapa

    def motivo_detallado(self, maximo: int = 20) -> str:
        """Texto para audit_lote.motivo y el correo (no para los logs: puede incluir valores)."""
        partes = [f"[{self.etapa}] {self}" if self.etapa else str(self)]
        for e in self.errores[:maximo]:
            donde = f"reg {e.registro}" if e.registro is not None else "archivo"
            if e.columna:
                donde += f", {e.columna}"
            valor = f" (valor: {e.valor!r})" if e.valor is not None else ""
            partes.append(f"{donde}: {e.motivo}{valor}")
        if len(self.errores) > maximo:
            partes.append(f"... y {len(self.errores) - maximo} errores mas")
        return "; ".join(partes)[:MAX_MOTIVO]


class ErrorIntegridad(ErrorCalidad):
    """Un control no coincide con el archivo (alterado o modificado despues de generarlo)."""

    estado = "FALLIDO"


class ErrorConciliacion(ErrorCalidad):
    """Lo publicado en SQL no coincide con el control curated."""

    estado = "FALLIDO"


class ConflictoArchivo(ErrorCalidad):
    """Mismo nombre de archivo que uno ya registrado, con contenido distinto."""

    estado = "CONFLICTO"


class BloqueadoDependencia(ErrorCalidad):
    """Una tabla de la que dependemos no quedo correcta para la misma fecha."""

    estado = "BLOQUEADO_DEPENDENCIA"


class ErrorTransitorio(ErrorPipeline):
    """Falla tecnica que puede resolverse reintentando (I/O, verificacion de copia)."""


class LoteYaProcesado(ErrorPipeline):
    """Mismo archivo (nombre y sha256) ya quedo CORRECTO: se saltean las tareas siguientes."""


class SinArchivo(ErrorPipeline):
    """No llego archivo para esa tabla y fecha: el grupo se saltea."""
