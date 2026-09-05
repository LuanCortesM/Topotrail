"""Bateria de testes de ponta a ponta do TopoTrail em QGIS headless.

Tres regioes com relevo muito diferente, mais casos de robustez:
  * Mantiqueira -- Marins x Itaguare (MDE real, 1 arco-segundo, carta 22S465; trilha
    GPS real da travessia com os cumes marcados pelo proprio caminhante);
  * Ceara -- Parque Estadual das Carnaubas (Copernicus GLO-90 real; trilhas GPS de
    campo; poligonal do parque);
  * Himalaia -- MDE sintetico com a estatistica do Everest (o download do tile
    real e bloqueado neste ambiente; o caso vale pelo regime de declividade).
Cada caso tem asserts; o resultado sai em bateria.json e RELATORIO.md.
"""
import os, sys, json, time, math, shutil, traceback
sys.path.insert(0, "/home/claude/work/exp")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import qgis_env, processing  # noqa
from qgis.core import QgsProcessingFeedback, QgsSettings, QgsVectorLayer, QgsCoordinateReferenceSystem
from osgeo import gdal, ogr, osr
import numpy as np

gdal.UseExceptions(); ogr.UseExceptions()
B = "/home/claude/work/bateria"; OUT = f"{B}/out"
shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)
CARTA = "/mnt/user-data/uploads/02 TOPOTRAIL/Cartas"
TRILHAS = "/mnt/user-data/uploads/02 TOPOTRAIL/Shapes/Trilhas para Teste"
RESULTS = []


class FB(QgsProcessingFeedback):
    def __init__(self): super().__init__(); self.lines = []
    def pushInfo(self, m): self.lines.append(m)
    def pushWarning(self, m): self.lines.append("AVISO: " + m)
    def reportError(self, m, fatal=False): self.lines.append("ERRO: " + m)
    def grep(self, *k): return [l for l in self.lines if any(x in l for x in k)]


def base(dem, out, start, end, **kw):
    p = {"INPUT_DEM": dem, "DERIVE_FROM_DEM": True, "VERTICAL_UNIT": 0,
         "ALT_MIN": -500.0, "ALT_MAX": 9000.0, "SLOPE_MAX": 100.0, "SLOPE_SCORE_MAX": 50.0,
         "THRESHOLD": 0.0, "AUTO_PERCENTILE": 75.0, "MIN_PATCH_AREA_HA": 2.0,
         "ALTITUDE_BAND_THRESHOLD": False, "ALTITUDE_BAND_SIZE_M": 200.0, "WALKABILITY_ZONES": False,
         "WEIGHT_ALT": 0.0, "WEIGHT_SLOPE": 1.0, "WEIGHT_CURVH": 1.0, "WEIGHT_CURVV": 1.0,
         "WEIGHT_WETNESS": 0.0, "WEIGHT_ROUGHNESS": 0.0,
         "START_POINT_FILE": start, "END_POINT_FILE": end,
         "ROUTE_BUFFER_M": 100.0, "ROUTE_MARGIN_M": 3000.0, "ROUTE_COST_MODEL": 2,
         "STREAMS_FROM_DEM": False, "STREAM_MIN_BASIN_KM2": 1.0,
         "GENERATE_ZONES": True, "OUTPUT_FILE": out, "OUTPUT_FORMAT": 1, "OUTPUT_CRS": ""}
    p.update(kw); return p


def run(params, lang="pt"):
    QgsSettings().setValue("TopoTrail/language", lang)
    fb = FB(); t = time.time()
    try:
        r = processing.run("topotrail:topotrail", params, feedback=fb)
    except Exception as exc:
        return None, fb, exc, time.time() - t
    return r, fb, None, time.time() - t


def vec(path):
    ds = ogr.Open(path); ly = ds.GetLayer(0); f = ly.GetNextFeature()
    defn = ly.GetLayerDefn()
    attrs = {defn.GetFieldDefn(i).GetName(): f.GetField(i) for i in range(defn.GetFieldCount())} if f else {}
    geom = f.GetGeometryRef().Clone() if f else None
    srs = ly.GetSpatialRef(); wkt = srs.ExportToWkt() if srs else ""
    n = ly.GetFeatureCount(); ds = None
    return dict(n=n, attrs=attrs, geom=geom, wkt=wkt)


