from pathlib import Path

import pytest

from lab_pipeline.contrato import cargar_contratos

RAIZ = Path(__file__).resolve().parents[1]
DATOS = RAIZ / "datos"


@pytest.fixture(scope="session")
def contratos():
    return cargar_contratos()


@pytest.fixture
def clientes(contratos):
    return contratos["lab.clientes"]


@pytest.fixture
def ventas(contratos):
    return contratos["lab.ventas"]
