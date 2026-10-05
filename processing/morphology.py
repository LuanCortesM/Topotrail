"""Componentes conexas e transformada de distancia, com ou sem SciPy.

O QGIS do Windows e do macOS traz SciPy; o do Linux (apt, Flatpak) nem sempre.
Com SciPy presente estas funcoes delegam a `scipy.ndimage` e o resultado e o de
sempre; sem ele, caem em implementacoes NumPy equivalentes:

* `label`: union-find vetorizado. Os rotulos saem na mesma ordem do SciPy (pela
  primeira celula de cada componente em varredura de linhas), entao a saida e
  identica, e nao apenas equivalente.
* `distance_transform_edt`: transformada euclidiana exata de Felzenszwalb &
  Huttenlocher (2012, Theory of Computing 8:415-428), separavel, com espacamento
  anisotropico e indice da feicao mais proxima. Em empate de distancia o indice
  pode diferir do SciPy; a distancia nao.
"""

import numpy as np

try:  # pragma: no cover - depende do ambiente
    from scipy import ndimage as _ndimage
except Exception:  # pragma: no cover
    _ndimage = None

FORCE_NUMPY = False  # testes ligam isto para exercitar o caminho sem SciPy


def has_scipy():
    return _ndimage is not None and not FORCE_NUMPY


def label(mask, connectivity=8):
    """(rotulos int32, n) das regioes True de `mask`; 0 e fundo."""
    mask = np.asarray(mask, dtype=bool)
    if connectivity not in (4, 8):
        raise ValueError("connectivity deve ser 4 ou 8")
    if has_scipy():
        estrutura = (np.ones((3, 3), dtype=bool) if connectivity == 8 else
                     np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool))
        rotulos, n = _ndimage.label(mask, structure=estrutura)
        return rotulos.astype(np.int32, copy=False), int(n)
    return _label_numpy(mask, connectivity)


def _label_numpy(mask, connectivity):
    linhas, colunas = mask.shape
    saida = np.zeros(mask.shape, dtype=np.int32)
    if not mask.any():
        return saida, 0
    tipo = np.int32 if mask.size < 2 ** 31 - 1 else np.int64
    indice = np.arange(mask.size, dtype=tipo).reshape(mask.shape)
    deslocamentos = [(0, 1), (1, 0)]
    if connectivity == 8:
        deslocamentos += [(1, 1), (1, -1)]
    origens, destinos = [], []
    for dl, dc in deslocamentos:
        c0, c1 = (0, colunas - dc) if dc >= 0 else (-dc, colunas)
        a = (slice(0, linhas - dl), slice(c0, c1))
        b = (slice(dl, linhas), slice(c0 + dc, c1 + dc))
        ligados = mask[a] & mask[b]
        origens.append(indice[a][ligados])
        destinos.append(indice[b][ligados])
    origens = np.concatenate(origens)
    destinos = np.concatenate(destinos)

    # Cada no aponta para um indice menor ou para si; a raiz de uma componente
    # termina sendo o seu menor indice, que e a primeira celula na varredura.
    pai = np.arange(mask.size, dtype=tipo)
    while True:
        while True:
            avo = pai[pai]
            if np.array_equal(avo, pai):
                break
            pai = avo
        ra, rb = pai[origens], pai[destinos]
        diferentes = ra != rb
        if not diferentes.any():
            break
        np.minimum.at(pai, np.maximum(ra[diferentes], rb[diferentes]),
                      np.minimum(ra[diferentes], rb[diferentes]))
    raizes = pai.reshape(mask.shape)[mask]
    unicas, inverso = np.unique(raizes, return_inverse=True)
    saida[mask] = inverso.astype(np.int32) + 1
    return saida, int(unicas.size)


