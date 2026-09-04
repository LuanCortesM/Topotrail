"""Funcoes de comparacao geometrica, sem efeitos colaterais."""
import numpy as np


def densify(x, y, step=10.0):
    """Reamostra uma polilinha a passo constante, para que a concordancia seja
    por comprimento e nao por vertice -- o GPS registra mais pontos onde se
    anda devagar, e contar vertices premiaria justamente os trechos lentos."""
    d = np.concatenate([[0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    s = np.arange(0, d[-1], step)
    return np.interp(s, d, x), np.interp(s, d, y), d[-1]


def agreement(ref_x, ref_y, mod_x, mod_y, buffers):
    """Fracao da referencia a menos de b metros da linha modelada."""
    out = []
    dmin = np.full(ref_x.shape, np.inf)
    for i in range(len(mod_x) - 1):
        ax, ay, bx, by = mod_x[i], mod_y[i], mod_x[i+1], mod_y[i+1]
        vx, vy = bx - ax, by - ay
        L2 = vx*vx + vy*vy
        t = 0.0 if L2 == 0 else np.clip(((ref_x-ax)*vx + (ref_y-ay)*vy) / L2, 0, 1)
        dmin = np.minimum(dmin, np.hypot(ref_x-(ax+t*vx), ref_y-(ay+t*vy)))
    for b in buffers:
        out.append(float(np.mean(dmin <= b)))
    return out, dmin