def raster(path):
    ds = gdal.Open(path); b = ds.GetRasterBand(1); a = b.ReadAsArray().astype("float64"); nd = b.GetNoDataValue()
    if nd is not None: a[a == nd] = np.nan
    return a, ds.GetGeoTransform(), ds.GetProjection()


def to_srs(geom, src_wkt, dst_wkt):
    s = osr.SpatialReference(); s.ImportFromWkt(src_wkt); s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    d = osr.SpatialReference(); d.ImportFromWkt(dst_wkt); d.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    g = geom.Clone(); g.Transform(osr.CoordinateTransformation(s, d)); return g


def agreement(route_path, trail_gpkg, buffers=(100.0, 250.0)):
    """Goodchild-Hunter: fracao do comprimento da rota dentro de um buffer da trilha real, e vice-versa."""
    r = vec(route_path); t = vec(trail_gpkg)
    trail = to_srs(t["geom"], t["wkt"], r["wkt"]); route = r["geom"]
    out = {}
    for bm in buffers:
        inside = route.Intersection(trail.Buffer(bm)).Length() / route.Length()
        covered = trail.Intersection(route.Buffer(bm)).Length() / trail.Length()
        out[f"{int(bm)}m"] = dict(rota_no_buffer_da_trilha=round(inside, 3), trilha_no_buffer_da_rota=round(covered, 3))
    out["comprimento_rota_m"] = round(route.Length(), 1); out["comprimento_trilha_m"] = round(trail.Length(), 1)
    return out


def distance_to_route(route_path, lonlat):
    r = vec(route_path)
    p = ogr.Geometry(ogr.wkbPoint); p.AddPoint_2D(*lonlat)
    s = osr.SpatialReference(); s.ImportFromEPSG(4326); s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    p = to_srs(p, s.ExportToWkt(), r["wkt"])
    return r["geom"].Distance(p)


def record(name, ok, detail, seconds=None, warnings=None):
    RESULTS.append(dict(caso=name, ok=bool(ok), detalhe=detail, segundos=None if seconds is None else round(seconds, 1),
                        avisos=warnings or []))
    print(("OK   " if ok else "FALHA") + f" {name}  ({'' if seconds is None else '%.0fs' % seconds})")
    for k, v in (detail.items() if isinstance(detail, dict) else [("detalhe", detail)]):
        print(f"      {k}: {v}")


def clip(src, dst, lonlat_bbox):
    gdal.Translate(dst, src, projWin=[lonlat_bbox[0], lonlat_bbox[3], lonlat_bbox[2], lonlat_bbox[1]])
    return dst


def buffered_trail_gpkg(trail_gpkg, dst, metres, epsg):
    t = vec(trail_gpkg); srs = osr.SpatialReference(); srs.ImportFromEPSG(epsg); srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    g = to_srs(t["geom"], t["wkt"], srs.ExportToWkt()).Buffer(metres)
    o = ogr.GetDriverByName("GPKG").CreateDataSource(dst); ly = o.CreateLayer("faixa", srs=srs, geom_type=ogr.wkbPolygon)
    f = ogr.Feature(ly.GetLayerDefn()); f.SetGeometry(g); ly.CreateFeature(f); o = None; return dst


def point_file(path, lonlat_list):
    o = ogr.GetDriverByName("GeoJSON").CreateDataSource(path); srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
    ly = o.CreateLayer("p", srs=srs, geom_type=ogr.wkbPoint)
    for x, y in lonlat_list:
        f = ogr.Feature(ly.GetLayerDefn()); g = ogr.Geometry(ogr.wkbPoint); g.AddPoint_2D(x, y); f.SetGeometry(g); ly.CreateFeature(f)
    o = None; return path


