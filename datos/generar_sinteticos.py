"""Genera los datos sinteticos del laboratorio (respuesta a datos/prompts/01 y 02).

Parte de los valores LIMPIOS (la verdad), escribe el normalizado esperado con csv.writer y
"ensucia" cada valor con una anomalia corregible para producir el original. No importa nada de
lab_pipeline: el esperado es independiente del codigo que se esta probando.

Uso:  python datos/generar_sinteticos.py      (semilla fija: siempre genera los mismos bytes)
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).parent
SEMILLA = 20261109
ENC_CLIENTES = ["cliente_id", "nombre", "email", "fecha_alta", "pais_codigo", "activo"]
ENC_VENTAS = ["venta_id", "cliente_id", "fecha_venta", "cantidad", "importe_total", "moneda", "observacion"]

NOMBRES = ["José Pérez", "María Gómez", "Lucía Fernández", "Martín Rodríguez", "Sofía López",
           "Julián Martínez", "Valentina Díaz", "Tomás Álvarez", "Camila Romero", "Mateo Sánchez",
           "Agustina Torres", "Benjamín Ruiz", "Florencia Castro", "Ignacio Núñez", "Renata Ortiz",
           "Facundo Molina", "Martina Suárez", "Santiago Rojas", "Paula Herrera", "Nicolás Peña"]
OBSERVACIONES = ["Entrega en sucursal", "Cliente pidió factura A", "Pago con transferencia",
                 "Retira el sábado", "Envío a domicilio", 'Pedido "urgente"', 'Producto "en oferta"']


def _sin_tildes(s: str) -> str:
    return s.translate(str.maketrans("áéíóúÁÉÍÓÚñÑ", "aeiouAEIOUnN"))


def dat_limpio(encabezado, filas) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, delimiter="|", quotechar='"', quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writerow(encabezado)
    w.writerows(filas)
    return buf.getvalue().encode("utf-8")


def dat_sucio(encabezado, filas) -> bytes:
    """Escribe a mano para controlar espacios y comillas. Un campo con comillas va entre
    comillas con las internas duplicadas (los espacios quedan DENTRO de las comillas)."""
    def campo(v: str) -> str:
        return '"' + v.replace('"', '""') + '"' if '"' in v else v
    lineas = ["|".join(encabezado)] + ["|".join(campo(v) for v in f) for f in filas]
    return ("\n".join(lineas) + "\n").encode("utf-8")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def fecha_en_formato(d: date, i: int) -> tuple[str, str]:
    formatos = [("%Y-%m-%d", "YYYY-MM-DD"), ("%d/%m/%Y", "DD/MM/YYYY"), ("%d-%m-%Y", "DD-MM-YYYY")]
    f, nombre = formatos[i % 3]
    return d.strftime(f), nombre


def generar_validos(rnd: random.Random):
    anomalias = []

    def anotar(archivo, reg, col, original, normalizado, tipo):
        if original != normalizado:
            anomalias.append({"archivo": archivo, "registro": reg, "columna": col,
                              "original": original, "normalizado": normalizado, "anomalia": tipo})

    # --- clientes ---
    arch_c = "lab_clientes_20261109.dat"
    limpios_c, sucios_c = [], []
    for i in range(20):
        cid = i + 1
        nombre = NOMBRES[i]
        if cid == 8:
            nombre = nombre.replace(" ", ' "Tomi" ', 1)   # comillas internas: Tomás "Tomi" Álvarez
        usuario = _sin_tildes(NOMBRES[i]).lower().replace(" ", ".")
        email = f"{usuario}@ejemplo.com.ar"
        alta = date(2020, 1, 1) + timedelta(days=rnd.randint(0, 2400))
        pais = ["AR", "CL", "UY"][rnd.randint(0, 2)]
        activo = rnd.random() < 0.75
        limpio = [str(cid), nombre, email, alta.isoformat(), pais, "1" if activo else "0"]

        s_nombre = f"  {nombre} " if i % 4 == 0 else nombre
        s_email = email.upper() if i % 3 == 0 else (f" {email}" if i % 5 == 1 else email)
        s_alta, fmt = fecha_en_formato(alta, i)
        s_pais = pais.lower() if i % 2 == 0 else pais
        s_activo = (["sí", "SÍ", "true", "1", "Si"] if activo else ["no", "false", "0", "NO"])[i % (5 if activo else 4)]
        s_id = f" {cid}" if i % 6 == 5 else str(cid)
        sucio = [s_id, s_nombre, s_email, s_alta, s_pais, s_activo]
        tipos = ["espacios externos", "espacios externos", "email en mayusculas/espacios",
                 f"fecha {fmt}", "pais en minusculas", "booleano textual"]
        for col, o, n, t in zip(ENC_CLIENTES, sucio, limpio, tipos):
            anotar(arch_c, cid, col, o, n, t)
        if '"' in nombre:
            anotar(arch_c, cid, "nombre", '"' + s_nombre.replace('"', '""') + '"', nombre,
                  "comillas internas duplicadas")
        limpios_c.append(limpio)
        sucios_c.append(sucio)

    # --- ventas ---
    arch_v = "lab_ventas_20261109.dat"
    limpios_v, sucios_v = [], []
    for i in range(100):
        vid = i + 1
        cid = rnd.randint(1, 20)
        fv = date(2026, 11, 1) + timedelta(days=rnd.randint(0, 8))
        cant = rnd.randint(1, 12)
        importe = Decimal(rnd.randint(1500, 2_500_000)) / 100
        obs = rnd.choice(OBSERVACIONES) if rnd.random() < 0.55 else ""
        limpio = [str(vid), str(cid), fv.isoformat(), str(cant), f"{importe:.2f}", "ARS", obs]

        s_fv, fmt = fecha_en_formato(fv, i)
        s_cant = f" {cant} " if i % 7 == 3 else str(cant)
        if i % 4 == 0:
            s_imp, t_imp = f"{importe:.2f}".replace(".", ","), "coma decimal"
        elif i % 4 == 1 and importe == importe.to_integral():
            s_imp, t_imp = str(int(importe)), "sin decimales"
        elif i % 4 == 1 and (importe * 10) == (importe * 10).to_integral():
            s_imp, t_imp = f"{importe:.1f}".replace(".", ","), "coma y un decimal"
        else:
            s_imp, t_imp = f"{importe:.2f}", ""
        s_mon = ["ARS", "ars", " ARS ", "Ars"][i % 4]
        if obs == "":
            s_obs = ["", "NULL", "N/A", "null", "  "][i % 5]
            t_obs = "nulo en opcional"
        else:
            s_obs = f" {obs}  " if i % 3 == 0 else obs
            t_obs = "espacios externos"
        s_cid = f"{cid} " if i % 9 == 2 else str(cid)
        sucio = [str(vid), s_cid, s_fv, s_cant, s_imp, s_mon, s_obs]
        tipos = ["", "espacios externos", f"fecha {fmt}", "espacios externos", t_imp,
                 "moneda en minusculas/espacios", t_obs]
        for col, o, n, t in zip(ENC_VENTAS, sucio, limpio, tipos):
            anotar(arch_v, vid, col, o, n, t)
        if '"' in obs:
            anotar(arch_v, vid, "observacion", "(entre comillas, internas duplicadas)", obs,
                   "comillas internas duplicadas")
        limpios_v.append(limpio)
        sucios_v.append(sucio)

    return (arch_c, limpios_c, sucios_c), (arch_v, limpios_v, sucios_v), anomalias


def escribir_validos(rnd):
    (arch_c, lc, sc), (arch_v, lv, sv), anomalias = generar_validos(rnd)
    orig, esp = RAIZ / "validos" / "originales", RAIZ / "validos" / "esperados"
    orig.mkdir(parents=True, exist_ok=True)
    esp.mkdir(parents=True, exist_ok=True)
    archivos = {}
    for arch, enc, limpios, sucios in ((arch_c, ENC_CLIENTES, lc, sc), (arch_v, ENC_VENTAS, lv, sv)):
        b_orig, b_esp = dat_sucio(enc, sucios), dat_limpio(enc, limpios)
        (orig / arch).write_bytes(b_orig)
        (esp / arch).write_bytes(b_esp)
        info = {"registros": len(limpios), "sha256_original": sha(b_orig), "sha256_esperado": sha(b_esp)}
        if arch.startswith("lab_ventas"):
            info["suma_cantidad"] = str(sum(int(f[3]) for f in limpios))
            info["suma_importe_total"] = f"{sum(Decimal(f[4]) for f in limpios):.2f}"
            info["clientes_referenciados"] = sorted({int(f[1]) for f in limpios})
        archivos[arch] = info
    manifiesto = {"fecha_negocio": "2026-11-09", "semilla": SEMILLA, "archivos": archivos,
                  "total_anomalias": len(anomalias), "anomalias": anomalias}
    (RAIZ / "validos" / "manifiesto.json").write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return lc


def escribir_negativos(clientes_validos):
    neg = RAIZ / "negativos"
    neg.mkdir(parents=True, exist_ok=True)

    def cliente(cid, nombre=None, email=None, alta="2025-03-10", pais="AR", activo="1"):
        nombre = nombre if nombre is not None else f"Cliente Prueba {cid}"
        return [str(cid), nombre, email or f"cliente{cid}@ejemplo.com", alta, pais, activo]

    def venta(vid, cid=3, imp="1500.00", mon="ARS", cant="2", obs=""):
        return [str(vid), str(cid), "2026-11-10", cant, imp, mon, obs]

    casos = {
        "lab_clientes_20261110.dat": (ENC_CLIENTES, [cliente(101), cliente(102, alta="31/02/2026"), cliente(103)]),
        "lab_clientes_20261111.dat": (ENC_CLIENTES, [cliente(111), cliente(112, nombre=""), cliente(113)]),
        "lab_ventas_20261112.dat": (ENC_VENTAS, [venta(1201), venta(1202)[:-1], venta(1203)]),
        "lab_ventas_20261113.dat": (ENC_VENTAS, [venta(1301), venta(1302), venta(1302, imp="99.90")]),
        "lab_ventas_20261114.dat": (ENC_VENTAS, [venta(1401), venta(1402, cid=999), venta(1403)]),
        "lab_ventas_20261115.dat": (ENC_VENTAS, [venta(1501), venta(1502, imp="12,345"), venta(1503)]),
        "lab_clientes_20261116.dat": (ENC_CLIENTES, []),
        "lab_ventas_20261117.dat": (ENC_VENTAS, [venta(1701), venta(1702, mon="USD"), venta(1703)]),
        # escenario 11: clientes invalido + ventas valido del mismo dia
        "lab_clientes_20261118.dat": (ENC_CLIENTES, [cliente(181), cliente(182, email="sin-arroba.com"), cliente(183)]),
        "lab_ventas_20261118.dat": (ENC_VENTAS, [venta(1800 + i, cid=i) for i in range(1, 6)]),
    }
    for arch, (enc, filas) in casos.items():
        (neg / arch).write_bytes(dat_sucio(enc, filas))

    # escenario 9: lote valido nuevo para la falla transitoria
    val = RAIZ / "validos" / "originales"
    (val / "lab_clientes_20261119.dat").write_bytes(
        dat_limpio(ENC_CLIENTES, [cliente(190 + i, pais=["AR", "CL", "UY"][i % 3]) for i in range(1, 6)]))
    (val / "lab_ventas_20261119.dat").write_bytes(
        dat_limpio(ENC_VENTAS, [venta(1900 + i, cid=(191 + i % 5) if i % 2 else (1 + i % 20),
                                      imp=f"{100 + i * 7}.{i % 100:02d}", cant=str(1 + i % 5))
                                for i in range(1, 31)]))


if __name__ == "__main__":
    rnd = random.Random(SEMILLA)
    clientes = escribir_validos(rnd)
    escribir_negativos(clientes)
    m = json.loads((RAIZ / "validos" / "manifiesto.json").read_text(encoding="utf-8"))
    print(json.dumps(m["archivos"], indent=2))
    print("anomalias:", m["total_anomalias"])
