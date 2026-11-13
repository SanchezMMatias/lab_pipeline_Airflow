"""Arma el correo de resumen desde las filas de audit_lote de un dag_run."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
from html import escape

from .auditoria import ESTADOS_OK

COLORES = {"CORRECTO": "#1a7f37", "YA_PROCESADO": "#57606a", "RECHAZADO": "#cf222e",
           "FALLIDO": "#cf222e", "CONFLICTO": "#bc4c00", "BLOQUEADO_DEPENDENCIA": "#bc4c00"}


def _dif(esp, obt):
    if esp is None or obt is None:
        return ""
    d = Decimal(obt) - Decimal(esp)
    return "0" if d == 0 else f"{d:+}"


def _v(x) -> str:
    return "" if x is None else escape(str(x))


def armar_resumen(filas: list[dict], dag_run_id: str, fecha_negocio: str, prefijo: str = "") -> tuple[str, str]:
    conteo = Counter(f["estado"] for f in filas)
    ok = bool(filas) and all(f["estado"] in ESTADOS_OK for f in filas)
    asunto = (f"{prefijo} {'OK' if ok else 'CON ERRORES'} - lab_archivos {fecha_negocio} - "
              + (", ".join(f"{k}={v}" for k, v in sorted(conteo.items())) or "sin archivos")).strip()

    filas_html = []
    for f in filas:
        color = COLORES.get(f["estado"], "#000")
        filas_html.append(
            "<tr>"
            f"<td>{_v(f['schema_destino'])}.{_v(f['tabla_destino'])}</td><td>{_v(f['archivo'])}</td>"
            f"<td style='color:{color};font-weight:bold'>{_v(f['estado'])}</td>"
            f"<td>{_v(f['registros_esp'])}</td><td>{_v(f['registros_obt'])}</td>"
            f"<td>{_dif(f['registros_esp'], f['registros_obt'])}</td>"
            f"<td>{_v(f['suma_cantidad_esp'])}</td><td>{_v(f['suma_cantidad_obt'])}</td>"
            f"<td>{_dif(f['suma_cantidad_esp'], f['suma_cantidad_obt'])}</td>"
            f"<td>{_v(f['suma_importe_esp'])}</td><td>{_v(f['suma_importe_obt'])}</td>"
            f"<td>{_dif(f['suma_importe_esp'], f['suma_importe_obt'])}</td>"
            f"<td>{_v(f['lote_id'])}</td><td>{_v(f['motivo'])}</td>"
            "</tr>")
    cuerpo = "\n".join(filas_html) or "<tr><td colspan='14'>No se registro ningun archivo en este run.</td></tr>"
    html = f"""<html><body style="font-family:sans-serif">
<h2>lab_archivos &mdash; fecha de negocio {escape(fecha_negocio)}</h2>
<p>dag_run_id: <code>{escape(dag_run_id)}</code><br>Resultado: <b>{'OK' if ok else 'CON ERRORES'}</b></p>
<table border="1" cellpadding="4" cellspacing="0" style="border-collapse:collapse;font-size:13px">
<tr style="background:#eee"><th>Tabla</th><th>Archivo</th><th>Estado</th>
<th>Reg. esp.</th><th>Reg. obt.</th><th>Dif.</th>
<th>Cant. esp.</th><th>Cant. obt.</th><th>Dif.</th>
<th>Importe esp.</th><th>Importe obt.</th><th>Dif.</th><th>Lote</th><th>Motivo</th></tr>
{cuerpo}
</table></body></html>"""
    return asunto, html