WP = json.load(open(f"{B}/waypoints.json"))
MARINS = WP["Pico do Marins"][0][:2]; MARINZINHO = WP["Pico do Marinzinho"][0][:2]; ITAGUARE = WP["Pico Itaguaré"][0][:2]

# =====================================================================
# MANTIQUEIRA: Marins x Itaguare (MDE real 1", trilha GPS real)
# =====================================================================
dem_mq = clip(f"{CARTA}/22S465ZN.tif", f"{OUT}/mantiqueira_dem.tif", (-45.19, -22.545, -45.035, -22.43))
a_mq, gt_mq, _ = raster(dem_mq)
print(f"\n== Mantiqueira: MDE {a_mq.shape}, {np.nanmin(a_mq):.0f}-{np.nanmax(a_mq):.0f} m ==")

# A. travessia completa com todos os produtos, passando pelos tres cumes na ordem real
r, fb, e, s = run(base(dem_mq, f"{OUT}/mq_A.gpkg", f"{B}/inicio.geojson", f"{B}/fim.geojson",
                       VIA_POINTS_FILE=f"{B}/picos.geojson", STREAMS_FROM_DEM=True, WEIGHT_WETNESS=0.5, WEIGHT_ROUGHNESS=0.5,
                       ALTITUDE_BAND_THRESHOLD=True, WALKABILITY_ZONES=False, MIN_PATCH_AREA_HA=5.0))
if e: record("MQ-A travessia completa", False, str(e)[-300:], s)
else:
    rt = vec(r["OUTPUT_ROUTE"]); ag = agreement(r["OUTPUT_ROUTE"], f"{B}/trilha_real.gpkg")
    dist = {n: round(distance_to_route(r["OUTPUT_ROUTE"], p), 1) for n, p in (("Marins", MARINS), ("Marinzinho", MARINZINHO), ("Itaguare", ITAGUARE))}
    tr, _, _ = raster(r["OUTPUT_TRANSITABILITY"]); tw = tr[np.isfinite(tr) & (tr > 0)]
    classes = {int(c): int((tw == c).sum()) for c in range(1, 6)}
    zones = vec(r["OUTPUT_VECTOR"])
    ok = all(v < 60 for v in dist.values()) and rt["attrs"]["trechos"] == 4 and ag["250m"]["rota_no_buffer_da_trilha"] > 0.5 and zones["n"] > 0
    record("MQ-A travessia completa (3 cumes, 6 produtos)", ok, dict(
        trechos=rt["attrs"]["trechos"], tempo_h=round(rt["attrs"].get("tempo_h", 0), 2), compr_m=round(rt["attrs"]["compr_m"]),
        ganho_m=round(rt["attrs"].get("ganho_m", 0)), distancia_aos_cumes_m=dist, concordancia_com_trilha_real=ag,
        classes_transitabilidade=classes, zonas=zones["n"], crs_saida=vec(r["OUTPUT_ROUTE"])["wkt"][:40]), s, fb.grep("AVISO")[:4])
    ROUTE_A = r["OUTPUT_ROUTE"]; LEN_A = rt["attrs"]["compr_m"]

# B. cumes em ordem embaralhada + otimizacao -> mesma rota que A
r, fb, e, s = run(base(dem_mq, f"{OUT}/mq_B.gpkg", f"{B}/inicio.geojson", f"{B}/fim.geojson",
                       VIA_POINTS_FILE=f"{B}/picos_desordem.geojson", OPTIMISE_ORDER=True, GENERATE_ZONES=False))
if e: record("MQ-B ordem otimizada", False, str(e)[-300:], s)
else:
    rt = vec(r["OUTPUT_ROUTE"]); rel = abs(rt["attrs"]["compr_m"] - LEN_A) / LEN_A
    ordem = fb.grep("ordem", "Ordem")
    record("MQ-B cumes embaralhados + Held-Karp recupera a ordem", rel < 0.02, dict(
        compr_m=round(rt["attrs"]["compr_m"]), compr_A=round(LEN_A), diferenca_relativa=round(rel, 4), log=ordem[:3]), s)

