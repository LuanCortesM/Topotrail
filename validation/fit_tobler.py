"""Ajusta a funcao de Tobler aos dados observados e compara com os valores publicados."""
import pickle, numpy as np
from scipy.optimize import curve_fit

PUB = (6.0, 3.5, 0.05)
store = pickle.load(open("windows.pkl", "rb"))

def model(g, vmax, decay, opt):
    return np.log(vmax) - decay * np.abs(g + opt)

def fit(g, v, label, p0=(3.0, 3.5, 0.05)):
    ok = np.isfinite(g) & np.isfinite(v) & (v > 0)
    g, v = g[ok], v[ok]
    try:
        p, cov = curve_fit(model, g, np.log(v), p0=p0, maxfev=40000,
                           bounds=([0.2, 0.0, -0.4], [10.0, 30.0, 0.4]))
        err = np.sqrt(np.diag(cov))
    except Exception as e:
        print(label, "falhou:", e); return None
    pred = np.exp(model(g, *p))
    resid = np.log(v) - np.log(pred)
    r2 = 1 - np.var(resid) / np.var(np.log(v))
    print(f"\n{label}  (n={len(g)})")
    print(f"  vmax    = {p[0]:6.3f} +- {err[0]:.3f} km/h   (publicado {PUB[0]})")
    print(f"  decay   = {p[1]:6.3f} +- {err[1]:.3f}        (publicado {PUB[1]})")
    print(f"  optimo  = {p[2]:+6.3f} +- {err[2]:.3f}        (publicado {PUB[2]:+})")
    print(f"  R2 (log) = {r2:.3f}   desvio-padrao residual = {resid.std():.3f} (fator {np.exp(resid.std()):.2f}x)")
    # o mesmo ajuste com decay e optimo travados nos valores publicados
    def scaled(g, vmax): return model(g, vmax, PUB[1], PUB[2])
    ps, _ = curve_fit(scaled, g, np.log(v), p0=[3.0], maxfev=20000)
    residp = np.log(v) - scaled(g, *ps)
    r2p = 1 - np.var(residp) / np.var(np.log(v))
    print(f"  so reescalando Tobler: vmax = {ps[0]:.3f} km/h  ->  R2 = {r2p:.3f}"
          f"   (Tobler original vale {PUB[0]/ps[0]:.2f}x o observado)")
    return p

for name, lst in store.items():
    g = np.concatenate([e["g"] for e in lst]); v = np.concatenate([e["v"] for e in lst])
    fit(g, v, f"=== {name.upper()} — todas as trilhas")

# caatinga sem o trecho de carro
lst = [e for e in store["caatinga"] if "20_e_21" not in e["file"]]
g = np.concatenate([e["g"] for e in lst]); v = np.concatenate([e["v"] for e in lst])
fit(g, v, "=== CAATINGA — excluindo dia_20_e_21 (trecho de carro)")

print("\n\nMedianas observadas por faixa de gradiente (caatinga, sem o carro):")
bins = np.array([-0.30,-0.20,-0.13,-0.08,-0.04,-0.01,0.01,0.04,0.08,0.13,0.20,0.30])
idx = np.digitize(g, bins)
print(f"{'faixa':>16s} {'n':>4s} {'v_obs':>7s} {'Tobler':>7s} {'razao':>6s}")
for k in range(1, len(bins)):
    m = idx == k
    if m.sum() < 5: continue
    centre = (bins[k-1]+bins[k])/2
    tob = PUB[0]*np.exp(-PUB[1]*abs(centre+PUB[2]))
    print(f"{bins[k-1]:+.2f}..{bins[k]:+.2f} {m.sum():4d} {np.median(v[m]):7.2f} {tob:7.2f} {np.median(v[m])/tob:6.2f}")
