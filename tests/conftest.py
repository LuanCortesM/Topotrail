"""Makes the numeric core importable without QGIS.

`processing/algorithm.py` imports `qgis.core` at module level, but the functions
under test are pure NumPy and never touch QGIS at run time; only the import
does. `nucleo_sem_qgis` substitutes the QGIS and GDAL modules for the duration
of that import and then restores `sys.modules`, so this suite and the
integration suite (`integracao/`, real QGIS) can share one pytest process.

The stubs are deliberately dumb: any test that reaches for real QGIS or GDAL
behaviour fails loudly instead of quietly passing against a fake.
`terrain.py`, `hydrology.py`, `transitability.py` and `morphology.py` import
only NumPy and are loaded directly.
"""

import pytest

import nucleo_sem_qgis


@pytest.fixture(scope="session")
def algorithm():
    """The real processing/algorithm.py, with QGIS and GDAL stubbed for import."""
    return nucleo_sem_qgis.algoritmo()


@pytest.fixture(scope="session")
def terrain():
    return nucleo_sem_qgis.carregar("terrain")


@pytest.fixture(scope="session")
def hydrology():
    return nucleo_sem_qgis.carregar("hydrology")


@pytest.fixture(scope="session")
def transitability():
    return nucleo_sem_qgis.carregar("transitability")


@pytest.fixture(scope="session")
def morphology():
    return nucleo_sem_qgis.carregar("morphology")


@pytest.fixture
def transform_10m():
    """GeoTransform for a 10 m grid: origin (0, 1000), y decreasing."""
    return (0.0, 10.0, 0.0, 1000.0, 0.0, -10.0)