# C. rasters proprios da carta (SN/HN/VN) vs derivados; Shapefile; CRS de saida 31983
for name, path in (("slope", "22S465SN.tif"), ("curvh", "22S465HN.tif"), ("curvv", "22S465VN.tif")):
    clip(f"{CARTA}/{path}", f"{OUT}/mq_{name}.tif", (-45.19, -22.545, -45.035, -22.43))
r0, fb0, e0, s0 = run(base(dem_mq, f"{OUT}/mq_C0.gpkg", f"{B}/marins.geojson", f"{B}/itaguare.geojson", GENERATE_ZONES=False))
r1, fb1, e1, s1 = run(base(dem_mq, f"{OUT}/mq_C1.shp", f"{B}/marins.geojson", f"{B}/itaguare.geojson",
                           DERIVE_FROM_DEM=False, INPUT_SLOPE=f"{OUT}/mq_slope.tif", INPUT_CURVH=f"{OUT}/mq_curvh.tif",
                           INPUT_CURVV=f"{OUT}/mq_curvv.tif", SLOPE_UNIT=0, OUTPUT_FORMAT=0, OUTPUT_CRS="EPSG:31983"))
if e0 or e1: record("MQ-C rasters proprios", False, str(e0 or e1)[-300:], s0 + s1)
else:
    sc0, _, _ = raster(r0["OUTPUT_SCORE_RASTER"]); sc1, _, _ = raster(r1["OUTPUT_SCORE_RASTER"])
    m = np.isfinite(sc0) & np.isfinite(sc1); corr = float(np.corrcoef(sc0[m], sc1[m])[0, 1]) if sc0.shape == sc1.shape else float("nan")
    zn = vec(r1["OUTPUT_VECTOR"]); srs = osr.SpatialReference(); srs.ImportFromWkt(zn["wkt"])
    record("MQ-C rasters proprios da carta vs derivados; Shapefile em EPSG:31983", corr > 0.8 and srs.GetAuthorityCode(None) == "31983" and os.path.exists(r1["OUTPUT_VECTOR"][:-4] + ".prj"),
           dict(correlacao_das_notas=round(corr, 3), formas=(sc0.shape, sc1.shape), zonas_shp=zn["n"], crs_zonas=srs.GetAuthorityCode(None),
                unidade_declividade=fb1.grep("graus", "Declividade")[:2]), s0 + s1)

# D. restricao = faixa de 40 m da trilha real (evitar): a rota tem de sair da trilha; KML; japones
faixa = buffered_trail_gpkg(f"{B}/trilha_real.gpkg", f"{OUT}/faixa_trilha.gpkg", 40.0, 32723)
r, fb, e, s = run(base(dem_mq, f"{OUT}/mq_D.kml", f"{B}/inicio.geojson", f"{B}/fim.geojson",
                       CONSTRAINT_LAYER=faixa, CONSTRAINT_BUFFER_M=0.0, CONSTRAINT_MODE=0, OUTPUT_FORMAT=2), lang="ja")
if e: record("MQ-D restricao evita a trilha real", False, str(e)[-300:], s)
else:
    ag = agreement(r["OUTPUT_ROUTE"], f"{B}/trilha_real.gpkg", buffers=(40.0,))
    aux = open(r["OUTPUT_TRANSITABILITY"] + ".aux.xml", encoding="utf-8").read()
    kml = vec(r["OUTPUT_VECTOR"]); ksrs = osr.SpatialReference(); ksrs.ImportFromWkt(kml["wkt"])
    record("MQ-D restricao 'evitar' sobre a trilha real; KML; legenda em japones", ag["40m"]["rota_no_buffer_da_trilha"] < 0.05 and "緩" in aux and ksrs.GetAuthorityCode(None) == "4326",
           dict(rota_dentro_da_faixa_proibida=ag["40m"]["rota_no_buffer_da_trilha"], legenda_ja=("緩" in aux), kml_crs=ksrs.GetAuthorityCode(None),
                restricao=fb.grep("Restricoes", "restricao")[:2]), s)