def distance_transform_edt(features_are_false, sampling=(1.0, 1.0), return_indices=False):
    """Distancia de cada celula a celula False mais proxima, como no SciPy.

    `sampling` e (passo em y, passo em x). Com `return_indices`, devolve tambem
    (linhas, colunas) da celula False mais proxima.
    """
    entrada = np.asarray(features_are_false, dtype=bool)
    sy, sx = (float(sampling[0]), float(sampling[1]))
    if has_scipy():
        return _ndimage.distance_transform_edt(
            entrada, sampling=(sy, sx), return_indices=return_indices)
    distancia, (lin, col) = _edt_numpy(~entrada, sy, sx)
    if return_indices:
        return distancia, np.stack([lin, col])
    return distancia


def _edt_numpy(feicao, sy, sx):
    linhas, colunas = feicao.shape
    if not feicao.any():
        infinito = np.full(feicao.shape, np.inf)
        vazio = np.zeros(feicao.shape, dtype=np.intp)
        return infinito, (vazio, vazio)

    # 1) Em cada coluna, a feicao mais proxima na vertical (duas varreduras).
    idx = np.arange(linhas)[:, None]
    acima = np.maximum.accumulate(np.where(feicao, idx, -1), axis=0)
    abaixo = np.minimum.accumulate(
        np.where(feicao, idx, linhas)[::-1], axis=0)[::-1]
    d_acima = np.where(acima >= 0, idx - acima, np.inf)
    d_abaixo = np.where(abaixo < linhas, abaixo - idx, np.inf)
    usa_acima = d_acima <= d_abaixo
    linha_mais_proxima = np.where(usa_acima, acima, abaixo)
    g = (sy * np.where(usa_acima, d_acima, d_abaixo)) ** 2

    # 2) Em cada linha, envelope inferior das parabolas sx^2 (c - q)^2 + g[q],
    #    todas as linhas ao mesmo tempo.
    sx2 = sx * sx
    k = np.full(linhas, -1, dtype=np.intp)
    v = np.zeros((linhas, colunas), dtype=np.intp)
    z = np.full((linhas, colunas + 1), np.inf)
    todas = np.arange(linhas)

    def cruzamento(r, q, p):
        return (((g[r, q] + sx2 * q * q) - (g[r, p] + sx2 * p * p))
                / (2.0 * sx2 * (q - p)))

    for q in range(colunas):
        finitas = np.isfinite(g[:, q])
        if not finitas.any():
            continue
        ativas = finitas.copy()
        while True:
            r = todas[ativas & (k >= 0)]
            if r.size == 0:
                break
            s = cruzamento(r, q, v[r, k[r]])
            sai = s <= z[r, k[r]]
            ativas[r[~sai]] = False
            if not sai.any():
                break
            k[r[sai]] -= 1
        r = todas[finitas]
        vazias = r[k[r] < 0]
        k[vazias] = 0
        v[vazias, 0] = q
        z[vazias, 0] = -np.inf
        z[vazias, 1] = np.inf
        cheias = r[k[r] >= 0]
        cheias = cheias[v[cheias, k[cheias]] != q]
        if cheias.size:
            s = cruzamento(cheias, q, v[cheias, k[cheias]])
            k[cheias] += 1
            v[cheias, k[cheias]] = q
            z[cheias, k[cheias]] = s
            z[cheias, k[cheias] + 1] = np.inf

    distancia2 = np.empty((linhas, colunas))
    coluna_mais_proxima = np.empty((linhas, colunas), dtype=np.intp)
    k = np.zeros(linhas, dtype=np.intp)
    for c in range(colunas):
        while True:
            avanca = z[todas, k + 1] < c
            if not avanca.any():
                break
            k[avanca] += 1
        q = v[todas, k]
        coluna_mais_proxima[:, c] = q
        distancia2[:, c] = sx2 * (c - q) ** 2 + g[todas, q]
    linha = linha_mais_proxima[todas[:, None], coluna_mais_proxima]
    return np.sqrt(distancia2), (linha, coluna_mais_proxima)
