"""O MDE sintetico da bateria reproduz o regime de declividade do Khumbu real?

Resposta medida: nao. Ele reproduz a FAIXA DE ALTITUDE do Everest, nao o relevo.
A cena sintetica e cerca de duas vezes mais ingreme que o transecto real (54,6%
contra 27,6% de declividade mediana no mesmo passo de 250 m) e tem tres vezes
mais terreno na classe 5 (22,0% contra 7,1%). A diferenca estrutural e maior que
a de escala: o incremento de altitude entre amostras consecutivas tem
autocorrelacao +0,63 no Khumbu real, +0,25 na Mantiqueira e +0,26 nas Carnaubas
-- encostas reais sao longas e coerentes --, contra -0,13 na cena sintetica, que
e a assinatura de ruido.

Isso nao invalida a cena como teste de esforco, que e o uso declarado: uma
superficie pior que a real e um caso pior que o real. Invalida a frase que
dizia "gerado com a estatistica de relevo da regiao do Everest".

Transecto real: 100 pontos de SRTM 90 m ao longo de 24,8 km a 28,0000 N,
de 86,7500 a 87,0017 E, passo de 250 m. Atravessa o glaciar do Khumbu, Gorak
Shep e sobe ate 8.262 m no macico do Everest.
"""
import numpy as np
from osgeo import gdal
gdal.UseExceptions()

REAL = [5552,5603,5519,5439,5405, 5423,5425,5420,5503,5720,
        5698,5584,5579,5599,5685, 5949,6165,6198,6069,5510,
        5520,5457,5405,5389,5378, 5375,5383,5561,5570,5594,
        5701,5520,5400,5354,5387, 5470,5403,5344,5292,5277,
        5281,5302,5304,5311,5334, 5444,5528,5590,5648,5870,
        6183,6441,6694,6901,7046, 7030,6961,6931,6905,6921,
        7018,7082,7123,7175,7225, 7324,7406,7519,7649,7737,
        7886,8067,8220,8262,8102, 7840,7631,7459,7277,7086,
        6934,6784,6632,6450,6396, 6307,6176,6191,6102,5747,
        5588,5503,5428,5391,5387, 5382,5378,5356,5341,5322]
PASSO = 250.0
real = np.array(REAL, dtype=float)
assert real.size == 100

def perfil(z, passo):
    d = np.abs(np.diff(z)) / passo * 100.0      # declividade ao longo do transecto, %
    return d

dr = perfil(real, PASSO)

# transectos equivalentes no MDE sintetico, no mesmo passo de 250 m
ds = gdal.Open("/home/claude/work/exp/extremos/everest_np/dem.tif")
sin = ds.GetRasterBand(1).ReadAsArray().astype(float)
gt = ds.GetGeoTransform()
px_m = abs(gt[1]) * 111320.0 * np.cos(np.radians(28.0))     # graus -> m
salto = max(1, int(round(PASSO / px_m)))
linhas = np.linspace(50, sin.shape[0] - 50, 40).astype(int)
ds_list = []
for i in linhas:
    corte = sin[i, ::salto]
    if corte.size >= 100:
        ds_list.append(perfil(corte[:100], PASSO))
sint = np.concatenate(ds_list)

print(f"pixel do MDE sintetico: {px_m:.0f} m  ->  amostrado a cada {salto} celulas ({salto*px_m:.0f} m)")
print(f"transectos sinteticos: {len(ds_list)} linhas x 99 passos = {sint.size} amostras\n")
print(f"{'grandeza':34s} {'Khumbu real':>12s} {'sintetico':>12s}")
print("-" * 60)
for rot, f in (("altitude minima (m)", lambda a: a.min()),
               ("altitude maxima (m)", lambda a: a.max()),
               ("amplitude (m)", lambda a: a.max() - a.min())):
    print(f"{rot:34s} {f(real):12.0f} {f(sin):12.0f}")
print("-" * 60)
for rot, q in (("declividade p50 (%)", 50), ("declividade p75 (%)", 75),
               ("declividade p90 (%)", 90), ("declividade p99 (%)", 99)):
    print(f"{rot:34s} {np.percentile(dr,q):12.1f} {np.percentile(sint,q):12.1f}")
print(f"{'declividade maxima (%)':34s} {dr.max():12.1f} {sint.max():12.1f}")
print(f"{'fracao acima de 100% (classe 5)':34s} {100*(dr>100).mean():11.1f}% {100*(sint>100).mean():11.1f}%")
print(f"{'fracao acima de 60% (classes 4-5)':34s} {100*(dr>60).mean():11.1f}% {100*(sint>60).mean():11.1f}%")

# autocorrelacao do desnivel: terreno real tem encostas longas, ruido nao
def autocorr1(z):
    d = np.diff(z)
    return float(np.corrcoef(d[:-1], d[1:])[0, 1])
ac_real = autocorr1(real)
ac_sint = float(np.mean([autocorr1(sin[i, ::salto][:100]) for i in linhas]))
print("-" * 60)
print(f"{'autocorrelacao do desnivel (lag 1)':34s} {ac_real:12.2f} {ac_sint:12.2f}")

# controle: a autocorrelacao distingue terreno real de ruido?
print("\ncontrole -- a mesma estatistica em terreno real brasileiro:")
for rot, caminho in (("Mantiqueira (TOPODATA 30 m)", "/home/claude/work/audit/triagem/canon_dem.tif"),
                     ("Carnaubas (GLO-90)", "/home/claude/work/caat/carnaubas_dem.tif")):
    d2 = gdal.Open(caminho)
    a = d2.GetRasterBand(1).ReadAsArray().astype(float)
    nd = d2.GetRasterBand(1).GetNoDataValue()
    if nd is not None:
        a[a == nd] = np.nan
    g = d2.GetGeoTransform()
    pm = abs(g[1]) if abs(g[1]) > 1 else abs(g[1]) * 111320.0
    s = max(1, int(round(PASSO / pm)))
    acs, decl = [], []
    for i in np.linspace(20, a.shape[0] - 20, 40).astype(int):
        c = a[i, ::s]
        c = c[np.isfinite(c)]
        if c.size < 30:
            continue
        dd = np.diff(c)
        acs.append(float(np.corrcoef(dd[:-1], dd[1:])[0, 1]))
        decl.append(np.abs(dd) / (s * pm) * 100.0)
    decl = np.concatenate(decl)
    print(f"  {rot:30s} pixel {pm:5.0f} m   autocorr {np.nanmean(acs):+.2f}   "
          f"declividade p50 {np.percentile(decl,50):5.1f}%")