# E. modo penalizar (8x) e modelos de custo alternativos rodam e dao rotas diferentes
lens = {}
for model in (0, 1, 2):
    r, fb, e, s = run(base(dem_mq, f"{OUT}/mq_E{model}.gpkg", f"{B}/marins.geojson", f"{B}/itaguare.geojson", ROUTE_COST_MODEL=model,
                           CONSTRAINT_LAYER=faixa, CONSTRAINT_MODE=1, GENERATE_ZONES=False))
    lens[model] = None if e else (round(vec(r["OUTPUT_ROUTE"])["attrs"]["compr_m"]), vec(r["OUTPUT_ROUTE"])["attrs"].get("tempo_h"))
record("MQ-E tres modelos de custo + restricao 'penalizar'", all(v is not None for v in lens.values()) and lens[2][1] is not None and lens[0][1] is None,
       dict(inverso=lens[0], exponencial=lens[1], tobler=lens[2]), None)

# =====================================================================
# CEARA: Parque Estadual das Carnaubas (Copernicus GLO-90 real)
# =====================================================================
dem_ce = "/home/claude/work/caat/carnaubas_dem.tif"
a_ce, _, _ = raster(dem_ce)
print(f"\n== Ceara: MDE {a_ce.shape}, {np.nanmin(a_ce):.0f}-{np.nanmax(a_ce):.0f} m ==")
pts = json.load(open("/home/claude/work/caat/pontos_carnaubas.json"))
ce_a = point_file(f"{OUT}/ce_a.geojson", [pts["origem"][:2]]); ce_b = point_file(f"{OUT}/ce_b.geojson", [pts["destino"][:2]])
# trilha real do Ceara (trajeto 1 de janeiro) como gpkg
tr1 = ogr.GetDriverByName("LIBKML").Open(f"{TRILHAS}/trajeto_1_janeiro.kml")
lines = []
for i in range(tr1.GetLayerCount()):
    for f in tr1.GetLayer(i):
        g = f.GetGeometryRef()
        if g and "LINE" in g.GetGeometryName(): lines.append(g.Clone())
o = ogr.GetDriverByName("GPKG").CreateDataSource(f"{OUT}/ce_trilha.gpkg"); s4 = osr.SpatialReference(); s4.ImportFromEPSG(4326)
ly = o.CreateLayer("t", srs=s4, geom_type=ogr.wkbMultiLineString); f = ogr.Feature(ly.GetLayerDefn())
merged = lines[0] if len(lines) == 1 else ogr.ForceToMultiLineString(lines[0])
for g in lines[1:]: merged = merged.Union(g)
f.SetGeometry(ogr.ForceToMultiLineString(merged)); ly.CreateFeature(f); o = None
ce_trail = vec(f"{OUT}/ce_trilha.gpkg")
env = ce_trail["geom"].GetEnvelope()
ce_t0 = point_file(f"{OUT}/ce_t0.geojson", [ce_trail["geom"].GetGeometryRef(0).GetPoint_2D(0)[:2]])
last = ce_trail["geom"].GetGeometryRef(ce_trail["geom"].GetGeometryCount() - 1)
ce_t1 = point_file(f"{OUT}/ce_t1.geojson", [last.GetPoint_2D(last.GetPointCount() - 1)[:2]])

# A. analise completa: drenagem, umidade, faixas altimetricas, zonas caminhaveis, poligonal do parque penalizada
r, fb, e, s = run(base(dem_ce, f"{OUT}/ce_A.gpkg", ce_a, ce_b, STREAMS_FROM_DEM=True, STREAM_MIN_BASIN_KM2=0.5, WEIGHT_WETNESS=1.0,
                       ALTITUDE_BAND_THRESHOLD=True, ALTITUDE_BAND_SIZE_M=100.0, WALKABILITY_ZONES=True,
                       CONSTRAINT_LAYER="/home/claude/work/caat/carnaubas.gpkg", CONSTRAINT_BUFFER_M=0.0, CONSTRAINT_MODE=1,
                       ROUTE_MARGIN_M=6000.0, MIN_PATCH_AREA_HA=10.0), lang="en")
