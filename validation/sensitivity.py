"""O resultado negativo e real ou artefato? Tres controles."""
import glob, os, numpy as np, tracks, speed_slope as ss
from scipy.optimize import curve_fit

BASE = "/mnt/user-data/uploads/02 TOPOTRAIL/Shapes/Trilhas para Teste"
CAAT = ss.Dem("caatinga_utm24s.tif"); MANT = ss.Dem("mantiqueira_utm23s.tif")
def region(lon): return (CAAT,"caatinga") if lon.mean() > -43 else (MANT,"mantiqueira")

def collect(window_m, pause_s, use_gps_elevation=False, region_name="caatinga",
            skip_car=True):
    old = ss.PAUSE_S; ss.PAUSE_S = pause_s
    G, V = [], []
    for f in sorted(glob.glob(BASE+"/*")):
        if f.endswith(".shp"): continue
        if skip_car and "20_e_21" in f: continue
        for lon, lat, ele, t in tracks.read_any(f):
            if not np.isfinite(t).all(): continue
            dem, name = region(lon)
            if name != region_name: continue
            if use_gps_elevation:
                class Fake:
                    epsg = dem.epsg
                    def __init__(s, z): s.z = z; s._i = 0
                    def sample(s, x, y): return s.z
                d = Fake(ele)
            else:
                d = dem
            g, v, _, _ = ss.windows(lon, lat, t, d, window_m)
            G.append(g); V.append(v)
    ss.PAUSE_S = old
    return np.concatenate(G), np.concatenate(V)

def model(g, vmax, decay, opt):
    return np.log(vmax) - decay*np.abs(g+opt)

def fit(g, v):
    ok = np.isfinite(g) & np.isfinite(v) & (v > 0)
    g, v = g[ok], v[ok]
    if len(g) < 20: return None
    p, cov = curve_fit(model, g, np.log(v), p0=(2.5,3.5,0.05), maxfev=40000,
                       bounds=([0.2,0.0,-0.4],[10,30,0.4]))
    r2 = 1 - np.var(np.log(v)-model(g,*p))/np.var(np.log(v))
    return len(g), p, np.sqrt(np.diag(cov))[1], r2

print("A. Comprimento da janela  (MDE 90 m, pausa 120 s, caatinga)")
print(f"{'janela':>8s} {'n':>5s} {'vmax':>6s} {'decay':>7s} {'+-':>6s} {'otimo':>7s} {'R2':>7s}")
for w in (90, 135, 180, 270, 360, 540, 720):
    r = fit(*collect(w, 120.0))
    if r: n,p,e,r2 = r; print(f"{w:8d} {n:5d} {p[0]:6.2f} {p[1]:7.2f} {e:6.2f} {p[2]:+7.3f} {r2:7.3f}")

print("\nB. Limiar de pausa  (janela 180 m)")
print(f"{'pausa_s':>8s} {'n':>5s} {'vmax':>6s} {'decay':>7s} {'R2':>7s}")
for ps in (20, 30, 60, 120, 300, 1e9):
    r = fit(*collect(180, ps))
    if r: n,p,e,r2 = r; print(f"{ps:8.0f} {n:5d} {p[0]:6.2f} {p[1]:7.2f} {r2:7.3f}")

print("\nC. Gradiente do GPS em vez do MDE  (dilucao de regressao)")
print(f"{'fonte':>10s} {'janela':>7s} {'n':>5s} {'vmax':>6s} {'decay':>7s} {'+-':>6s} {'R2':>7s}")
for w in (180, 360):
    for gps in (False, True):
        r = fit(*collect(w, 120.0, use_gps_elevation=gps))
        if r:
            n,p,e,r2 = r
            print(f"{'GPS' if gps else 'MDE':>10s} {w:7d} {n:5d} {p[0]:6.2f} {p[1]:7.2f} {e:6.2f} {r2:7.3f}")

print("\nD. Mantiqueira (MDE 30 m), janela curta")
for w in (60, 90, 120):
    r = fit(*collect(w, 120.0, region_name="mantiqueira"))
    print(f"  janela {w} m:", "poucos dados" if not r else
          f"n={r[0]} vmax={r[1][0]:.2f} decay={r[1][1]:.2f} R2={r[3]:.3f}")
