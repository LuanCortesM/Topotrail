"""Makes the numeric core importable without QGIS.

`processing/algorithm.py` imports `qgis.core` at module level, so none of its
mathematics could be tested in continuous integration -- which is why, until
now, not one line of the model was covered. The functions that matter are pure
NumPy and never touch QGIS at run time; only the import does.

Rather than refactor a 2,900-line module under a dissertation deadline, this
fixture substitutes the modules that are only needed for the import. The stubs
are deliberately dumb: `QgsProcessingAlgorithm` and friends become empty
classes, and the GDAL/OGR entry points become no-ops. Any test that actually
reaches for QGIS or GDAL behaviour will fail loudly instead of quietly passing
against a fake, which is the property that matters.

`terrain.py`, `hydrology.py` and `transitability.py` import only NumPy and need
none of this; they are imported directly.
"""

import importlib.util
import pathlib
import sys
import types

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _module(name, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


class _SpatialReference:
    """Enough of osr.SpatialReference for module import and UTM selection."""

    def __init__(self):
        self._geographic = True
        self._authority = ("EPSG", "4326")

    def ImportFromWkt(self, wkt):
        import pyproj

        crs = pyproj.CRS.from_wkt(wkt)
        self._geographic = crs.is_geographic
        self._authority = crs.to_authority()

    def ImportFromEPSG(self, code):
        import pyproj

        crs = pyproj.CRS.from_epsg(code)
        self._geographic = crs.is_geographic
        self._authority = ("EPSG", str(code))

    def SetAxisMappingStrategy(self, *args):
        pass

    def IsGeographic(self):
        return self._geographic

    def IsProjected(self):
        return not self._geographic

    def GetAuthorityName(self, target=None):
        return self._authority[0] if self._authority else None

    def GetAuthorityCode(self, target=None):
        return self._authority[1] if self._authority else None

    def ExportToWkt(self):
        return ""


def _install_stubs():
    if "tt_algorithm" in sys.modules:
        return

    osgeo = _module("osgeo")
    _module(
        "osgeo.gdal",
        UseExceptions=lambda: None,
        VersionInfo=lambda *a: "stub",
        Open=lambda *a, **k: None,
        GetDriverByName=lambda *a: None,
        Warp=lambda *a, **k: None,
        WarpOptions=lambda *a, **k: None,
        Translate=lambda *a, **k: None,
        RasterizeLayer=lambda *a, **k: None,
        ColorTable=object,
        GDT_Float32=6,
        GDT_Byte=1,
        GRA_Bilinear=1,
        GRA_NearestNeighbour=0,
        GRA_Cubic=2,
        GCI_PaletteIndex=1,
    )
    _module(
        "osgeo.ogr",
        UseExceptions=lambda: None,
        Open=lambda *a, **k: None,
        GetDriverByName=lambda *a: None,
        Feature=object,
        CreateGeometryFromWkb=lambda *a: None,
        wkbMultiPolygon=6,
    )
    _module("osgeo.osr", SpatialReference=_SpatialReference,
            OAMS_TRADITIONAL_GIS_ORDER=0)
    osgeo.gdal = sys.modules["osgeo.gdal"]
    osgeo.ogr = sys.modules["osgeo.ogr"]
    osgeo.osr = sys.modules["osgeo.osr"]

    class _Base:
        def __init__(self, *args, **kwargs):
            pass

    qgis_names = [
        "QgsProcessingAlgorithm", "QgsProcessingParameterRasterLayer",
        "QgsProcessingParameterNumber", "QgsProcessingParameterFile",
        "QgsProcessingParameterFileDestination", "QgsProcessingParameterEnum",
        "QgsProcessingParameterCrs", "QgsProcessingParameterBoolean",
        "QgsProcessingParameterVectorLayer", "QgsProcessingParameterString",
        "QgsProcessingOutputVectorLayer", "QgsProcessingOutputRasterLayer",
        "QgsProcessingOutputFile", "QgsProject",
    ]
    _module("qgis")
    _module("qgis.core", **{name: type(name, (_Base,), {}) for name in qgis_names})
    _module("qgis.PyQt")
    _module(
        "qgis.PyQt.QtCore",
        QCoreApplication=type(
            "QCoreApplication", (object,),
            {"translate": staticmethod(lambda context, text, *a: text)},
        ),
    )
    sys.modules["qgis"].core = sys.modules["qgis.core"]
    sys.modules["qgis"].PyQt = sys.modules["qgis.PyQt"]

    # algorithm.py usa imports relativos (from .hydrology import ...), entao
    # precisa de um pacote pai. Registramos um pacote "processing" sintetico
    # apontando para o diretorio real, sem executar o __init__.py dele -- que
    # importa o proprio algorithm e criaria um ciclo.
    package = types.ModuleType("processing")
    package.__path__ = [str(ROOT / "processing")]
    sys.modules["processing"] = package

    spec = importlib.util.spec_from_file_location(
        "processing.algorithm", ROOT / "processing" / "algorithm.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["processing.algorithm"] = module
    sys.modules["tt_algorithm"] = module
    spec.loader.exec_module(module)


@pytest.fixture(scope="session")
def algorithm():
    """The real processing/algorithm.py, with QGIS and GDAL stubbed for import."""
    _install_stubs()
    return sys.modules["tt_algorithm"]


def _load_by_path(name):
    """Load a module from its file, bypassing `processing/__init__.py`.

    The package __init__ imports algorithm.py, which imports QGIS. terrain,
    hydrology and transitability need only NumPy, so they are loaded directly
    and stay testable even where QGIS is not installed at all.
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "processing" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def terrain():
    return _load_by_path("terrain")


@pytest.fixture(scope="session")
def hydrology():
    return _load_by_path("hydrology")


@pytest.fixture(scope="session")
def transitability():
    return _load_by_path("transitability")


@pytest.fixture
def transform_10m():
    """GeoTransform for a 10 m grid: origin (0, 1000), y decreasing."""
    return (0.0, 10.0, 0.0, 1000.0, 0.0, -10.0)


def inclined_plane(rows, cols, spacing, slope_ratio, axis="x"):
    """A perfect plane of known gradient, for closed-form comparison."""
    y, x = np.mgrid[0:rows, 0:cols].astype(np.float64)
    distance = (x if axis == "x" else y) * spacing
    return (distance * slope_ratio).astype(np.float32)