if e: record("CE-A Carnaubas completo", False, str(e)[-300:], s)
else:
    rt = vec(r["OUTPUT_ROUTE"]); tr, _, _ = raster(r["OUTPUT_TRANSITABILITY"]); tw = tr[np.isfinite(tr) & (tr > 0)]
    classes = {int(c): round(float((tw == c).mean()), 3) for c in range(1, 6)}
    aux = open(r["OUTPUT_TRANSITABILITY"] + ".aux.xml", encoding="utf-8").read()
    record("CE-A Carnaubas: drenagem + umidade + faixas + zonas caminhaveis + poligonal penalizada (en)", rt["n"] == 1 and vec(r["OUTPUT_VECTOR"])["n"] > 0 and "Gentle" in aux,
           dict(compr_m=round(rt["attrs"]["compr_m"]), tempo_h=round(rt["attrs"]["tempo_h"], 2), ganho_m=round(rt["attrs"].get("ganho_m", 0)),
                fracao_por_classe=classes, zonas=vec(r["OUTPUT_VECTOR"])["n"], drenagem=fb.grep("Drenagem", "drenagem", "canal", "bacia")[:2],
                restricao=fb.grep("Restricoes")[:1], crs_trabalho=fb.grep("CRS de trabalho")[:1]), s, fb.grep("AVISO")[:3])

# B. rota entre os extremos da trilha GPS real (trajeto 1) e concordancia
r, fb, e, s = run(base(dem_ce, f"{OUT}/ce_B.gpkg", ce_t0, ce_t1, GENERATE_ZONES=False, ROUTE_MARGIN_M=4000.0))
if e: record("CE-B rota vs trilha GPS", False, str(e)[-300:], s)
else:
    ag = agreement(r["OUTPUT_ROUTE"], f"{OUT}/ce_trilha.gpkg", buffers=(90.0, 250.0))
    record("CE-B rota entre os extremos do trajeto GPS real (90 m de pixel)", ag["250m"]["rota_no_buffer_da_trilha"] > 0.3, ag, s)

# C. ponto fora do MDE (o GPS que ficou ligado ate Sobral): erro claro
far = ogr.GetDriverByName("LIBKML").Open(f"{TRILHAS}/dia_20_e_21_junho.kml")
fx = None
for i in range(far.GetLayerCount()):
    for f in far.GetLayer(i):
        g = f.GetGeometryRef()
        if g and "LINE" in g.GetGeometryName():
            gg = g.GetGeometryRef(0) if g.GetGeometryCount() else g
            fx = gg.GetPoint_2D(gg.GetPointCount() - 1)[:2]
ce_far = point_file(f"{OUT}/ce_far.geojson", [fx])
r, fb, e, s = run(base(dem_ce, f"{OUT}/ce_C.gpkg", ce_a, ce_far, GENERATE_ZONES=False))
record("CE-C destino fora do MDE (GPS ate Sobral) da erro claro", e is not None and "fora da extensao" in str(e), dict(ponto=fx, erro=str(e).strip().split("\n")[-1][:200]), s)

