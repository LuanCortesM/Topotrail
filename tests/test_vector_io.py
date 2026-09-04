"""Os vetores de saida sao montados, reprojetados, medidos e gravados so com OGR.

Ate a 0.12 essa parte usava geopandas + shapely, que o QGIS nao instala; a
0.13 trocou por `FeatureSet`, uma colecao minima sobre ogr.Geometry. Este
teste confirma, com o GDAL de verdade, que a troca preservou o comportamento:
reprojecao, comprimento e area em CRS metrico, buffer, e escrita em GPKG,
Shapefile e KML que o proprio OGR le de volta.

Roda num subprocesso porque o resto da suite substitui `osgeo` por stubs
para importar o modulo sem QGIS; aqui precisamos do GDAL real. Se nenhum
interpretador tiver GDAL, o teste e pulado, nao falha.
"""

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

SCRIPT = textwrap.dedent(
    r'''
    import importlib.util, math, os, sys, tempfile, types
    sys.modules.setdefault("qgis", types.ModuleType("qgis"))
    core = types.ModuleType("qgis.core")
    class _Base:
        def __init__(self, *a, **k): pass
    for name in ("QgsProcessingAlgorithm", "QgsProcessingParameterRasterLayer",
                 "QgsProcessingParameterNumber", "QgsProcessingParameterFile",
                 "QgsProcessingParameterFileDestination", "QgsProcessingParameterEnum",
                 "QgsProcessingParameterCrs", "QgsProcessingParameterBoolean",
                 "QgsProcessingParameterVectorLayer", "QgsProcessingParameterString",
                 "QgsProcessingOutputVectorLayer", "QgsProcessingOutputRasterLayer",
                 "QgsProcessingOutputFile", "QgsProject"):
        setattr(core, name, type(name, (_Base,), {}))
    sys.modules["qgis.core"] = core
    sys.modules["qgis"].core = core
    package = types.ModuleType("processing"); package.__path__ = [os.path.join(ROOT, "processing")]
    sys.modules["processing"] = package
    spec = importlib.util.spec_from_file_location("processing.algorithm", os.path.join(ROOT, "processing", "algorithm.py"))
    alg = importlib.util.module_from_spec(spec); sys.modules["processing.algorithm"] = alg; spec.loader.exec_module(alg)

    from osgeo import ogr
    ogr.UseExceptions()
    FeatureSet = alg.FeatureSet

    # Quadrado de 1 km em UTM 23S e uma linha de 1 km.
    utm = alg.srs_from_any("EPSG:32723").ExportToWkt()
    square = ogr.CreateGeometryFromWkt("POLYGON((500000 7500000,501000 7500000,501000 7501000,500000 7501000,500000 7500000))")
    line = ogr.Geometry(ogr.wkbLineString); line.AddPoint_2D(500000, 7500000); line.AddPoint_2D(501000, 7500000)

    zones = FeatureSet([square], [{"value": 1}], utm)
    zones.set_column("area_m2", zones.areas()); zones.set_column("area_ha", [a / 1e4 for a in zones.areas()])
    assert abs(zones.areas()[0] - 1e6) < 1e-3, zones.areas()
    assert zones.columns == ["value", "area_m2", "area_ha", "geometry"], zones.columns

    route = FeatureSet([line], [{"tipo": "rota_principal", "custo": 1.5, "vertices": 2}], utm)
    assert abs(route.lengths()[0] - 1000.0) < 1e-6

    # Reprojecao ida e volta preserva a medida dentro de 1 mm.
    back = route.to_crs("EPSG:4326").to_crs("EPSG:32723")
    assert abs(back.lengths()[0] - 1000.0) < 1e-3, back.lengths()
    geo = route.to_crs("EPSG:4326")
    x, y = geo.geometries[0].GetPoint_2D(0)
    assert -90 < y < 0 and -180 < x < 0, (x, y)  # hemisferio sul, oeste

    corridor = route.buffer(50.0)
    assert abs(corridor.areas()[0] - (1000 * 100 + math.pi * 50 ** 2)) / corridor.areas()[0] < 0.01
    b = corridor.total_bounds(); assert b[0] < 500000 < 501000 < b[2] and b[1] < 7500000 < b[3]

    tmp = tempfile.mkdtemp()
    class _Crs:
        def __init__(self, authid): self._authid = authid
        def isValid(self): return True
        def authid(self): return self._authid
    for fmt, name in (("GeoPackage", "z.gpkg"), ("Shapefile", "z.shp"), ("KML", "z.kml")):
        path = os.path.join(tmp, name)
        export = FeatureSet(zones.geometries, zones.attributes, zones.crs)
        # save_vector e o caminho real do plugin: escolhe driver, reprojeta, poda campos.
        alg.save_vector(export, path, fmt, _Crs("EPSG:4326") if fmt == "KML" else None)
        ds = ogr.Open(path); layer = ds.GetLayer(0)
        assert layer.GetFeatureCount() == 1, (fmt, layer.GetFeatureCount())
        feature = layer.GetNextFeature()
        assert feature.GetGeometryRef().IsValid()
        fields = {layer.GetLayerDefn().GetFieldDefn(i).GetName() for i in range(layer.GetLayerDefn().GetFieldCount())}
        assert "area_ha" in fields and "value" in fields, (fmt, fields)
        assert ("area_m2" in fields) == (fmt != "Shapefile"), (fmt, fields)
        got = feature.GetField("area_ha")
        assert abs(float(got) - 100.0) < 1e-6, (fmt, got)
        srs = layer.GetSpatialRef()
        assert srs is not None and srs.GetAuthorityCode(None) == ("4326" if fmt == "KML" else "32723"), (fmt, srs.GetAuthorityCode(None))
        ds = None

    # Rota e corredor em GPKG com nomes de camada proprios; NaN vira nulo.
    route.set_column("compr_m", [float("nan")])
    route.to_file(os.path.join(tmp, "r.gpkg"), driver="GPKG", layer_name="rota")
    ds = ogr.Open(os.path.join(tmp, "r.gpkg")); layer = ds.GetLayerByName("rota")
    feature = layer.GetNextFeature()
    assert feature.IsFieldNull(feature.GetFieldIndex("compr_m"))
    assert feature.GetField("tipo") == "rota_principal" and feature.GetField("vertices") == 2
    print("VECTOR_IO_OK")
    '''
)


def _interpreter_with_gdal():
    candidates = [sys.executable, "python3", "python3.12", "python3.11", "python3.13"]
    for candidate in candidates:
        path = candidate if os.path.isabs(candidate) else subprocess.run(
            ["which", candidate], capture_output=True, text=True).stdout.strip()
        if not path:
            continue
        ok = subprocess.run([path, "-c", "from osgeo import gdal, ogr, osr"],
                            capture_output=True).returncode == 0
        if ok:
            return path
    return None



def test_feature_set_round_trips_through_real_ogr():
    executable = _interpreter_with_gdal()
    if executable is None:
        pytest.skip("GDAL nao esta instalado em nenhum interpretador disponivel")
    result = subprocess.run(
        [executable, "-c", f"ROOT = {str(ROOT)!r}\n" + SCRIPT],
        capture_output=True, text=True, timeout=120)
    output = result.stdout + result.stderr
    assert result.returncode == 0 and "VECTOR_IO_OK" in output, output[-2500:]
