"""As classes de transitabilidade contra terreno realmente caminhado.

O teste e simples e falsificavel: uma trilha percorrida a pe por uma equipe de
campo, com equipamento, e por definicao transitavel. Se o mapa classifica boa
parte dela como "intransitavel", os limites 20/35/60/100% estao errados.
"""
import entorno
BASE, MDE, TMP = entorno.campo("mantiqueira", "caatinga")
import glob, os, numpy as np, tracks, speed_slope as ss
_, load = entorno.nucleo()
terrain, transit = load("terrain"), load("transitability")


for dem_path, label, lo, hi in ((MDE["mantiqueira"], "MANTIQUEIRA (MDE 30 m)", -46, -43),
                                (MDE["caatinga"], "CAATINGA (MDE 90 m)", -43, -39)):
    dem = ss.Dem(dem_path)
    gt = dem.ds.GetGeoTransform()
    slope = terrain.slope_percent_from_dem(dem.array.astype(np.float32), gt)
    valid = np.isfinite(dem.array)
    classes, _ = transit.classify(slope, valid)

    print(f"\n=== {label}")
    print(f"{'trilha':34s} {'pts':>6s} " +
          " ".join(f"{transit.CLASS_LABELS_EN[c][:9]:>10s}" for c in range(1, 6)))
    scene = np.array([(classes == c).sum() for c in range(1, 6)], float)
    allc = np.zeros(5)
    for f in sorted(glob.glob(BASE + "/*")):
        if f.endswith(".shp"): continue
        for lon, lat, ele, t in tracks.read_any(f):
            if not (lo < lon.mean() < hi): continue
            x, y = ss.project(lon, lat, dem.epsg)
            col = ((np.array(x) - gt[0]) / gt[1]).astype(int)
            row = ((np.array(y) - gt[3]) / gt[5]).astype(int)
            ok = ((col >= 0) & (col < classes.shape[1]) &
                  (row >= 0) & (row < classes.shape[0]))
            c = classes[row[ok], col[ok]]
            counts = np.array([(c == k).sum() for k in range(1, 6)], float)
            if counts.sum() == 0: continue
            allc += counts
            pct = 100 * counts / counts.sum()
            print(f"{os.path.basename(f)[:32]:34s} {int(counts.sum()):6d} " +
                  " ".join(f"{p:9.1f}%" for p in pct))
    if allc.sum():
        print(f"{'TODAS AS TRILHAS':34s} {int(allc.sum()):6d} " +
              " ".join(f"{p:9.1f}%" for p in 100*allc/allc.sum()))
        print(f"{'a cena inteira (referencia)':34s} {int(scene.sum()):6d} " +
              " ".join(f"{p:9.1f}%" for p in 100*scene/scene.sum()))
        walk = 100*(allc[0]+allc[1])/allc.sum()
        print(f"  -> {walk:.1f}% da trilha real cai nas classes 1-2 "
              f"('caminhavel'); {100*allc[4]/allc.sum():.2f}% em 'intransitavel'")