# =====================================================================
# HIMALAIA: MDE sintetico com estatistica do Everest (3200-8848 m)
# =====================================================================
dem_hi = "/home/claude/work/exp/extremos/everest_np/dem.tif"
a_hi, gt_hi, _ = raster(dem_hi)
print(f"\n== Himalaia (sintetico): MDE {a_hi.shape}, {np.nanmin(a_hi):.0f}-{np.nanmax(a_hi):.0f} m ==")
def lonlat(gt, r, c): return (gt[0] + (c + 0.5) * gt[1], gt[3] + (r + 0.5) * gt[5])
hi_a = point_file(f"{OUT}/hi_a.geojson", [lonlat(gt_hi, 150, 150)]); hi_b = point_file(f"{OUT}/hi_b.geojson", [lonlat(gt_hi, 750, 750)])
# A. relevo extremo: transitabilidade dominada por classes altas; rota existe; chinês
r, fb, e, s = run(base(dem_hi, f"{OUT}/hi_A.gpkg", hi_a, hi_b, SLOPE_MAX=150.0, ROUTE_MARGIN_M=20000.0, WEIGHT_ROUGHNESS=1.0, MIN_PATCH_AREA_HA=20.0), lang="zh")
if e: record("HI-A Himalaia", False, str(e)[-300:], s)
else:
    rt = vec(r["OUTPUT_ROUTE"]); tr, _, _ = raster(r["OUTPUT_TRANSITABILITY"]); tw = tr[np.isfinite(tr) & (tr > 0)]
    classes = {int(c): round(float((tw == c).mean()), 3) for c in range(1, 6)}
    aux = open(r["OUTPUT_TRANSITABILITY"] + ".aux.xml", encoding="utf-8").read()
    record("HI-A Himalaia sintetico: rota em relevo extremo, VRM, legenda em chines", rt["n"] == 1 and classes[4] + classes[5] > 0.3 and ("陡" in aux or "坡" in aux),
           dict(compr_m=round(rt["attrs"]["compr_m"]), tempo_h=round(rt["attrs"]["tempo_h"], 2), alt_max_m=round(rt["attrs"].get("alt_max_m", 0)),
                fracao_por_classe=classes, zonas=vec(r["OUTPUT_VECTOR"])["n"], crs=fb.grep("CRS de trabalho")[:1]), s, fb.grep("AVISO")[:3])
    HI_LEN = rt["attrs"]["compr_m"]
# B. o mesmo MDE em pes com unidade vertical "pes" -> rota identica
a_ft = (np.nan_to_num(a_hi, nan=-9999) / 0.3048).astype("float32"); a_ft[np.isnan(a_hi)] = -9999
ds = gdal.GetDriverByName("GTiff").Create(f"{OUT}/hi_ft.tif", a_hi.shape[1], a_hi.shape[0], 1, gdal.GDT_Float32); ds.SetGeoTransform(gt_hi); ds.SetProjection(gdal.Open(dem_hi).GetProjection())
ds.GetRasterBand(1).WriteArray(a_ft); ds.GetRasterBand(1).SetNoDataValue(-9999); ds = None
r, fb, e, s = run(base(f"{OUT}/hi_ft.tif", f"{OUT}/hi_B.gpkg", hi_a, hi_b, VERTICAL_UNIT=1, SLOPE_MAX=150.0, ROUTE_MARGIN_M=20000.0, WEIGHT_ROUGHNESS=1.0, GENERATE_ZONES=False))
if e: record("HI-B pes", False, str(e)[-300:], s)
else:
    rt = vec(r["OUTPUT_ROUTE"]); record("HI-B MDE em pes (unidade vertical) reproduz a rota em metros", abs(rt["attrs"]["compr_m"] - HI_LEN) / HI_LEN < 0.01,
                                       dict(compr_m=round(rt["attrs"]["compr_m"]), compr_metros=round(HI_LEN)), s)
# C. Nepal sintetico com raster de declividade em GRAUS fornecido
np_dir = "/home/claude/work/exp/paises/nepal_himalaia"; a_np, gt_np, _ = raster(f"{np_dir}/dem.tif")
np_a = point_file(f"{OUT}/np_a.geojson", [lonlat(gt_np, 100, 100)]); np_b = point_file(f"{OUT}/np_b.geojson", [lonlat(gt_np, a_np.shape[0] - 100, a_np.shape[1] - 100)])
r, fb, e, s = run(base(f"{np_dir}/dem.tif", f"{OUT}/np_C.gpkg", np_a, np_b, DERIVE_FROM_DEM=False, INPUT_SLOPE=f"{np_dir}/slope_deg.tif",
                       INPUT_CURVH=f"{np_dir}/curv_h.tif", INPUT_CURVV=f"{np_dir}/curv_v.tif", SLOPE_UNIT=1, SLOPE_MAX=150.0, ROUTE_MARGIN_M=20000.0, GENERATE_ZONES=False), lang="fr")
