"""Suite de integracao: GDAL e QGIS de verdade, sem nenhum substituto.

A suite de `tests/` e hermetica de proposito -- substitui `osgeo` e `qgis` por
modulos falsos para rodar em qualquer maquina em cinco segundos. O preco e que
ela nao ve nada que dependa do comportamento real do GDAL, e foi exatamente ai
que passou o pior defeito que a auditoria da 1.2.0 encontrou: gravar a saida num
GeoPackage existente apagava as camadas do usuario. Nenhum teste unitario podia
ter pego isso, porque no substituto `GetDriverByName` devolve None.

Esta suite roda o pacote instalado, com as bibliotecas de verdade, e e pulada
inteira onde elas nao existirem.

    /usr/bin/python3.12 -m pytest integracao -q
"""
import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


RECADO_SUBSTITUTO = (
    "esta suite foi coletada no mesmo processo que tests/, que substitui osgeo e "
    "qgis por dubles em sys.modules e nao da para desfazer isso depois do import. "
    "Rode-a sozinha: /usr/bin/python3.12 -m pytest integracao -q"
)


def _real(nome):
    """Importa de verdade, recusando qualquer substituto deixado por outra suite.

    Testar contra um duble aqui seria pior que nao testar: foi exatamente num
    modulo substituido que passou o pior defeito da 1.2.0 -- gravar a saida num
    GeoPackage existente apagava as camadas do usuario, e no duble
    GetDriverByName devolve None.
    """
    modulo = sys.modules.get(nome)
    if modulo is not None and getattr(modulo, "__topotrail_stub__", False):
        pytest.skip("{}: {}".format(nome, RECADO_SUBSTITUTO), allow_module_level=False)
    try:
        return __import__(nome, fromlist=["*"])
    except Exception:
        return None


@pytest.fixture(scope="session")
def ogr():
    modulo = _real("osgeo.ogr")
    if modulo is None or modulo.GetDriverByName("GPKG") is None:
        pytest.skip("GDAL com driver GPKG nao disponivel")
    modulo.UseExceptions()
    return modulo


@pytest.fixture(scope="session")
def osr():
    modulo = _real("osgeo.osr")
    if modulo is None:
        pytest.skip("GDAL/OSR nao disponivel")
    return modulo


@pytest.fixture(autouse=True)
def idioma_limpo():
    """Devolve o idioma do algoritmo ao padrao entre um teste e outro.

    O idioma vive em QgsSettings, que e estado global do processo: um teste que
    roda em chines deixava o seguinte lendo a legenda em chines, e a falha
    aparecia no teste errado, so quando a suite rodava inteira e nessa ordem.
    """
    try:
        from qgis.core import QgsSettings
    except Exception:
        yield
        return
    chave = "TopoTrail/language"
    anterior = QgsSettings().value(chave, "")
    QgsSettings().setValue(chave, "pt")
    try:
        yield
    finally:
        QgsSettings().setValue(chave, anterior)


@pytest.fixture(scope="session")
def plugin():
    """O pacote do plugin como ele e importado dentro do QGIS."""
    pai = os.path.dirname(RAIZ)
    if pai not in sys.path:
        sys.path.insert(0, pai)
    try:
        modulo = __import__(
            "{}.processing.algorithm".format(os.path.basename(RAIZ)),
            fromlist=["algorithm"])
    except Exception as erro:      # pragma: no cover - depende do ambiente
        pytest.skip("plugin nao importavel fora do QGIS: {}".format(erro))
    return modulo


