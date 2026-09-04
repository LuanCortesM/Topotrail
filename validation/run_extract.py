import glob, os, pickle, numpy as np, tracks, speed_slope as ss

BASE = "/mnt/user-data/uploads/02 TOPOTRAIL/Shapes/Trilhas para Teste"
CAAT = ss.Dem("caatinga_utm24s.tif")
MANT = ss.Dem("mantiqueira_utm23s.tif")

def region(lon):
    # caatinga (Piaui/Ceara) fica perto de -41; Mantiqueira perto de -45
    return (CAAT, 180.0, "caatinga") if lon.mean() > -43 else (MANT, 60.0, "mantiqueira")

rows, store = [], {}
for f in sorted(glob.glob(BASE + "/*")):
    if f.endswith(".shp"):
        continue
    for lon, lat, ele, t in tracks.read_any(f):
        if not np.isfinite(t).all():
            continue
        dem, win, name = region(lon)
        x, y = ss.project(lon, lat, dem.epsg)
        length = float(np.sum(np.hypot(np.diff(x), np.diff(y))))
        possible = int(length // win)
        g, v, d, dt = ss.windows(lon, lat, t, dem, win)
        rows.append((os.path.basename(f), name, length / 1000.0,
                     (t[-1] - t[0]) / 3600.0, possible, len(g),
                     np.median(v) if len(g) else np.nan,
                     np.percentile(v, 95) if len(g) else np.nan))
        if len(g):
            store.setdefault(name, []).append(
                {"file": os.path.basename(f), "g": g, "v": v, "d": d, "dt": dt})

print(f"{'trilha':34s} {'regiao':11s} {'km':>7s} {'horas':>6s} {'jan':>5s} "
      f"{'usadas':>6s} {'%':>5s} {'v_med':>6s} {'v_p95':>6s}")
for r in rows:
    print(f"{r[0][:32]:34s} {r[1]:11s} {r[2]:7.2f} {r[3]:6.2f} {r[4]:5d} "
          f"{r[5]:6d} {100*r[5]/max(r[4],1):5.1f} {r[6]:6.2f} {r[7]:6.2f}")

pickle.dump(store, open("windows.pkl", "wb"))
for name, lst in store.items():
    g = np.concatenate([e["g"] for e in lst]); v = np.concatenate([e["v"] for e in lst])
    print(f"\n{name}: {len(g)} janelas, gradiente {np.percentile(g,2):+.2f} a "
          f"{np.percentile(g,98):+.2f}, velocidade mediana {np.median(v):.2f} km/h")