record("HI-C Nepal: rasters proprios em graus (fr)", e is None and vec(r["OUTPUT_ROUTE"])["n"] == 1 if e is None else False,
       dict(erro=str(e)[-200:]) if e else dict(compr_m=round(vec(r["OUTPUT_ROUTE"])["attrs"]["compr_m"]), conversao=fb.grep("graus", "degr")[:1]), s)

# =====================================================================
# EXTRAS: polar (aviso UTM), Web Mercator, camada de memoria, idiomas restantes
# =====================================================================
dem_po = "/home/claude/work/exp/extremos/polar_86n/dem.tif"; a_po, gt_po, _ = raster(dem_po)
po_a = point_file(f"{OUT}/po_a.geojson", [lonlat(gt_po, 200, 200)]); po_b = point_file(f"{OUT}/po_b.geojson", [lonlat(gt_po, 700, 700)])
r, fb, e, s = run(base(dem_po, f"{OUT}/po.gpkg", po_a, po_b, GENERATE_ZONES=False, ROUTE_MARGIN_M=20000.0), lang="es")
record("EX-1 latitude 86 N: roda e avisa que a UTM esta fora do dominio", e is None and any("84" in w for w in fb.grep("AVISO")),
       dict(erro=str(e)[-200:]) if e else dict(aviso=fb.grep("84")[:1], compr_m=round(vec(r["OUTPUT_ROUTE"])["attrs"]["compr_m"])), s)

merc = f"{OUT}/mq_3857.tif"; gdal.Warp(merc, dem_mq, dstSRS="EPSG:3857", dstNodata=-9999)
r, fb, e, s = run(base(merc, f"{OUT}/merc.gpkg", f"{B}/marins.geojson", f"{B}/itaguare.geojson", GENERATE_ZONES=False))
ref_len = lens[2][0] if lens.get(2) else None
record("EX-2 MDE em Web Mercator e reprojetado para UTM (rota igual a do MDE geografico)", e is None and any("Mercator" in w for w in fb.grep("AVISO")) and abs(vec(r["OUTPUT_ROUTE"])["attrs"]["compr_m"] - LEN_A * 0 - vec(r0["OUTPUT_ROUTE"])["attrs"]["compr_m"]) / vec(r0["OUTPUT_ROUTE"])["attrs"]["compr_m"] < 0.05,
       dict(erro=str(e)[-200:]) if e else dict(aviso=fb.grep("Mercator")[:1], compr_m=round(vec(r["OUTPUT_ROUTE"])["attrs"]["compr_m"]), compr_ref=round(vec(r0["OUTPUT_ROUTE"])["attrs"]["compr_m"])), s)

mem = QgsVectorLayer("Polygon?crs=EPSG:32723", "mem", "memory")
from qgis.core import QgsFeature, QgsGeometry
fz = QgsFeature(); fz.setGeometry(QgsGeometry.fromWkt(vec(faixa)["geom"].ExportToWkt())); mem.dataProvider().addFeatures([fz])
r, fb, e, s = run(base(dem_mq, f"{OUT}/mem.gpkg", f"{B}/inicio.geojson", f"{B}/fim.geojson", CONSTRAINT_LAYER=mem, CONSTRAINT_MODE=0, GENERATE_ZONES=False))
record("EX-3 camada de restricao em memoria (sem arquivo)", e is None and bool(fb.grep("Camada de restricao")), dict(erro=str(e)[-200:]) if e else dict(log=fb.grep("Camada de restricao")[:1]), s)

QgsSettings().setValue("TopoTrail/language", "pt")
json.dump(RESULTS, open(f"{B}/bateria.json", "w"), ensure_ascii=False, indent=1, default=str)
n_ok = sum(1 for x in RESULTS if x["ok"]); print(f"\n===== {n_ok}/{len(RESULTS)} casos OK =====")
sys.exit(0 if n_ok == len(RESULTS) else 1)
