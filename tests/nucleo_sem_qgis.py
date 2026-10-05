"""O nucleo numerico do plugin, importavel sem QGIS e sem GDAL.

`processing/algorithm.py` importa `qgis.core` e `osgeo` no topo, mas as funcoes
que importam para os testes sao NumPy puro. Aqui esses modulos sao substituidos
por dubles burros SO durante o import do algoritmo: terminado o import,
`sys.modules` volta a ser o que era. O modulo carregado guarda as referencias
aos dubles; o resto do processo -- a suite de integracao, os scripts de
validacao com GDAL de verdade -- nao ve dubles nenhum.

Sem pytest de proposito: `validation/entorno.py` usa o mesmo carregador.
"""

import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
_COBERTOS = ("osgeo", "qgis", "processing")


def _coberto(nome):
    return any(nome == raiz or nome.startswith(raiz + ".") for raiz in _COBERTOS)


def _module(name, **attributes):
    module = types.ModuleType(name)
    # A suite de integracao recusa qualquer modulo com esta marca em vez de
    # testar contra um duble.
    module.__topotrail_stub__ = True
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


def _inv_geotransform(gt):
    """Inversa da afim 2x3 do GDAL, para testar world_to_pixel sem GDAL."""
    det = gt[1] * gt[5] - gt[2] * gt[4]
    if det == 0:
        return None
    inv_det = 1.0 / det
    return (
        (gt[2] * gt[3] - gt[0] * gt[5]) * inv_det, gt[5] * inv_det, -gt[2] * inv_det,
        (-gt[1] * gt[3] + gt[0] * gt[4]) * inv_det, -gt[4] * inv_det, gt[1] * inv_det,
    )


def _instalar():
    osgeo = _module("osgeo")
    _module(
        "osgeo.gdal",
        UseExceptions=lambda: None,
        VersionInfo=lambda *a: "stub",
        Open=lambda *a, **k: None,
        GetDriverByName=lambda *a: None,
        InvGeoTransform=_inv_geotransform,
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
        "QgsProcessingParameterDefinition",
        "QgsProcessingOutputVectorLayer", "QgsProcessingOutputRasterLayer",
        "QgsProcessingOutputFile", "QgsProject",
    ]
    _module("qgis")
    _module("qgis.core", **{name: type(name, (_Base,), {}) for name in qgis_names})
    _module("qgis.PyQt")

    class _Any:
        """Aceita qualquer atributo: constantes de enumeracao do Qt."""

        def __getattr__(self, name):
            return 0

    _module(
        "qgis.PyQt.QtCore",
        Qt=_Any(),
        QCoreApplication=type(
            "QCoreApplication", (object,),
            {"translate": staticmethod(lambda context, text, *a: text)},
        ),
    )
    sys.modules["qgis"].core = sys.modules["qgis.core"]
    sys.modules["qgis"].PyQt = sys.modules["qgis.PyQt"]

    # algorithm.py usa imports relativos, entao precisa de um pacote pai: um
    # "processing" sintetico apontando para o diretorio real, sem executar o
    # __init__.py dele, que importa o proprio algorithm.
    package = types.ModuleType("processing")
    package.__path__ = [str(ROOT / "processing")]
    sys.modules["processing"] = package

    spec = importlib.util.spec_from_file_location(
        "processing.algorithm", ROOT / "processing" / "algorithm.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["processing.algorithm"] = module
    spec.loader.exec_module(module)
    return module


def algoritmo():
    """O processing/algorithm.py real, importado com QGIS e GDAL substituidos."""
    if "tt_algorithm" in sys.modules:
        return sys.modules["tt_algorithm"]
    antes = {nome: modulo for nome, modulo in sys.modules.items() if _coberto(nome)}
    try:
        module = _instalar()
    finally:
        for nome in [n for n in list(sys.modules) if _coberto(n)]:
            if nome in antes:
                sys.modules[nome] = antes[nome]
            else:
                del sys.modules[nome]
    sys.modules["tt_algorithm"] = module
    return module


def carregar(name):
    """Um modulo de processing/ que so usa NumPy, sem passar pelo __init__."""
    chave = "tt_" + name
    if chave in sys.modules:
        return sys.modules[chave]
    spec = importlib.util.spec_from_file_location(
        chave, ROOT / "processing" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[chave] = module
    spec.loader.exec_module(module)
    return module
