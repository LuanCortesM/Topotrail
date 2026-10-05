"""Cenas sinteticas para as execucoes de ponta a ponta da integracao.

Viviam em conftest.py, e `from conftest import ...` e ambiguo quando tests/ e
integracao/ sao coletados no mesmo processo.
"""
import os


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
