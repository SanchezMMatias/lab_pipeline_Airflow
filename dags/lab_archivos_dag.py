"""lab_archivos: solo orquestacion. Toda la logica esta en lab_pipeline (Python puro).

Un TaskGroup por tabla, generado desde config/tablas/*.yaml. Las tablas avanzan en paralelo
hasta staging; una tabla con depende_de espera la conciliacion de su dependencia antes de
publicar. El resumen y la verificacion final corren pase lo que pase (ALL_DONE).

Disparar con: airflow dags trigger lab_archivos --conf '{"fecha_negocio": "2026-11-09"}'
"""
from __future__ import annotations

import functools
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from airflow.sdk import Param, TaskGroup, TriggerRule, Variable, dag, get_current_context, task
from airflow.sdk.exceptions import AirflowFailException, AirflowSkipException

from lab_pipeline import auditoria, pasos
from lab_pipeline.contrato import cargar_contratos, orden_de_carga
from lab_pipeline.entorno import cargar_entorno
from lab_pipeline.errores import ErrorCalidad, LoteYaProcesado, SinArchivo

CONTRATOS = cargar_contratos()
ORDEN = orden_de_carga(CONTRATOS)


# --- helpers de la capa Airflow ------------------------------------------------------------

def _entorno():
    return cargar_entorno(Variable.get("lab_entorno", default="local"))


