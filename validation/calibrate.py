"""Calibra as constantes de rota contra o objetivo certo: a geometria.

O erro do estudo anterior foi calibrar TERRAIN_SLOWDOWN_MAX contra velocidade.
Prever velocidade nunca foi funcao dele -- a funcao e escolher por onde a rota
passa. Aqui ele e ajustado contra o que de fato faz: a concordancia entre a rota
modelada e a trilha percorrida.

Sete trajetos de trabalho da caatinga, com validacao cruzada leave-one-out:
para cada trajeto, os parametros sao escolhidos usando SO os outros seis, e
avaliados no que ficou de fora. Sem isso, ajustar tres parametros a sete curvas
mede apenas a capacidade de decorar.
"""
import sys, glob, os, pickle, numpy as np, tracks, speed_slope as ss, importlib.util
from osgeo import gdal; gdal.UseExceptions()
sys.path.insert(0, "/home/claude/work/repo/tests")
import conftest; conftest._install_stubs()
alg = sys.modules["tt_algorithm"]
def load(n):
    s=importlib.util.spec_from_file_location(n,f"/home/claude/work/repo/processing/{n}.py")
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
terrain, hydrology = load("terrain"), load("hydrology")
from geom import densify, agreement
BASE = "/mnt/user-data/uploads/02 TOPOTRAIL/Shapes/Trilhas para Teste"
BUF = [250]

def build_cases():
    cases = []
    for f in sorted(glob.glob(BASE+"/*")):
        if f.endswith(".shp") or "20_e_21" in f: continue
        for lon, lat, ele, t in tracks.read_any(f):
            if len(lon) < 200 or lon.mean() < -43: continue
            dem = ss.Dem("caatinga_utm24s.tif")
            x, y = map(np.asarray, ss.project(lon, lat, dem.epsg))
            straight = np.hypot(x[-1]-x[0], y[-1]-y[0])
            if straight < 500: continue
            pad = 1500.
            gdal.Warp("/tmp/cal.tif","caatinga_utm24s.tif",
                      outputBounds=(x.min()-pad,y.min()-pad,x.max()+pad,y.max()+pad),
                      dstNodata=-9999)
            d=gdal.Open("/tmp/cal.tif"); gt=d.GetGeoTransform()
            z=d.GetRasterBand(1).ReadAsArray().astype(np.float32); z[z==-9999]=np.nan
            slope, ch, cv = terrain.derive_terrain(z, gt)
            s_slope = alg.normalize_cost(slope, 0., 50.)
            score = np.where(np.isfinite(z), (s_slope
                     + alg.normalize_curvature_preference(ch)
                     + alg.normalize_curvature_preference(cv))/3., np.nan)
            channels, twi, met = hydrology.analyse_hydrology(z, gt, min_basin_km2=0.5)
            rx, ry, rlen = densify(x, y, 10.)
            rc = lambda X,Y:(int((Y-gt[3])/gt[5]), int((X-gt[0])/gt[1]))
            cases.append(dict(name=os.path.basename(f)[:24], gt=gt, z=z.astype(np.float64),
                              score=score, chan=channels.astype(bool),
                              start=rc(x[0],y[0]), end=rc(x[-1],y[-1]),
                              rx=rx, ry=ry, straight=straight))
            print(f"  preparado: {cases[-1]['name']:26s} {z.shape} celulas")
    return cases

def evaluate(case, slowdown, decay, penalty):
    old = (alg.TERRAIN_SLOWDOWN_MAX, alg.TOBLER_DECAY, alg.CONSTRAINT_PENALTY_FACTOR)
    alg.TERRAIN_SLOWDOWN_MAX, alg.TOBLER_DECAY, alg.CONSTRAINT_PENALTY_FACTOR = \
        slowdown, decay, penalty
    try:
        mask = case["chan"] if penalty != 1.0 else None
        cost = alg.build_route_cost(case["score"], alg.ROUTE_COST_TOBLER, 6.0, mask)
        path,_ = alg.least_cost_path(cost, case["start"], case["end"],
                                     elevation=case["z"], pixel_size_m=case["gt"][1],
                                     anisotropic=True)
    except Exception:
        return 0.0, 1e9
    finally:
        alg.TERRAIN_SLOWDOWN_MAX, alg.TOBLER_DECAY, alg.CONSTRAINT_PENALTY_FACTOR = old
    gt = case["gt"]
    px = gt[0]+(np.array([p[1] for p in path])+.5)*gt[1]
    py = gt[3]+(np.array([p[0] for p in path])+.5)*gt[5]
    mx,my,_ = densify(px,py,10.)
    a, dmin = agreement(case["rx"], case["ry"], mx, my, BUF)
    return a[0], float(np.median(dmin))

print("Preparando os casos...")
cases = build_cases()
print(f"{len(cases)} trajetos.\n")

SLOW = [0.0, 0.5, 1.0, 2.0, 4.0]
DECAY = [1.3, 2.3, 3.5, 5.0]
grid = {}
print("Varredura conjunta SLOWDOWN x decay (penalidade desligada):")
header = "slow \\ decay"
print(f"{header:>12s} " + " ".join(f"{d:>7.1f}" for d in DECAY))
for sd in SLOW:
    row = []
    for dc in DECAY:
        vals = [evaluate(c, sd, dc, 1.0) for c in cases]
        grid[(sd,dc)] = vals
        row.append(np.mean([v[0] for v in vals]))
    print(f"{sd:12.1f} " + " ".join(f"{100*v:6.1f}%" for v in row))

best = max(grid, key=lambda k: np.mean([v[0] for v in grid[k]]))
print(f"\nMelhor no conjunto todo: SLOWDOWN={best[0]}, decay={best[1]}  "
      f"-> {100*np.mean([v[0] for v in grid[best]]):.1f}% de concordancia")
print(f"Padrao atual (2.0, 3.5): {100*np.mean([v[0] for v in grid[(2.0,3.5)]]):.1f}%")

print("\nValidacao cruzada leave-one-out:")
print(f"{'trajeto deixado de fora':26s} {'escolhido':>14s} {'no trajeto':>11s} {'padrao':>8s}")
loo_sel, loo_def = [], []
for i, c in enumerate(cases):
    others = lambda k: np.mean([grid[k][j][0] for j in range(len(cases)) if j != i])
    pick = max(grid, key=others)
    sel, dflt = grid[pick][i][0], grid[(2.0,3.5)][i][0]
    loo_sel.append(sel); loo_def.append(dflt)
    print(f"{c['name']:26s} {str(pick):>14s} {100*sel:10.1f}% {100*dflt:7.1f}%")
print(f"{'MEDIA':26s} {'':>14s} {100*np.mean(loo_sel):10.1f}% {100*np.mean(loo_def):7.1f}%")

print("\nPenalidade de drenagem, no melhor par:")
for pen in (0.5, 1.0, 2.0, 8.0):
    vals = [evaluate(c, best[0], best[1], pen) for c in cases]
    print(f"  fator {pen:4.1f}: concordancia {100*np.mean([v[0] for v in vals]):5.1f}%  "
          f"desvio mediano {np.mean([v[1] for v in vals]):6.0f} m")
pickle.dump({str(k): [(float(a),float(b)) for a,b in v] for k,v in grid.items()},
            open("calibration_grid.pkl","wb"))
