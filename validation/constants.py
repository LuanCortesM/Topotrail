"""As duas constantes que faltavam, contra os mesmos dados de campo."""
import sys, glob, os, numpy as np, tracks, speed_slope as ss, importlib.util
from osgeo import gdal; gdal.UseExceptions()
from scipy.optimize import curve_fit
sys.path.insert(0, "/home/claude/work/repo/tests")
import conftest; conftest._install_stubs()
alg = sys.modules["tt_algorithm"]
def load(n):
    s=importlib.util.spec_from_file_location(n,f"/home/claude/work/repo/processing/{n}.py")
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
terrain, hydrology = load("terrain"), load("hydrology")
from geom import densify
BASE = "/mnt/user-data/uploads/02 TOPOTRAIL/Shapes/Trilhas para Teste"

# ==========================================================================
# 1. TERRAIN_SLOWDOWN_MAX: a adequabilidade explica o ritmo residual?
# ==========================================================================
# O modelo afirma: tempo = tobler(gradiente) * (1 + SLOWDOWN * (1 - S)).
# Em logaritmo isso e linear, entao o coeficiente de (1 - S) e estimavel.
print("="*74)
print("1. TERRAIN_SLOWDOWN_MAX = 2,0  --  a adequabilidade explica o ritmo?")
print("="*74)

dem = ss.Dem("caatinga_utm24s.tif"); gt = dem.ds.GetGeoTransform()
z = dem.array.astype(np.float32)
slope, ch, cv = terrain.derive_terrain(z, gt)
score = np.where(np.isfinite(z), (alg.normalize_cost(slope,0.,50.)
                 + alg.normalize_curvature_preference(ch)
                 + alg.normalize_curvature_preference(cv))/3., np.nan)

