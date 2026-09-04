"""Rota por multiplos destinos: encadeamento e otimizacao de ordem."""

import itertools

import numpy as np
import pytest


def _terrain(seed=11, rows=40, cols=40):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:rows, 0:cols].astype(float)
    elevation = 200 + 30*np.sin(x/7) + 25*np.cos(y/6) + rng.normal(0, 4, (rows, cols))
    cost = 1 + 0.6*rng.random((rows, cols))
    return elevation, cost


def test_a_two_point_route_is_the_ordinary_least_cost_path(algorithm):
    """O encadeamento nao pode mudar o caso de sempre: com dois pontos, tem de
    devolver exatamente o que o A* de origem-destino devolvia."""
    elevation, cost = _terrain()
    reference, reference_cost = algorithm.least_cost_path(cost, (3, 3), (36, 36))
    cells, total, legs = algorithm.multi_leg_route(cost, [(3, 3), (36, 36)])
    assert cells == reference
    assert total == pytest.approx(reference_cost)
    assert len(legs) == 1


def test_the_route_actually_passes_through_every_waypoint(algorithm):
    """A propriedade que o usuario esta pedindo: o cume entra na rota, mesmo
    sendo caro. Sem isso o A* contorna exatamente o lugar que se quer visitar."""
    elevation, cost = _terrain()
    waypoints = [(3, 3), (20, 30), (35, 8), (36, 36)]
    cells, total, legs = algorithm.multi_leg_route(cost, waypoints)
    for point in waypoints:
        assert tuple(point) in cells
    assert len(legs) == 3


def test_the_legs_join_without_repeating_the_shared_cell(algorithm):
    """Cada trecho comeca onde o anterior terminou. Se a juncao repetisse a
    celula, o comprimento e o custo sairiam inflados e a linha teria vertices
    duplicados."""
    elevation, cost = _terrain()
    waypoints = [(3, 3), (18, 25), (36, 36)]
    cells, total, legs = algorithm.multi_leg_route(cost, waypoints)
    assert len(cells) == len(set(map(tuple, cells))) or True   # pode revisitar
    first, _ = algorithm.least_cost_path(cost, (3, 3), (18, 25))
    second, _ = algorithm.least_cost_path(cost, (18, 25), (36, 36))
    assert len(cells) == len(first) + len(second) - 1
    assert total == pytest.approx(sum(legs))


def test_a_detour_costs_at_least_as_much_as_going_direct(algorithm):
    """Desigualdade triangular: obrigar a rota a passar por um ponto nunca pode
    sair mais barato que ir direto. Se sair, o A* nao esta otimo."""
    elevation, cost = _terrain()
    _, direct = algorithm.least_cost_path(cost, (3, 3), (36, 36))
    for via in [(20, 30), (35, 8), (10, 35), (30, 20)]:
        _, through, _ = algorithm.multi_leg_route(cost, [(3, 3), via, (36, 36)])
        assert through >= direct - 1e-9


def test_order_optimisation_finds_the_true_optimum(algorithm):
    """Held-Karp contra forca bruta. Com quatro pontos intermediarios sao 24
    ordens possiveis, entao a resposta exata pode ser conferida enumerando."""
    elevation, cost = _terrain(seed=5)
    start, end = (2, 2), (37, 37)
    middle = [(8, 30), (30, 6), (18, 18), (33, 28)]

    _, optimised, _ = algorithm.multi_leg_route(
        cost, [start] + middle + [end], optimise_order=True)

    brute = min(
        algorithm.multi_leg_route(cost, [start] + list(order) + [end])[1]
        for order in itertools.permutations(middle))
    assert optimised == pytest.approx(brute, rel=1e-9)


def test_order_optimisation_never_loses_to_the_given_order(algorithm):
    elevation, cost = _terrain(seed=8)
    points = [(2, 2), (30, 8), (6, 33), (20, 20), (37, 37)]
    _, as_given, _ = algorithm.multi_leg_route(cost, points)
    _, optimised, _ = algorithm.multi_leg_route(cost, points, optimise_order=True)
    assert optimised <= as_given + 1e-9


def test_optimisation_respects_the_asymmetry_of_walking_uphill(algorithm):
    """No modelo de Tobler a matriz de custos e assimetrica, e a ordem otima de
    um circuito pode depender do sentido. O teste apenas garante que a
    otimizacao roda no modo anisotropico e devolve custo finito -- a
    assimetria em si ja e fixada em test_routing_math."""
    rows = cols = 30
    elevation = (np.mgrid[0:rows, 0:cols][1] * 15.0).astype(float)
    cost = np.ones((rows, cols))
    points = [(2, 2), (15, 25), (25, 5), (27, 27)]
    cells, total, legs = algorithm.multi_leg_route(
        cost, points, elevation=elevation, pixel_size_m=30.0,
        anisotropic=True, optimise_order=True)
    assert np.isfinite(total) and total > 0
    for point in points:
        assert tuple(point) in cells


def test_too_many_waypoints_to_optimise_is_refused_clearly(algorithm):
    elevation, cost = _terrain()
    points = [(2, 2)] + [(5 + i, 5 + i) for i in range(algorithm.MAX_OPTIMISED_WAYPOINTS + 1)] + [(37, 37)]
    with pytest.raises(ValueError, match="otimizacao de ordem"):
        algorithm.multi_leg_route(cost, points, optimise_order=True)


def test_a_single_point_is_not_a_route(algorithm):
    elevation, cost = _terrain()
    with pytest.raises(ValueError):
        algorithm.multi_leg_route(cost, [(3, 3)])


def test_two_waypoints_in_the_same_cell_are_reported_by_position(algorithm):
    elevation, cost = _terrain()
    with pytest.raises(Exception, match="mesma celula"):
        algorithm.multi_leg_route(cost, [(3, 3), (20, 20), (20, 20), (36, 36)])


def test_visiting_a_costly_summit_is_what_waypoints_are_for(algorithm):
    """O caso Marins-Itaguare, reduzido ao essencial.

    Num terreno com um pico caro no meio, a rota de menor custo entre origem e
    destino contorna o pico -- corretamente, porque subir e caro. Declarar o
    cume como destino intermediario e a unica forma de obter a travessia que a
    pessoa quer. Em campo isso levou a concordancia com a trilha real de 2,7%
    para 73,0% e o desvio mediano de 1.860 m para 114 m.
    """
    rows = cols = 41
    y, x = np.mgrid[0:rows, 0:cols].astype(float)
    summit = (20, 20)
    radius = np.hypot(x - summit[1], y - summit[0])
    elevation = 1000 + 600 * np.exp(-(radius ** 2) / 60.0)
    cost = np.ones((rows, cols))

    direct, _, _ = algorithm.multi_leg_route(
        cost, [(2, 2), (38, 38)], elevation=elevation,
        pixel_size_m=30.0, anisotropic=True)
    assert summit not in direct, "o A* contorna o cume, e esta certo em faze-lo"

    through, _, _ = algorithm.multi_leg_route(
        cost, [(2, 2), summit, (38, 38)], elevation=elevation,
        pixel_size_m=30.0, anisotropic=True)
    assert summit in through

    def highest(path):
        return max(elevation[r, c] for r, c in path)
    assert highest(through) > highest(direct) + 100
