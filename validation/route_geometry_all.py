"""O mesmo teste em todos os trajetos, para separar defeito de escopo."""
import sys, glob, os, numpy as np, tracks, speed_slope as ss, importlib.util
from osgeo import gdal; gdal.UseExceptions()
sys.path.insert(0, "/home/claude/work/repo/tests")
import conftest; conftest._install_stubs()
alg = sys.modules["tt_algorithm"]
def load(n):
    s=importlib.util.spec_from_file_location(n,f"/home/claude/work/repo/processing/{n}.py")
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
terrain = load("terrain")
from geom import densify, agreement
BASE = "/mnt/user-data/uploads/02 TOPOTRAIL/Shapes/Trilhas para Teste"
BUF = [60, 150, 250, 500]

print(f"\n{'trajeto':26s} {'real':>6s} {'reta':>6s} {'plug':>6s} {'sinu':>5s} "
      f"{'<250m reta':>10s} {'<250m plug':>10s} {'desv.med reta':>13s} {'plug':>7s} "
      f"{'subida real':>11s} {'plug':>6s}")
for f in sorted(glob.glob(BASE+"/*")):
    if f.endswith(".shp") or "marins" in f: continue
    for lon, lat, ele, t in tracks.read_any(f):
        if len(lon) < 200: continue
        caat = lon.mean() > -43
        src = "caatinga_utm24s.tif" if caat else "mantiqueira_utm23s.tif"
        dem = ss.Dem(src)
        tx, ty = ss.project(lon, lat, dem.epsg); tx, ty = np.asarray(tx), np.asarray(ty)
        straight = np.hypot(tx[-1]-tx[0], ty[-1]-ty[0])
        if straight < 500: continue           # ida e volta ao mesmo ponto: sem sentido
        pad = 1500.0
        gdal.Warp("/tmp/rg.tif", src, outputBounds=(tx.min()-pad,ty.min()-pad,
                                                    tx.max()+pad,ty.max()+pad), dstNodata=-9999)
        d = gdal.Open("/tmp/rg.tif"); gt = d.GetGeoTransform()
        z = d.GetRasterBand(1).ReadAsArray().astype(np.float32); z[z==-9999]=np.nan
        if z.size > 4_000_000: continue
        slope, ch, cv = terrain.derive_terrain(z, gt)
        score = np.where(np.isfinite(z),
                         (alg.normalize_cost(slope,0.,50.)+alg.normalize_curvature_preference(ch)
                          +alg.normalize_curvature_preference(cv))/3., np.nan)
        rcs = lambda x,y: (int((y-gt[3])/gt[5]), int((x-gt[0])/gt[1]))
        cost = alg.build_route_cost(score, alg.ROUTE_COST_TOBLER, 6.0)
        try:
            path,_ = alg.least_cost_path(cost, rcs(tx[0],ty[0]), rcs(tx[-1],ty[-1]),
                                         elevation=z.astype(np.float64),
                                         pixel_size_m=gt[1], anisotropic=True)
        except Exception as e:
            print(f"{os.path.basename(f)[:24]:26s} falhou: {e}"); continue
        px = gt[0]+(np.array([p[1] for p in path])+.5)*gt[1]
        py = gt[3]+(np.array([p[0] for p in path])+.5)*gt[5]
        rx, ry, rlen = densify(tx, ty, 10.)
        mx, my, mlen = densify(px, py, 10.)
        sx = np.linspace(tx[0],tx[-1],600); sy = np.linspace(ty[0],ty[-1],600)
        a_s, d_s = agreement(rx,ry,sx,sy,BUF)
        a_p, d_p = agreement(rx,ry,mx,my,BUF)
        prof = lambda x,y: z[np.clip(((y-gt[3])/gt[5]).astype(int),0,z.shape[0]-1),
                             np.clip(((x-gt[0])/gt[1]).astype(int),0,z.shape[1]-1)]
        gain = lambda x,y: float(np.nansum(np.clip(np.diff(prof(x,y)),0,None)))
        print(f"{os.path.basename(f)[:24]:26s} {rlen/1000:6.2f} {straight/1000:6.2f} "
              f"{mlen/1000:6.2f} {rlen/straight:5.2f} {100*a_s[2]:9.1f}% {100*a_p[2]:9.1f}% "
              f"{np.median(d_s):12.0f}m {np.median(d_p):6.0f}m "
              f"{gain(rx,ry):10.0f}m {gain(mx,my):5.0f}m")
