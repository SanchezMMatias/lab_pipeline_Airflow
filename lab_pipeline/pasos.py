"""Una funcion por tarea del DAG. Python puro: recibe storage, conexion SQL y contrato.

Cada paso recibe y devuelve un dict chico (ctx) con rutas, lote_id, audit_id y estado:
es lo unico que viaja por XCom. Ante un ErrorCalidad el paso deja la fila de auditoria en
su estado final (RECHAZADO, FALLIDO, ...), escribe el detalle en rejected/ y relanza.
"""
from __future__ import annotations

import json
import logging
from datetime import date

from . import auditoria, carga_sql, conciliacion, control
from .contrato import Contrato
from .entorno import Entorno
from .errores import (BloqueadoDependencia, ConflictoArchivo, ErrorCalidad, ErrorConciliacion,
                      ErrorRegistro, ErrorTransitorio, LoteYaProcesado, SinArchivo)
from .nombres import ArchivoEntrada, calcular_lote_id, nombre_archivo, parsear_nombre, rutas_lote
from .normalizacion import escribir_dat, normalizar_filas
from .resumen import armar_resumen
from .storage import Storage
from .storage.base import escribir_inmutable

log = logging.getLogger(__name__)


def _info(ctx: dict) -> ArchivoEntrada:
    return parsear_nombre(ctx["archivo"])


def _rechazar(storage: Storage, conn, ctx: dict, err: ErrorCalidad) -> None:
    """Deja evidencia en rejected/ y en auditoria. No loguea valores de registros."""
    if err.errores:
        detalle = {"archivo": ctx["archivo"], "lote_id": ctx["lote_id"], "etapa": err.etapa,
                   "estado": err.estado, "motivo": str(err), "cantidad_errores": len(err.errores),
                   "errores": [e.a_dict() for e in err.errores]}
        storage.escribir_bytes(ctx["rutas"]["rejected"],
                               json.dumps(detalle, ensure_ascii=False, indent=2).encode("utf-8"),
                               sobrescribir=True)
    auditoria.registrar_errores(conn, ctx["audit_id"], err.errores)
    auditoria.actualizar(conn, ctx["audit_id"], estado=err.estado, motivo=err.motivo_detallado(), fin=True)
    log.warning("%s %s: %s (%d errores)", ctx["archivo"], err.estado, err, len(err.errores))


def _con_rechazo(storage, conn, ctx, funcion):
    try:
        return funcion()
    except ErrorCalidad as e:
        _rechazar(storage, conn, ctx, e)
        raise


# --- 1. recepcion e idempotencia -------------------------------------------------------

def recibir(env: Entorno, storage: Storage, conn, contrato: Contrato, fecha: date,
            dag_id: str, dag_run_id: str) -> dict:
    archivo = nombre_archivo(contrato.schema, contrato.tabla, fecha)
    ruta = f"{env.zonas['entrada']}/{archivo}"
    if not storage.existe(ruta):
        raise SinArchivo(f"no llego {archivo}")
    datos = storage.leer_bytes(ruta)
    sha = control.sha256_bytes(datos)
    info = parsear_nombre(archivo)
    lote_id = calcular_lote_id(info, sha)

    estado, reutilizar = auditoria.decidir_recepcion(auditoria.previos(conn, archivo), sha, dag_run_id)
    if estado == "YA_PROCESADO":
        aid = auditoria.insertar(conn, info, lote_id, sha, dag_id, dag_run_id, estado,
                                 "mismo archivo (nombre y sha256) ya procesado correctamente", terminal=True)
        raise LoteYaProcesado(f"{archivo} ya procesado (audit_id {aid})")
    if estado == "CONFLICTO":
        aid = auditoria.insertar(conn, info, lote_id, sha, dag_id, dag_run_id, estado,
                                 "mismo nombre que un archivo ya registrado pero con otro sha256: "
                                 "no se toca raw ni SQL", terminal=True)
        raise ConflictoArchivo(f"{archivo}: mismo nombre con contenido distinto (audit_id {aid})",
                               [ErrorRegistro(None, None, sha, "sha256 distinto al registrado")],
                               etapa="recepcion")
    aid = reutilizar or auditoria.insertar(conn, info, lote_id, sha, dag_id, dag_run_id, "EN_PROCESO")
    log.info("%s recibido: lote %s, audit_id %s", archivo, lote_id, aid)
    return {"archivo": archivo, "tabla": contrato.nombre_completo, "fecha": fecha.isoformat(),
            "sha256": sha, "lote_id": lote_id, "audit_id": aid,
            "rutas": rutas_lote(env.zonas, info, lote_id), "estado": "EN_PROCESO"}


