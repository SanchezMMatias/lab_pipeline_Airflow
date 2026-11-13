import pytest

from lab_pipeline.control import parsear_estructura
from lab_pipeline.normalizacion import ValorInvalido, escribir_dat, normalizar_filas, normalizar_valor

from conftest import DATOS


@pytest.mark.parametrize("tabla,columna,crudo,esperado", [
    # decimal
    ("lab.ventas", "importe_total", " 12,5 ", "12.50"),
    ("lab.ventas", "importe_total", "12.5", "12.50"),
    ("lab.ventas", "importe_total", "1500", "1500.00"),
    ("lab.ventas", "importe_total", "0,01", "0.01"),
    # fechas en los tres formatos
    ("lab.ventas", "fecha_venta", "2026-11-09", "2026-11-09"),
    ("lab.ventas", "fecha_venta", "09/11/2026", "2026-11-09"),
    ("lab.ventas", "fecha_venta", " 09-11-2026 ", "2026-11-09"),
    ("lab.clientes", "fecha_alta", "29/02/2024", "2024-02-29"),  # bisiesto real
    # booleanos
    ("lab.clientes", "activo", "SÍ", "1"),
    ("lab.clientes", "activo", "si", "1"),
    ("lab.clientes", "activo", "true", "1"),
    ("lab.clientes", "activo", "1", "1"),
    ("lab.clientes", "activo", "NO", "0"),
    ("lab.clientes", "activo", "False", "0"),
    # texto, email, code, int
    ("lab.clientes", "nombre", "  José Pérez ", "José Pérez"),
    ("lab.clientes", "email", " Ana.Diaz@Ejemplo.COM ", "ana.diaz@ejemplo.com"),
    ("lab.clientes", "pais_codigo", " ar", "AR"),
    ("lab.ventas", "moneda", "ars", "ARS"),
    ("lab.ventas", "cantidad", " 7 ", "7"),
    # nulos en opcional -> vacio
    ("lab.ventas", "observacion", "N/A", ""),
    ("lab.ventas", "observacion", "NULL", ""),
    ("lab.ventas", "observacion", "null", ""),
    ("lab.ventas", "observacion", "   ", ""),
    ("lab.ventas", "observacion", 'Pedido "urgente"', 'Pedido "urgente"'),
])
def test_normaliza(contratos, tabla, columna, crudo, esperado):
    assert normalizar_valor(crudo, contratos[tabla].columna(columna)) == esperado


@pytest.mark.parametrize("tabla,columna,crudo,motivo", [
    ("lab.ventas", "importe_total", "12,345", "decimal invalido"),     # 3 decimales: rechazo, no redondeo
    ("lab.ventas", "importe_total", "1.234,50", "decimal invalido"),   # separador de miles
    ("lab.ventas", "importe_total", "-5", "decimal invalido"),
    ("lab.ventas", "importe_total", "1e3", "decimal invalido"),
    ("lab.ventas", "importe_total", "1234567890123,00", "excede"),     # > DECIMAL(14,2)
    ("lab.clientes", "fecha_alta", "31/02/2026", "fecha inexistente"),
    ("lab.clientes", "fecha_alta", "2026/02/01", "formato de fecha"),
    ("lab.clientes", "activo", "quizas", "booleano"),
    ("lab.clientes", "activo", "N/A", "obligatorio vacio"),
    ("lab.clientes", "nombre", "", "obligatorio vacio"),
    ("lab.clientes", "nombre", "NULL", "obligatorio vacio"),
    ("lab.clientes", "nombre", "x" * 101, "supera el maximo"),
    ("lab.clientes", "email", "sin-arroba.com", "email"),
    ("lab.clientes", "pais_codigo", "BR", "no permitido"),
    ("lab.clientes", "pais_codigo", "ARG", "largo"),
    ("lab.ventas", "moneda", "USD", "no permitido"),
    ("lab.ventas", "cantidad", "0", "minimo"),
    ("lab.ventas", "cantidad", "2.5", "no es un entero"),
    ("lab.ventas", "venta_id", "99999999999", "rango de INT"),
])
def test_rechaza(contratos, tabla, columna, crudo, motivo):
    with pytest.raises(ValorInvalido, match=motivo):
        normalizar_valor(crudo, contratos[tabla].columna(columna))


def test_acumula_todos_los_errores(ventas):
    filas = [["1", "1", "31/02/2026", "0", "12,345", "USD", ""],
             ["2", "1", "2026-11-09", "1", "10", "ARS", ""]]
    res = normalizar_filas(ventas, filas)
    assert [(e.registro, e.columna) for e in res.errores] == [
        (1, "fecha_venta"), (1, "cantidad"), (1, "importe_total"), (1, "moneda")]
    assert res.errores[2].valor == "12,345"


def test_clave_duplicada_y_archivo_vacio(ventas):
    fila = ["5", "1", "2026-11-09", "1", "10", "ARS", ""]
    res = normalizar_filas(ventas, [fila, list(fila)])
    assert len(res.errores) == 1
    assert "duplicada" in res.errores[0].motivo and res.errores[0].registro == 2
    assert "sin registros" in normalizar_filas(ventas, []).errores[0].motivo


def test_comillas_internas_se_preservan(ventas):
    datos = escribir_dat(ventas.encabezado, [["1", "1", "2026-11-09", "1", "10.00", "ARS", 'Pedido "urgente"']])
    assert datos.splitlines()[1] == b'1|1|2026-11-09|1|10.00|ARS|"Pedido ""urgente"""'
    assert not datos.startswith(b"\xef\xbb\xbf") and b"\r" not in datos


@pytest.mark.parametrize("archivo,tabla", [("lab_clientes_20261109.dat", "lab.clientes"),
                                           ("lab_ventas_20261109.dat", "lab.ventas")])
def test_sintetico_original_normaliza_igual_al_esperado_byte_a_byte(contratos, archivo, tabla):
    c = contratos[tabla]
    original = (DATOS / "validos" / "originales" / archivo).read_bytes()
    esperado = (DATOS / "validos" / "esperados" / archivo).read_bytes()
    res = normalizar_filas(c, parsear_estructura(original, c))
    assert res.errores == []
    assert escribir_dat(c.encabezado, res.filas) == esperado
