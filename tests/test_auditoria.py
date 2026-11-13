from lab_pipeline.auditoria import Previo, decidir_recepcion
from lab_pipeline.entorno import cargar_entorno
from lab_pipeline.resumen import armar_resumen


def P(i, sha, estado, run="r0"):
    return Previo(i, sha, estado, run)


def test_nombre_nuevo():
    assert decidir_recepcion([], "a", "r1") == ("EN_PROCESO", None)


def test_mismo_archivo_ya_correcto():
    assert decidir_recepcion([P(1, "a", "CORRECTO")], "a", "r1") == ("YA_PROCESADO", None)


def test_mismo_nombre_otro_contenido():
    assert decidir_recepcion([P(1, "a", "CORRECTO")], "b", "r1") == ("CONFLICTO", None)
    assert decidir_recepcion([P(1, "a", "RECHAZADO")], "b", "r1") == ("CONFLICTO", None)


def test_reintento_tras_falla():
    assert decidir_recepcion([P(1, "a", "FALLIDO")], "a", "r2") == ("EN_PROCESO", None)


def test_un_conflicto_previo_no_bloquea_el_original():
    previos = [P(1, "a", "CORRECTO"), P(2, "b", "CONFLICTO")]
    assert decidir_recepcion(previos, "a", "r3") == ("YA_PROCESADO", None)


def test_reintento_de_recepcion_en_el_mismo_run_reutiliza_la_fila():
    assert decidir_recepcion([P(7, "a", "EN_PROCESO", "r1")], "a", "r1") == ("EN_PROCESO", 7)


def test_resumen_marca_errores_y_escapa_html():
    filas = [{
        "audit_id": 1, "archivo": "lab_ventas_20261109.dat", "schema_destino": "lab", "tabla_destino": "ventas",
        "fecha_negocio": "2026-11-09", "lote_id": "l", "estado": "FALLIDO", "registros_esp": 100,
        "registros_obt": 100, "suma_cantidad_esp": 633, "suma_cantidad_obt": 633,
        "suma_importe_esp": "1207807.85", "suma_importe_obt": "1207808.85", "motivo": "<b>dif</b>",
        "inicio_utc": None, "fin_utc": None}]
    asunto, html = armar_resumen(filas, "run1", "2026-11-09", "[x]")
    assert "CON ERRORES" in asunto and "FALLIDO=1" in asunto
    assert "+1.00" in html and "&lt;b&gt;dif&lt;/b&gt;" in html


def test_entorno_local():
    env = cargar_entorno("local")
    assert env.storage_cfg["tipo"] == "local" and env.conn_correo == "smtp_mailpit"
