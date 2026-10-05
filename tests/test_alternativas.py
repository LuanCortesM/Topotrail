"""Corredor de rotas quase otimas.

O grafo vetorizado (route_graph_edges) tem de ser o mesmo modelo de passo do A*
-- senao o corredor descreve outro problema --, e o corredor tem de conter a
rota otima e crescer com a folga.
"""

import numpy as np
import pytest


def _cena(seed, rows=24, cols=28, barreiras=0.12):
    rng = np.random.default_rng(seed)
    custo = rng.uniform(1.0, 3.0, size=(rows, cols))
    custo[rng.random((rows, cols)) < barreiras] = np.inf
    custo[0, 0] = custo[-1, -1] = 1.0
    altitude = np.cumsum(rng.normal(0, 4.0, size=(rows, cols)), axis=1).astype(np.float32)
    return custo, altitude


def _a_estrela(algorithm, custo, inicio, fim, **kw):
    try:
        return algorithm.least_cost_path(custo, inicio, fim, **kw)[1]
    except Exception:
        return np.inf


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("anisotropico", [False, True])
def test_graph_distance_equals_the_astar_cost(algorithm, seed, anisotropico):
    custo, altitude = _cena(seed)
    kw = dict(elevation=altitude, pixel_size_m=30.0, anisotropic=True) if anisotropico else {}
    arestas = algorithm.route_graph_edges(custo, **kw)
    cols = custo.shape[1]
    inicio, fim = (0, 0), (custo.shape[0] - 1, cols - 1)
    dist = algorithm.cost_distances(arestas, custo.size, 0)
    esperado = _a_estrela(algorithm, custo, inicio, fim, **kw)
    if np.isfinite(esperado):
        assert dist[fim[0] * cols + fim[1]] == pytest.approx(esperado, rel=1e-6)
    else:
        assert not np.isfinite(dist[fim[0] * cols + fim[1]])


def test_graph_pays_the_ford_on_the_diagonal_like_the_astar(algorithm):
    custo = np.ones((12, 12))
    vau = np.ones((12, 12))
    vau[:, 6] = 8.0                      # um curso d'agua de uma celula
    custo = custo * vau
    arestas = algorithm.route_graph_edges(custo, crossing_factor=vau)
    dist = algorithm.cost_distances(arestas, custo.size, 0)
    esperado = algorithm.least_cost_path(custo, (0, 0), (11, 11), crossing_factor=vau)[1]
    assert dist[11 * 12 + 11] == pytest.approx(esperado, rel=1e-9)


def test_reverse_distances_are_costs_to_the_target(algorithm):
    custo, altitude = _cena(3)
    kw = dict(elevation=altitude, pixel_size_m=30.0, anisotropic=True)
    arestas = algorithm.route_graph_edges(custo, **kw)
    cols = custo.shape[1]
    fim = custo.size - 1
    ate_fim = algorithm.cost_distances(arestas, custo.size, fim, reverse=True)
    for celula in ((0, 0), (5, 3), (10, 20)):
        esperado = _a_estrela(algorithm, custo, celula, (custo.shape[0] - 1, cols - 1), **kw)
        obtido = ate_fim[celula[0] * cols + celula[1]]
        if np.isfinite(esperado):
            assert obtido == pytest.approx(esperado, rel=1e-6)


@pytest.mark.parametrize("seed", range(3))
def test_python_dijkstra_equals_scipy(algorithm, monkeypatch, seed):
    pytest.importorskip("scipy.sparse.csgraph")
    custo, altitude = _cena(seed)
    arestas = algorithm.route_graph_edges(custo, elevation=altitude, pixel_size_m=30.0,
                                          anisotropic=True)
    monkeypatch.setattr(algorithm.morphology, "FORCE_NUMPY", False)
    com_scipy = algorithm.cost_distances(arestas, custo.size, 0)
    monkeypatch.setattr(algorithm.morphology, "FORCE_NUMPY", True)
    sem_scipy = algorithm.cost_distances(arestas, custo.size, 0)
    assert np.allclose(com_scipy, sem_scipy, rtol=1e-12, equal_nan=True)


def test_the_optimal_route_is_inside_the_corridor_and_it_grows_with_slack(algorithm):
    custo, altitude = _cena(1, barreiras=0.05)
    kw = dict(elevation=altitude, pixel_size_m=30.0, anisotropic=True)
    rota, _ = algorithm.least_cost_path(custo, (0, 0), (23, 27), **kw)
    arestas = algorithm.route_graph_edges(custo, **kw)
    trechos = [(0, custo.size - 1)]
    areas = []
    for folga in (0.0, 0.02, 0.1, 0.3):
        mascara, relativa = algorithm.near_optimal_corridor(arestas, custo.shape, trechos, folga)
        assert all(mascara[r, c] for r, c in rota)
        assert np.nanmin(relativa[np.isfinite(relativa)]) == pytest.approx(0.0, abs=1e-9)
        areas.append(int(mascara.sum()))
    assert areas == sorted(areas) and areas[-1] > areas[0]


def test_two_equal_valleys_both_enter_the_corridor(algorithm):
    """Dois corredores identicos separados por uma crista: com folga minima o
    corredor de alternativas tem de mostrar os dois, e a rota so um."""
    custo = np.full((21, 30), 5.0)
    custo[4, 2:28] = 1.0                 # vale norte
    custo[16, 2:28] = 1.0                # vale sul, simetrico
    custo[4:17, 2] = 1.0
    custo[4:17, 27] = 1.0
    inicio, fim = (10, 2), (10, 27)
    arestas = algorithm.route_graph_edges(custo)
    cols = custo.shape[1]
    mascara, _ = algorithm.near_optimal_corridor(
        arestas, custo.shape, [(inicio[0] * cols + inicio[1], fim[0] * cols + fim[1])], 0.001)
    assert mascara[4, 15] and mascara[16, 15]
    assert not mascara[10, 15]