# --- 2. raw + control original ----------------------------------------------------------

def a_raw(storage: Storage, conn, contrato: Contrato, ctx: dict) -> dict:
    def paso():
        r = ctx["rutas"]
        datos = storage.leer_bytes(r["entrada"])
        if control.sha256_bytes(datos) != ctx["sha256"]:
            raise ErrorTransitorio("el archivo de entrada cambio desde la recepcion")
        escribir_inmutable(storage, r["raw"], datos)
        copia = storage.leer_bytes(r["raw"])
        if control.sha256_bytes(copia) != ctx["sha256"]:
            raise ErrorTransitorio("el sha256 de la copia raw no coincide con el origen")
        filas = control.parsear_estructura(copia, contrato)
        ctl = control.control_raw(_info(ctx), contrato, ctx["lote_id"], copia, len(filas))
        storage.escribir_bytes(r["raw_ctl"], control.ctl_a_bytes(ctl), sobrescribir=True)
        log.info("raw OK: %d registros", len(filas))
        return {**ctx, "registros_raw": len(filas)}
    return _con_rechazo(storage, conn, ctx, paso)


# --- 3. normalizacion + control curated -------------------------------------------------

def normalizar(storage: Storage, conn, contrato: Contrato, ctx: dict) -> dict:
    def paso():
        r = ctx["rutas"]
        ctl_raw = control.ctl_desde_bytes(storage.leer_bytes(r["raw_ctl"]))
        filas = control.parsear_estructura(storage.leer_bytes(r["raw"]), contrato)
        res = normalizar_filas(contrato, filas)
        if res.errores:
            raise ErrorCalidad(f"{len(res.errores)} errores de normalizacion", res.errores, etapa="normalizacion")
        datos = escribir_dat(contrato.encabezado, res.filas)
        escribir_inmutable(storage, r["curated"], datos)
        ctl = control.control_curated(ctl_raw, contrato, datos, res.filas)
        storage.escribir_bytes(r["curated_ctl"], control.ctl_a_bytes(ctl), sobrescribir=True)
        campos = {"sha256_curated": ctl["sha256"], "registros_esp": ctl["cantidad_registros"]}
        for col, valor in ctl["sumatorias"].items():
            if col in auditoria.MAPA_SUMAS:
                campos[auditoria.MAPA_SUMAS[col] + "_esp"] = valor
        auditoria.actualizar(conn, ctx["audit_id"], **campos)
        log.info("curated OK: %d registros", len(res.filas))
        return {**ctx, "registros": len(res.filas)}
    return _con_rechazo(storage, conn, ctx, paso)


# --- 4. validacion pre-carga --------------------------------------------------------------

def validar_precarga(storage: Storage, conn, contrato: Contrato, ctx: dict) -> dict:
    def paso():
        r = ctx["rutas"]
        control.validar_precarga(
            contrato,
            storage.leer_bytes(r["curated"]),
            control.ctl_desde_bytes(storage.leer_bytes(r["curated_ctl"])),
            control.ctl_desde_bytes(storage.leer_bytes(r["raw_ctl"])))
        return ctx
    return _con_rechazo(storage, conn, ctx, paso)


# --- 5. staging ---------------------------------------------------------------------------

def cargar_staging(storage: Storage, conn, contrato: Contrato, ctx: dict) -> dict:
    filas = control.parsear_estructura(storage.leer_bytes(ctx["rutas"]["curated"]), contrato)
    n = carga_sql.cargar_staging(conn, contrato, ctx["lote_id"], filas)
    log.info("staging: %d filas", n)
    return ctx


def validar_staging(storage: Storage, conn, contrato: Contrato, ctx: dict) -> dict:
    def paso():
        ctl = control.ctl_desde_bytes(storage.leer_bytes(ctx["rutas"]["curated_ctl"]))
        carga_sql.validar_staging(conn, contrato, ctx["lote_id"], ctl["cantidad_registros"])
        return ctx
    return _con_rechazo(storage, conn, ctx, paso)


