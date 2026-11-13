from pathlib import Path

import pytest

from lab_pipeline.contrato import ContratoInvalido, cargar_contrato, cargar_contratos, orden_de_carga


def test_contratos_reales_cargan():
    c = cargar_contratos()
    assert set(c) == {"lab.clientes", "lab.ventas"}
    assert c["lab.clientes"].encabezado == ["cliente_id", "nombre", "email", "fecha_alta", "pais_codigo", "activo"]
    assert c["lab.ventas"].cantidad_columnas == 7
    assert c["lab.ventas"].columnas_suma == ("cantidad", "importe_total")


def test_orden_de_carga_respeta_dependencias():
    assert orden_de_carga(cargar_contratos()) == ["lab.clientes", "lab.ventas"]


def _escribir(tmp_path: Path, nombre: str, texto: str) -> Path:
    p = tmp_path / nombre
    p.write_text(texto, encoding="utf-8")
    return p


BASE = """
schema: lab
tabla: prueba
version_contrato: 1
clave_primaria: [id]
columnas_suma: {suma}
columnas:
  - {{nombre: id, tipo: int, obligatorio: true}}
  - {{nombre: monto, tipo: {tipo_monto}, obligatorio: true, precision: 14, escala: 2}}
"""


def test_suma_sobre_identificador_falla(tmp_path):
    p = _escribir(tmp_path, "lab_prueba.yaml", BASE.format(suma="[id]", tipo_monto="decimal"))
    with pytest.raises(ContratoInvalido, match="identificador"):
        cargar_contrato(p)


def test_suma_sobre_columna_inexistente_falla(tmp_path):
    p = _escribir(tmp_path, "lab_prueba.yaml", BASE.format(suma="[total]", tipo_monto="decimal"))
    with pytest.raises(ContratoInvalido, match="no es una columna"):
        cargar_contrato(p)


def test_tipo_desconocido_falla(tmp_path):
    p = _escribir(tmp_path, "lab_prueba.yaml", BASE.format(suma="[]", tipo_monto="float"))
    with pytest.raises(ContratoInvalido, match="tipo desconocido"):
        cargar_contrato(p)


def test_nombre_de_archivo_debe_coincidir(tmp_path):
    p = _escribir(tmp_path, "otro.yaml", BASE.format(suma="[monto]", tipo_monto="decimal"))
    with pytest.raises(ContratoInvalido, match="deberia llamarse"):
        cargar_contrato(p)


def test_columna_sin_tipo_falla(tmp_path):
    texto = BASE.format(suma="[]", tipo_monto="decimal").replace("{nombre: id, tipo: int,", "{nombre: id,")
    p = _escribir(tmp_path, "lab_prueba.yaml", texto)
    with pytest.raises(ContratoInvalido, match="columna sin"):
        cargar_contrato(p)


def test_entorno_local_tiene_lo_necesario():
    import yaml

    from lab_pipeline.contrato import DIR_TABLAS

    ruta = DIR_TABLAS.parent / "entornos" / "local.yaml"
    env = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    assert env["storage"]["tipo"] == "local"
    assert set(env["storage"]["zonas"]) == {"entrada", "raw", "curated", "rejected"}
    assert env["conexiones"] == {"sql": "mssql_lab", "correo": "smtp_mailpit"}
    assert env["correo"]["destinatarios"]