@contextmanager
def _sql(env):
    from airflow.providers.odbc.hooks.odbc import OdbcHook

    conn = OdbcHook(odbc_conn_id=env.conn_sql).get_conn()
    conn.timeout = 30  # timeout por sentencia: un SQL Server colgado no deja la tarea esperando para siempre
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _traducir(fn):
    """Excepciones del nucleo -> semantica de Airflow."""
    @functools.wraps(fn)
    def envoltura(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (LoteYaProcesado, SinArchivo) as e:
            raise AirflowSkipException(str(e)) from None
        except ErrorCalidad as e:
            # Sin reintentos. El mensaje no incluye valores de registros (estan en rejected/ y audit_error).
            raise AirflowFailException(f"{e.estado}: {e}") from None
    return envoltura


def _al_fallar(context):
    """on_failure_callback: si la tarea murio por un error tecnico (ya sin reintentos), la fila
    de auditoria no queda EN_PROCESO. No pisa estados ya informados (RECHAZADO, CONFLICTO...)."""
    ti = context["ti"]
    grupo = ti.task_id.split(".")[0]
    try:
        ctx = ti.xcom_pull(task_ids=f"{grupo}.recibir")
    except Exception:
        ctx = None
    if not ctx:
        return
    exc = context.get("exception")
    motivo = f"{ti.task_id}: {type(exc).__name__}: {exc}"
    with _sql(_entorno()) as conn:
        auditoria.marcar_fallido_si_abierto(conn, ctx["audit_id"], motivo)


def _contexto():
    c = get_current_context()
    return c, date.fromisoformat(c["params"]["fecha_negocio"])


def _paso(nombre_paso, necesita_storage=True):
    """Fabrica una tarea que llama a pasos.<nombre_paso>(storage, conn, contrato, ctx)."""
    @task(task_id=nombre_paso, on_failure_callback=_al_fallar)
    @_traducir
    def _t(tabla: str, ctx: dict) -> dict:
        env = _entorno()
        with _sql(env) as conn:
            return getattr(pasos, nombre_paso)(env.storage(), conn, CONTRATOS[tabla], ctx)
    return _t


# --- tareas --------------------------------------------------------------------------------

@task(on_failure_callback=_al_fallar)
@_traducir
def recibir(tabla: str) -> dict:
    c, fecha = _contexto()
    env = _entorno()
    with _sql(env) as conn:
        return pasos.recibir(env, env.storage(), conn, CONTRATOS[tabla], fecha, c["dag"].dag_id, c["run_id"])


@task(trigger_rule=TriggerRule.ALL_DONE, on_failure_callback=_al_fallar)
@_traducir
def verificar_dependencias(tabla: str) -> dict:
    """ALL_DONE: corre aunque la dependencia haya fallado, para poder marcar BLOQUEADO_DEPENDENCIA.
    Si la propia tabla no llego a staging, no hay nada que hacer."""
    c, _ = _contexto()
    grupo = c["ti"].task_id.split(".")[0]
    ctx = c["ti"].xcom_pull(task_ids=f"{grupo}.validar_staging")
    if not ctx:
        raise AirflowSkipException("la tabla no llego a staging")
    env = _entorno()
    with _sql(env) as conn:
        return pasos.verificar_dependencias(env.storage(), conn, CONTRATOS[tabla], ctx)


@task(on_failure_callback=_al_fallar)
@_traducir
def publicar(tabla: str, ctx: dict) -> dict:
    env = _entorno()
    demora = int(Variable.get("lab_demora_publicacion_s", default=0))  # solo escenario 9
    with _sql(env) as conn:
        return pasos.publicar(conn, CONTRATOS[tabla], ctx, demora)


@task(trigger_rule=TriggerRule.ALL_DONE)
def enviar_resumen() -> None:
    from airflow.providers.smtp.hooks.smtp import SmtpHook

    c, fecha = _contexto()
    env = _entorno()
    with _sql(env) as conn:
        asunto, html, filas = pasos.resumen(env, conn, c["run_id"], fecha.isoformat())
    destino = Variable.get("lab_mail_destinatario", default=None) or list(env.destinatarios)
    with SmtpHook(smtp_conn_id=env.conn_correo) as smtp:
        smtp.send_email_smtp(to=destino, subject=asunto, html_content=html)
    print(f"Resumen enviado: {asunto}")


@task(trigger_rule=TriggerRule.ALL_DONE)
@_traducir
def verificar_estado_final() -> None:
    """La trampa del estado final: si la unica hoja fuera el correo, el run quedaria success
    aunque fallara una carga. Esta tarea lo lee de audit_lote y falla si algo no quedo OK."""
    c, _ = _contexto()
    with _sql(_entorno()) as conn:
        filas = pasos.verificar_estado_final(conn, c["run_id"])
    for f in filas:
        print(f"{f['archivo']}: {f['estado']}")


a_raw = _paso("a_raw")
normalizar = _paso("normalizar")
validar_precarga = _paso("validar_precarga")
cargar_staging = _paso("cargar_staging")
validar_staging = _paso("validar_staging")
conciliar = _paso("conciliar")


DEFAULTS = {
    "owner": "lab",
    "retries": 3,
    "retry_delay": timedelta(minutes=1),
    "retry_exponential_backoff": True,
    "execution_timeout": timedelta(minutes=10),
}


@dag(
    dag_id="lab_archivos",
    schedule=None,
    start_date=datetime(2026, 11, 1),
    catchup=False,
    default_args=DEFAULTS,
    max_active_runs=1,
    tags=["lab"],
    params={"fecha_negocio": Param("2026-11-09", type="string", format="date",
                                   description="Fecha de negocio de los archivos a procesar")},
    doc_md=__doc__,
)
def lab_archivos():
    grupos, conciliaciones = [], {}
    for nombre in ORDEN:
        contrato = CONTRATOS[nombre]
        with TaskGroup(group_id=contrato.tabla) as grupo:
            ctx = recibir(nombre)
            ctx = a_raw(nombre, ctx)
            ctx = normalizar(nombre, ctx)
            ctx = validar_precarga(nombre, ctx)
            ctx = cargar_staging(nombre, ctx)
            staging_ok = validar_staging(nombre, ctx)
            if contrato.depende_de:
                listo = verificar_dependencias(nombre)
                staging_ok >> listo
                for dep in contrato.depende_de:
                    conciliaciones[dep] >> listo
                ctx = publicar(nombre, listo)
            else:
                ctx = publicar(nombre, staging_ok)
            conciliaciones[nombre] = conciliar(nombre, ctx)
        grupos.append(grupo)

    resumen = enviar_resumen()
    final = verificar_estado_final()
    grupos >> resumen >> final


lab_archivos()