@pytest.fixture(scope="session")
def qgis_app():
    """QGIS headless de verdade, para rodar o algoritmo de ponta a ponta.

    Sobe um QgsApplication no proprio processo do pytest. Sem isto os defeitos
    que so aparecem numa execucao completa -- legenda gravada no raster, avisos
    que nunca eram emitidos, chave que faltava no dicionario de resultados --
    continuariam sem teste, porque em `tests/` o QGIS e um duble.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("XDG_RUNTIME_DIR", "/tmp/xdg")
    try:
        os.makedirs(os.environ["XDG_RUNTIME_DIR"], exist_ok=True)
    except OSError:
        pass
    nucleo = _real("qgis.core")
    if nucleo is None:
        pytest.skip("QGIS nao disponivel")
    aplicacao = nucleo.QgsApplication.instance()
    if aplicacao is None:
        aplicacao = nucleo.QgsApplication([], False)
        nucleo.QgsApplication.setPrefixPath("/usr", True)
        aplicacao.initQgis()
    return aplicacao


@pytest.fixture(scope="session")
def executar(qgis_app, plugin):
    """Roda o algoritmo completo e devolve (resultado, feedback, excecao)."""
    nucleo = _real("qgis.core")

    class _Feedback(nucleo.QgsProcessingFeedback):
        def __init__(self):
            super().__init__()
            self.linhas = []

        def pushInfo(self, mensagem):
            self.linhas.append(mensagem)

        def pushWarning(self, mensagem):
            self.linhas.append("AVISO: " + mensagem)

        def reportError(self, mensagem, fatal=False):
            self.linhas.append("ERRO: " + mensagem)

        def procurar(self, *chaves):
            return [linha for linha in self.linhas
                    if any(chave in linha for chave in chaves)]

    def _executar(parametros):
        # Chama processAlgorithm direto, e nao QgsProcessingAlgorithm.run():
        # run() converte qualquer excecao em (None, False) e o tipo do erro --
        # que e justamente o que a correcao das excecoes nuas fixa -- se perde.
        algoritmo = plugin.TopotrailAlgorithm()
        algoritmo.initAlgorithm()
        contexto = nucleo.QgsProcessingContext()
        feedback = _Feedback()
        try:
            resultado = algoritmo.processAlgorithm(parametros, contexto, feedback)
        except Exception as erro:
            return None, feedback, erro
        return resultado, feedback, None

    return _executar


# ---- construcao de cenas sinteticas para as execucoes de ponta a ponta ----

CENA_GEOTRANSFORM = (500000.0, 30.0, 0.0, 7500000.0, 0.0, -30.0)
CENA_EPSG = 32723


def escrever_dem(caminho, matriz, geotransform=CENA_GEOTRANSFORM, epsg=CENA_EPSG,
                 nodata=None):
    """Grava um GeoTIFF de uma banda com o GDAL de verdade."""
    from osgeo import gdal, osr

    linhas, colunas = matriz.shape
    fonte = gdal.GetDriverByName("GTiff").Create(
        caminho, colunas, linhas, 1, gdal.GDT_Float32)
    fonte.SetGeoTransform(geotransform)
    referencia = osr.SpatialReference()
    referencia.ImportFromEPSG(epsg)
    fonte.SetProjection(referencia.ExportToWkt())
    banda = fonte.GetRasterBand(1)
    if nodata is not None:
        banda.SetNoDataValue(nodata)
    banda.WriteArray(matriz)
    banda.FlushCache()
    del fonte
    return caminho


def escrever_pontos(caminho, coordenadas, epsg=CENA_EPSG):
    from osgeo import ogr, osr

    if os.path.exists(caminho):
        os.remove(caminho)
    fonte = ogr.GetDriverByName("GeoJSON").CreateDataSource(caminho)
    referencia = osr.SpatialReference()
    referencia.ImportFromEPSG(epsg)
    camada = fonte.CreateLayer("p", srs=referencia, geom_type=ogr.wkbPoint)
    for x, y in coordenadas:
        feicao = ogr.Feature(camada.GetLayerDefn())
        geometria = ogr.Geometry(ogr.wkbPoint)
        geometria.AddPoint_2D(float(x), float(y))
        feicao.SetGeometry(geometria)
        camada.CreateFeature(feicao)
    del fonte
    return caminho


def escrever_poligonos(caminho, wkts, epsg=CENA_EPSG):
    from osgeo import ogr, osr

    if os.path.exists(caminho):
        os.remove(caminho)
    fonte = ogr.GetDriverByName("GPKG").CreateDataSource(caminho)
    referencia = osr.SpatialReference()
    referencia.ImportFromEPSG(epsg)
    camada = fonte.CreateLayer("r", srs=referencia, geom_type=ogr.wkbPolygon)
    for wkt in wkts:
        feicao = ogr.Feature(camada.GetLayerDefn())
        feicao.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
        camada.CreateFeature(feicao)
    del fonte
    return caminho


def relevo(linhas=60, colunas=60, base=1000.0):
    """MDE sintetico com rampa e ondulacao: relevo simples mas nao plano."""
    import numpy as np

    y, x = np.mgrid[0:linhas, 0:colunas].astype("float32")
    return (base + x * 3.0 + np.sin(y / 5.0) * 20.0).astype("float32")


def parametros_base(dem, saida, inicio=None, fim=None, **extras):
    """Os mesmos parametros da bateria oficial, com a cena sintetica."""
    parametros = {
        "INPUT_DEM": dem, "DERIVE_FROM_DEM": True, "VERTICAL_UNIT": 0,
        "ALT_MIN": -500.0, "ALT_MAX": 9000.0, "SLOPE_MAX": 100.0,
        "SLOPE_SCORE_MAX": 50.0, "THRESHOLD": 0.0, "AUTO_PERCENTILE": 75.0,
        "MIN_PATCH_AREA_HA": 2.0, "ALTITUDE_BAND_THRESHOLD": False,
        "ALTITUDE_BAND_SIZE_M": 200.0, "WALKABILITY_ZONES": False,
        "WEIGHT_ALT": 0.0, "WEIGHT_SLOPE": 1.0, "WEIGHT_CURVH": 1.0,
        "WEIGHT_CURVV": 1.0, "WEIGHT_WETNESS": 0.0, "WEIGHT_ROUGHNESS": 0.0,
        "START_POINT_FILE": inicio, "END_POINT_FILE": fim,
        "ROUTE_BUFFER_M": 100.0, "ROUTE_MARGIN_M": 3000.0, "ROUTE_COST_MODEL": 2,
        "STREAMS_FROM_DEM": False, "STREAM_MIN_BASIN_KM2": 1.0,
        "GENERATE_ZONES": True, "OUTPUT_FILE": saida, "OUTPUT_FORMAT": 1,
        "OUTPUT_CRS": "",
    }
    parametros.update(extras)
    return parametros