# --- 6. dependencias y publicacion -----------------------------------------------------------

def verificar_dependencias(storage: Storage, conn, contrato: Contrato, ctx: dict) -> dict:
    """Si una tabla de la que dependemos tuvo archivo ese dia y no quedo OK, no se publica.
    Si quedo OK (o no llego archivo), se validan aca las FK hacia ella: recien ahora estan
    publicados los registros nuevos del mismo dia."""
    def paso():
        fecha = date.fromisoformat(ctx["fecha"])
        for dep in contrato.depende_de:
            schema, tabla = dep.split(".")
            estado = auditoria.ultimo_estado(conn, schema, tabla, fecha)
            if estado is not None and estado not in auditoria.ESTADOS_OK:
                raise BloqueadoDependencia(
                    f"{dep} del {fecha} quedo {estado}",
                    [ErrorRegistro(None, None, estado, f"{dep} del {fecha} no quedo CORRECTO")],
                    etapa="dependencias")
        carga_sql.validar_referencias(conn, contrato, ctx["lote_id"])
        return ctx
    return _con_rechazo(storage, conn, ctx, paso)


def publicar(conn, contrato: Contrato, ctx: dict, demora_s: int = 0) -> dict:
    ahora = carga_sql.publicar(conn, contrato, ctx["lote_id"], ctx["audit_id"], demora_s)
    if not ahora:
        # Un intento anterior ya hizo commit: no duplicar y seguir a conciliar.
        auditoria.actualizar(conn, ctx["audit_id"], estado="PUBLICADO")
        log.info("lote ya estaba publicado: no se reinserta")
    return {**ctx, "estado": "PUBLICADO"}


# --- 7. conciliacion ------------------------------------------------------------------------

def conciliar(storage: Storage, conn, contrato: Contrato, ctx: dict) -> dict:
    def paso():
        ctl = control.ctl_desde_bytes(storage.leer_bytes(ctx["rutas"]["curated_ctl"]))
        res = conciliacion.conciliar(conn, contrato, ctx["lote_id"], ctl)
        campos = {"registros_esp": int(res["esperado"]["registros"]),
                  "registros_obt": int(res["obtenido"]["registros"])}
        for col in contrato.columnas_suma:
            if col in auditoria.MAPA_SUMAS:
                base = auditoria.MAPA_SUMAS[col]
                campos[base + "_esp"] = res["esperado"][col]
                campos[base + "_obt"] = res["obtenido"][col]
        auditoria.actualizar(conn, ctx["audit_id"], **campos)
        if not res["ok"]:
            difs = ", ".join(f"{k}: esperado {res['esperado'][k]} obtenido {res['obtenido'][k]} "
                             f"(dif {v:+})" for k, v in res["diferencias"].items())
            raise ErrorConciliacion(f"diferencia SQL vs control: {difs}", etapa="conciliacion")
        auditoria.registrar_errores(conn, ctx["audit_id"], [])
        auditoria.actualizar(conn, ctx["audit_id"], estado="CORRECTO", motivo=None, fin=True)
        return {**ctx, "estado": "CORRECTO"}
    return _con_rechazo(storage, conn, ctx, paso)


# --- 8. resumen y estado final ----------------------------------------------------------------

def resumen(env: Entorno, conn, dag_run_id: str, fecha_negocio: str) -> tuple[str, str, list[dict]]:
    filas = auditoria.filas_del_run(conn, dag_run_id)
    asunto, html = armar_resumen(filas, dag_run_id, fecha_negocio, env.asunto_prefijo)
    return asunto, html, filas


def verificar_estado_final(conn, dag_run_id: str) -> list[dict]:
    """Lee los estados desde audit_lote (en Airflow 3 las tareas no consultan la metadata DB)."""
    filas = auditoria.filas_del_run(conn, dag_run_id)
    if not filas:
        raise ErrorCalidad("no se registro ningun archivo en este run", etapa="final")
    malas = [f for f in filas if f["estado"] not in auditoria.ESTADOS_OK]
    if malas:
        raise ErrorCalidad("estado final con errores: " + ", ".join(
            f"{f['archivo']}={f['estado']}" for f in malas), etapa="final")
    return filas