G, V, S = [], [], []
for f in sorted(glob.glob(BASE+"/*")):
    if f.endswith(".shp") or "20_e_21" in f: continue
    for lon, lat, ele, t in tracks.read_any(f):
        if not np.isfinite(t).all() or lon.mean() < -43: continue
        g, v, d, dt = ss.windows(lon, lat, t, dem, 180.0)
        if not len(g): continue
        x, y = ss.project(lon, lat, dem.epsg)
        col = np.clip(((np.asarray(x)-gt[0])/gt[1]).astype(int),0,score.shape[1]-1)
        row = np.clip(((np.asarray(y)-gt[3])/gt[5]).astype(int),0,score.shape[0]-1)
        s_track = np.nanmean(score[row, col])
        # adequabilidade media por janela: reamostra grosseiramente
        step = max(1, len(row)//len(g))
        sw = np.array([np.nanmean(score[row[i*step:(i+1)*step+1], col[i*step:(i+1)*step+1]])
                       for i in range(len(g))])
        G.append(g); V.append(v); S.append(sw)
G, V, S = np.concatenate(G), np.concatenate(V), np.concatenate(S)
ok = np.isfinite(G)&np.isfinite(V)&np.isfinite(S)&(V>0)
G, V, S = G[ok], V[ok], S[ok]
print(f"n = {len(G)} janelas;  adequabilidade P05={np.percentile(S,5):.3f} "
      f"P50={np.percentile(S,50):.3f} P95={np.percentile(S,95):.3f}")

def model(X, vmax, decay, slowdown):
    g, s = X
    return np.log(vmax) - decay*np.abs(g+0.05) - np.log1p(slowdown*(1.0-s))

p, cov = curve_fit(model, (G, S), np.log(V), p0=(3.0, 3.5, 2.0), maxfev=60000,
                   bounds=([0.2,0.,-0.95],[10.,30.,50.]))
e = np.sqrt(np.diag(cov))
r2 = 1-np.var(np.log(V)-model((G,S),*p))/np.var(np.log(V))
print(f"  vmax      = {p[0]:6.2f} +- {e[0]:.2f}")
print(f"  decay     = {p[1]:6.2f} +- {e[1]:.2f}")
print(f"  SLOWDOWN  = {p[2]:6.2f} +- {e[2]:.2f}     (o codigo usa 2,00)")
print(f"  R2 = {r2:.3f}")
# quanto a adequabilidade acrescenta sozinha
def only_tobler(g, vmax, decay): return np.log(vmax)-decay*np.abs(g+0.05)
p2,_ = curve_fit(only_tobler, G, np.log(V), p0=(3.,3.5), maxfev=40000)
r2b = 1-np.var(np.log(V)-only_tobler(G,*p2))/np.var(np.log(V))
print(f"  R2 sem o termo de terreno = {r2b:.3f}  ->  a adequabilidade acrescenta "
      f"{r2-r2b:+.3f}")
c = np.corrcoef(S, np.log(V))[0,1]
print(f"  correlacao adequabilidade x log(velocidade) = {c:+.3f}"
      f"  (esperado positivo se o termo faz sentido)")

# ==========================================================================
# 2. CONSTRAINT_PENALTY_FACTOR: as trilhas reais evitam cursos d'agua?
# ==========================================================================
print("\n" + "="*74)
print("2. CONSTRAINT_PENALTY_FACTOR = 8,0  --  ha desvio revelado de drenagem?")
print("="*74)
print("Preferencia revelada: se a trilha real cruza menos canais por km que a")
print("linha reta entre os mesmos extremos, existe evitacao a estimar.\n")
print(f"{'trajeto':26s} {'km':>6s} {'cruz.real':>10s} {'/km':>6s} "
      f"{'cruz.reta':>10s} {'/km':>6s} {'razao':>6s}")
tot_r = tot_s = tot_kr = tot_ks = 0.0
for f in sorted(glob.glob(BASE+"/*")):
    if f.endswith(".shp") or "20_e_21" in f: continue
    for lon, lat, ele, t in tracks.read_any(f):
        if len(lon) < 200 or lon.mean() < -43: continue
        x, y = ss.project(lon, lat, dem.epsg); x, y = np.asarray(x), np.asarray(y)
        straight = np.hypot(x[-1]-x[0], y[-1]-y[0])
        if straight < 500: continue
        pad = 1200.
        gdal.Warp("/tmp/hy.tif", "caatinga_utm24s.tif",
                  outputBounds=(x.min()-pad,y.min()-pad,x.max()+pad,y.max()+pad),
                  dstNodata=-9999)
        d = gdal.Open("/tmp/hy.tif"); g2 = d.GetGeoTransform()
        zz = d.GetRasterBand(1).ReadAsArray().astype(np.float32); zz[zz==-9999]=np.nan
        ch_mask, twi, met = hydrology.analyse_hydrology(zz, g2, min_basin_km2=0.5)
        def crossings(px, py):
            c = np.clip(((px-g2[0])/g2[1]).astype(int),0,ch_mask.shape[1]-1)
            r = np.clip(((py-g2[3])/g2[5]).astype(int),0,ch_mask.shape[0]-1)
            on = ch_mask[r, c].astype(int)
            return int(np.sum(np.diff(on) == 1))
        rx, ry, rlen = densify(x, y, 10.)
        sx = np.linspace(x[0],x[-1],int(straight/10)); sy = np.linspace(y[0],y[-1],int(straight/10))
        cr, cs = crossings(rx,ry), crossings(sx,sy)
        kr, ksd = rlen/1000, straight/1000
        tot_r += cr; tot_s += cs; tot_kr += kr; tot_ks += ksd
        print(f"{os.path.basename(f)[:24]:26s} {kr:6.2f} {cr:10d} {cr/kr:6.2f} "
              f"{cs:10d} {cs/ksd:6.2f} {(cr/kr)/max(cs/ksd,1e-9):6.2f}")
print(f"{'TOTAL':26s} {tot_kr:6.2f} {int(tot_r):10d} {tot_r/tot_kr:6.2f} "
      f"{int(tot_s):10d} {tot_s/tot_ks:6.2f} {(tot_r/tot_kr)/(tot_s/tot_ks):6.2f}")
