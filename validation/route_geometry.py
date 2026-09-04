"""A rota do plugin contra a trilha realmente percorrida.

O teste que faltava. Ate aqui o plugin produzia rotas plausiveis e ninguem
tinha verificado se elas passam por onde as pessoas passam. A travessia
Marins-Itaguare tem 4.064 vertices de GPS e serve de verdade de campo.

O criterio e o de Goodchild & Hunter (1997): a proporcao da linha de referencia
que cai dentro de um buffer de largura b em torno da linha modelada. Sozinho
ele nao diz nada -- qualquer rota entre os mesmos extremos acerta alguma coisa
-- entao toda concordancia aqui vem acompanhada do mesmo numero para uma
LINHA RETA entre origem e destino. A linha reta e o modelo nulo: se a rota do
plugin nao vence a linha reta, o modelo de custo nao esta contribuindo nada.
"""
import sys, numpy as np, tracks, speed_slope as ss, importlib.util
from osgeo import gdal
gdal.UseExceptions()

sys.path.insert(0, "/home/claude/work/repo/tests")
import conftest; conftest._install_stubs()
alg = sys.modules["tt_algorithm"]
def load(n):
    s = importlib.util.spec_from_file_location(n, f"/home/claude/work/repo/processing/{n}.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
terrain = load("terrain")

KML = "/mnt/user-data/uploads/02 TOPOTRAIL/Shapes/Trilhas para Teste/travessia-marins-itaguare.kml"
DEM = "mantiqueira_utm23s.tif"


from geom import densify, agreement


# --- trilha real -----------------------------------------------------------
segs = [t for t in tracks.read_any(KML) if len(t[0]) > 100]
lon, lat, ele, _ = max(segs, key=lambda t: len(t[0]))
dem = ss.Dem(DEM)
tx, ty = ss.project(lon, lat, dem.epsg)
tx, ty = np.asarray(tx), np.asarray(ty)
rx, ry, real_len = densify(tx, ty)
print(f"Travessia Marins-Itaguare: {len(lon)} vertices, {real_len/1000:.2f} km percorridos")

# --- recorte do MDE --------------------------------------------------------
pad = 2000.0
gdal.Warp("/tmp/route_dem.tif", DEM, outputBounds=(tx.min()-pad, ty.min()-pad,
                                                   tx.max()+pad, ty.max()+pad),
          dstNodata=-9999)
d = gdal.Open("/tmp/route_dem.tif"); gt = d.GetGeoTransform()
z = d.GetRasterBand(1).ReadAsArray().astype(np.float32); z[z == -9999] = np.nan
print(f"Recorte: {z.shape[1]}x{z.shape[0]} celulas de {gt[1]:.0f} m, "
      f"altitude {np.nanmin(z):.0f}-{np.nanmax(z):.0f} m")

def rc(x, y):
    return (int((y - gt[3]) / gt[5]), int((x - gt[0]) / gt[1]))
start, end = rc(tx[0], ty[0]), rc(tx[-1], ty[-1])

# --- adequabilidade, do jeito que o plugin monta ---------------------------
slope, curv_h, curv_v = terrain.derive_terrain(z, gt)
valid = np.isfinite(z)
s_slope = alg.normalize_cost(slope, 0.0, 50.0, name="declividade")
s_h = alg.normalize_curvature_preference(curv_h)
s_v = alg.normalize_curvature_preference(curv_v)
score = np.where(valid, (s_slope + s_h + s_v) / 3.0, np.nan)
print(f"Adequabilidade: P05={np.nanpercentile(score,5):.3f} "
      f"P50={np.nanpercentile(score,50):.3f} P95={np.nanpercentile(score,95):.3f}")

def path_xy(path):
    r = np.array([p[0] for p in path]); c = np.array([p[1] for p in path])
    return gt[0] + (c + 0.5)*gt[1], gt[3] + (r + 0.5)*gt[5]

BUF = [30, 60, 100, 150, 250, 500]
print(f"\n{'modelo':28s} {'km':>6s} {'sinuos':>7s} " + " ".join(f"{'<'+str(b)+'m':>7s}" for b in BUF))

straight_line = np.hypot(tx[-1]-tx[0], ty[-1]-ty[0])

# controle: linha reta
sx = np.linspace(tx[0], tx[-1], 400); sy = np.linspace(ty[0], ty[-1], 400)
a, _ = agreement(rx, ry, sx, sy, BUF)
print(f"{'LINHA RETA (controle)':28s} {straight_line/1000:6.2f} {1.00:7.2f} "
      + " ".join(f"{100*v:6.1f}%" for v in a))

results = {}
for label, model, contrast, aniso in (
        ("plugin: Tobler anisotropico", alg.ROUTE_COST_TOBLER, 6.0, True),
        ("plugin: exponencial k=6", alg.ROUTE_COST_EXPONENTIAL, 6.0, False),
        ("plugin: inverso (v0.5)", alg.ROUTE_COST_INVERSE, 6.0, False)):
    cost = alg.build_route_cost(score, model, contrast)
    path, c = alg.least_cost_path(cost, start, end, elevation=z.astype(np.float64),
                                  pixel_size_m=gt[1], anisotropic=aniso)
    px, py = path_xy(path)
    dx, dy, mlen = densify(px, py)
    a, dmin = agreement(rx, ry, px, py, BUF)
    results[label] = (a, dmin, px, py, path)
    print(f"{label:28s} {mlen/1000:6.2f} {mlen/straight_line:7.2f} "
          + " ".join(f"{100*v:6.1f}%" for v in a))

print(f"{'TRILHA REAL':28s} {real_len/1000:6.2f} {real_len/straight_line:7.2f}")

print("\nDesvio da trilha real ate cada modelo (metros):")
print(f"{'modelo':28s} {'mediana':>8s} {'P90':>8s} {'max':>8s}")
a, dstr = agreement(rx, ry, sx, sy, BUF)
print(f"{'LINHA RETA (controle)':28s} {np.median(dstr):8.0f} "
      f"{np.percentile(dstr,90):8.0f} {dstr.max():8.0f}")
for label, (a, dmin, *_ ) in results.items():
    print(f"{label:28s} {np.median(dmin):8.0f} {np.percentile(dmin,90):8.0f} {dmin.max():8.0f}")

# --------------------------------------------------------------------------
# Diagnostico: por que a rota do plugin nao reproduz esta trilha?
# --------------------------------------------------------------------------
print("\n" + "="*72)
print("DIAGNOSTICO: a trilha real esta minimizando custo?")
print("="*72)

def profile(x, y):
    col = ((x - gt[0]) / gt[1]).astype(int); row = ((y - gt[3]) / gt[5]).astype(int)
    ok = (col>=0)&(col<z.shape[1])&(row>=0)&(row<z.shape[0])
    return z[row[ok], col[ok]], score[row[ok], col[ok]], slope[row[ok], col[ok]]

def summarise(name, x, y, length):
    zz, sc, sl = profile(x, y)
    gain = float(np.nansum(np.clip(np.diff(zz), 0, None)))
    print(f"{name:28s} {length/1000:6.2f} km  cume {np.nanmax(zz):6.0f} m  "
          f"subida acumulada {gain:6.0f} m  adequab. media {np.nanmean(sc):.3f}  "
          f"declив.mediana {np.nanmedian(sl):5.1f}%")

print(f"{'':28s} {'compr':>9s}  {'':11s} {'':22s} {'':21s}")
summarise("TRILHA REAL", rx, ry, real_len)
summarise("LINHA RETA (controle)", sx, sy, straight_line)
for label, (a, dmin, px, py, path) in results.items():
    dx2, dy2, mlen = densify(px, py)
    summarise(label, dx2, dy2, mlen)

zz, sc, sl = profile(rx, ry)
print(f"\nA trilha real passa por {np.nanmax(zz):.0f} m. O ponto mais alto entre "
      f"origem e destino\nna cena inteira e {np.nanmax(z):.0f} m: a travessia sobe "
      f"deliberadamente aos cumes.")
