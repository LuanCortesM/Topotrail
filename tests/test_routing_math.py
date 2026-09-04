"""The routing mathematics, checked against independently computed answers.

The A* is the part of TopoTrail whose output a person will act on in the field,
and until now nothing verified it. These tests compare it to a plain Dijkstra
written here from scratch — a second implementation, deliberately naive, whose
only virtue is that it is obviously correct — and to closed-form values of
Tobler's function.
"""

import heapq
import math

import numpy as np
import pytest

NEIGHBOURS = ((-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
              (-1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)),
              (1, -1, math.sqrt(2)), (1, 1, math.sqrt(2)))


def reference_dijkstra(cost, start, end):
    """A deliberately plain Dijkstra with the same step model as the plugin.

    No heuristic, no early exit tricks. If A* disagrees with this, A* is wrong.
    """
    rows, cols = cost.shape
    dist = {start: 0.0}
    heap = [(0.0, start)]
    seen = set()
    while heap:
        d, node = heapq.heappop(heap)
        if node in seen:
            continue
        seen.add(node)
        if node == end:
            return d
        row, col = node
        for d_row, d_col, step in NEIGHBOURS:
            n_row, n_col = row + d_row, col + d_col
            if not (0 <= n_row < rows and 0 <= n_col < cols):
                continue
            if not np.isfinite(cost[n_row, n_col]) or not np.isfinite(cost[row, col]):
                continue
            move = (cost[row, col] + cost[n_row, n_col]) / 2.0 * step
            candidate = d + move
            if candidate < dist.get((n_row, n_col), math.inf):
                dist[(n_row, n_col)] = candidate
                heapq.heappush(heap, (candidate, (n_row, n_col)))
    return math.inf


# --------------------------------------------------------------------------
# A* correctness
# --------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(12))
def test_astar_matches_dijkstra_on_random_grids(algorithm, seed):
    """The heuristic must not cost optimality. Over twelve random cost
    surfaces, A* and a plain Dijkstra must agree to floating-point precision."""
    rng = np.random.default_rng(seed)
    cost = rng.uniform(0.5, 20.0, (18, 22))
    start, end = (1, 1), (16, 20)

    _, astar_cost = algorithm.least_cost_path(cost, start, end)
    assert astar_cost == pytest.approx(reference_dijkstra(cost, start, end), rel=1e-9)


@pytest.mark.parametrize("seed", range(6))
def test_astar_matches_dijkstra_with_obstacles(algorithm, seed):
    """Same, with a third of the grid impassable — the case where a bad
    heuristic most easily produces a suboptimal detour."""
    rng = np.random.default_rng(100 + seed)
    cost = rng.uniform(1.0, 10.0, (20, 20))
    cost[rng.random((20, 20)) < 0.33] = np.inf
    cost[1, 1] = 1.0
    cost[18, 18] = 1.0
    cost[1:19, 10] = 1.0        # guarantee a corridor exists

    try:
        _, astar_cost = algorithm.least_cost_path(cost, (1, 1), (18, 18))
    except Exception:
        assert not np.isfinite(reference_dijkstra(cost, (1, 1), (18, 18)))
        return
    assert astar_cost == pytest.approx(reference_dijkstra(cost, (1, 1), (18, 18)), rel=1e-9)


def test_path_on_uniform_cost_is_the_octile_distance(algorithm):
    """With every cell costing the same, the cheapest path is the shortest one
    on an 8-connected grid: the octile distance. For a 10x10 offset that is
    9*sqrt(2) diagonal steps."""
    cost = np.ones((15, 15))
    _, total = algorithm.least_cost_path(cost, (2, 2), (11, 11))
    assert total == pytest.approx(9 * math.sqrt(2), rel=1e-9)


def test_path_starts_and_ends_where_asked(algorithm):
    rng = np.random.default_rng(3)
    cost = rng.uniform(1.0, 5.0, (15, 15))
    cells, _ = algorithm.least_cost_path(cost, (0, 0), (14, 14))
    assert cells[0] == (0, 0) and cells[-1] == (14, 14)


def test_path_is_contiguous(algorithm):
    """Every step moves to one of the eight neighbours — no teleports."""
    rng = np.random.default_rng(5)
    cost = rng.uniform(1.0, 9.0, (20, 20))
    cells, _ = algorithm.least_cost_path(cost, (0, 0), (19, 19))
    for (r0, c0), (r1, c1) in zip(cells, cells[1:]):
        assert max(abs(r1 - r0), abs(c1 - c0)) == 1


def test_disconnected_endpoints_raise(algorithm):
    cost = np.ones((12, 12))
    cost[6, :] = np.inf          # a wall right across the grid
    with pytest.raises(Exception):
        algorithm.least_cost_path(cost, (1, 1), (10, 10))


def test_route_avoids_an_expensive_band(algorithm):
    """A cheap detour must be preferred over an expensive straight line."""
    cost = np.full((21, 21), 1.0)
    cost[10, 0:18] = 500.0       # barrier with a gap at the right edge
    cells, _ = algorithm.least_cost_path(cost, (2, 2), (18, 2))
    crossings = [c for (r, c) in cells if r == 10]
    assert min(crossings) >= 18, "the route should cross through the gap, not the barrier"


# --------------------------------------------------------------------------
# Tobler's hiking function
# --------------------------------------------------------------------------

def test_tobler_on_the_flat(algorithm):
    """W(0) = 6 exp(-3.5 * 0.05) = 5.0366 km/h, so 1000 m takes 0.19855 h."""
    expected_speed = 6.0 * math.exp(-3.5 * 0.05)
    hours = algorithm.tobler_hours(0.0, 1000.0)
    assert hours == pytest.approx(1.0 / expected_speed, rel=1e-12)
    assert 1.0 / hours == pytest.approx(expected_speed, rel=1e-12)
    assert expected_speed == pytest.approx(5.0366, abs=1e-3)


def test_tobler_is_fastest_on_a_gentle_descent_not_on_the_flat(algorithm):
    """The defining feature of the function, and the reason the router is
    anisotropic: maximum speed is at a slope of -0.05, not at zero."""
    optimum = algorithm.tobler_hours(-0.05 * 1000.0, 1000.0)
    flat = algorithm.tobler_hours(0.0, 1000.0)
    steeper_descent = algorithm.tobler_hours(-0.20 * 1000.0, 1000.0)
    assert optimum < flat
    assert optimum < steeper_descent
    assert 1.0 / optimum == pytest.approx(6.0, rel=1e-12)   # exactly the maximum


def test_tobler_is_asymmetric(algorithm):
    """Climbing 200 m over a kilometre is slower than descending the same.
    An isotropic model cannot express this; the test states the difference."""
    uphill = algorithm.tobler_hours(+200.0, 1000.0)
    downhill = algorithm.tobler_hours(-200.0, 1000.0)
    assert uphill > downhill
    # 6exp(-3.5|0.25|) against 6exp(-3.5|-0.15|): a factor of exp(0.35)
    assert uphill / downhill == pytest.approx(math.exp(3.5 * 0.10), rel=1e-9)


@pytest.mark.parametrize("rise", [-500.0, -100.0, 0.0, 100.0, 500.0])
def test_tobler_matches_the_published_formula(algorithm, rise):
    horizontal = 1000.0
    slope = rise / horizontal
    expected = (horizontal / 1000.0) / (6.0 * math.exp(-3.5 * abs(slope + 0.05)))
    assert algorithm.tobler_hours(rise, horizontal) == pytest.approx(expected, rel=1e-12)


def test_tobler_zero_distance_is_free(algorithm):
    assert algorithm.tobler_hours(10.0, 0.0) == 0.0


# --------------------------------------------------------------------------
# Anisotropic routing
# --------------------------------------------------------------------------

def test_anisotropic_route_is_direction_dependent(algorithm):
    """Uphill and downhill on the same terrain must cost different amounts.
    This is the property the isotropic model could not have, so it is the one
    that proves the anisotropic path is really using elevation."""
    rows = cols = 25
    elevation = (np.mgrid[0:rows, 0:cols][1] * 20.0).astype(np.float64)   # 20 m per cell east
    slowdown = np.ones((rows, cols))

    _, uphill = algorithm.least_cost_path(
        slowdown, (12, 2), (12, 22), elevation=elevation, pixel_size_m=30.0, anisotropic=True)
    _, downhill = algorithm.least_cost_path(
        slowdown, (12, 22), (12, 2), elevation=elevation, pixel_size_m=30.0, anisotropic=True)

    assert uphill > downhill
    # Tobler is symmetric about S = -0.05, so reversing a constant gradient S
    # multiplies the cost by exp(3.5 * 2 * 0.05) exactly, whatever S is:
    #   W(+S) / W(-S) = exp(-3.5(S + 0.05)) / exp(-3.5(0.05 - S)) = exp(-7 S)
    # and the cost is the reciprocal of the speed. Here S = 20/30 uphill.
    assert uphill / downhill == pytest.approx(math.exp(3.5 * 2 * 0.05), rel=1e-6)


def test_anisotropic_cost_is_time_in_hours(algorithm):
    """A flat 20-cell traverse at 30 m per cell is 600 m, which at Tobler's
    flat speed of 5.0366 km/h takes 0.11913 h. The accumulated cost must be
    that number, not an arbitrary index."""
    elevation = np.full((15, 25), 400.0)
    slowdown = np.ones((15, 25))
    _, hours = algorithm.least_cost_path(
        slowdown, (7, 2), (7, 22), elevation=elevation, pixel_size_m=30.0, anisotropic=True)
    expected = (20 * 30.0 / 1000.0) / (6.0 * math.exp(-3.5 * 0.05))
    assert hours == pytest.approx(expected, rel=1e-9)


def test_anisotropic_slowdown_multiplies_time(algorithm):
    """Doubling the terrain slowdown everywhere must exactly double the time."""
    elevation = np.full((15, 25), 400.0)
    _, base = algorithm.least_cost_path(
        np.ones((15, 25)), (7, 2), (7, 22),
        elevation=elevation, pixel_size_m=30.0, anisotropic=True)
    _, doubled = algorithm.least_cost_path(
        np.full((15, 25), 2.0), (7, 2), (7, 22),
        elevation=elevation, pixel_size_m=30.0, anisotropic=True)
    assert doubled == pytest.approx(2.0 * base, rel=1e-9)


def test_anisotropic_heuristic_stays_admissible(algorithm):
    """An inadmissible heuristic silently returns suboptimal routes. Compare
    against Dijkstra on the same anisotropic step costs."""
    rng = np.random.default_rng(17)
    rows = cols = 16
    elevation = np.cumsum(rng.normal(0, 8.0, (rows, cols)), axis=1) + 500.0
    slowdown = rng.uniform(1.0, 3.0, (rows, cols))
    pixel = 30.0
    start, end = (2, 2), (13, 13)

    def step_cost(a, b, length):
        rise = elevation[b] - elevation[a]
        horizontal = length * pixel
        return algorithm.tobler_hours(rise, horizontal) * (
            (slowdown[a] + slowdown[b]) / 2.0)

    dist = {start: 0.0}
    heap = [(0.0, start)]
    seen = set()
    best = math.inf
    while heap:
        d, node = heapq.heappop(heap)
        if node in seen:
            continue
        seen.add(node)
        if node == end:
            best = d
            break
        r, c = node
        for d_row, d_col, length in NEIGHBOURS:
            nr, nc = r + d_row, c + d_col
            if not (0 <= nr < rows and 0 <= nc < cols):
                continue
            candidate = d + step_cost((r, c), (nr, nc), length)
            if candidate < dist.get((nr, nc), math.inf):
                dist[(nr, nc)] = candidate
                heapq.heappush(heap, (candidate, (nr, nc)))

    _, astar = algorithm.least_cost_path(
        slowdown, start, end, elevation=elevation, pixel_size_m=pixel, anisotropic=True)
    assert astar == pytest.approx(best, rel=1e-9)


def test_anisotropic_mode_requires_elevation(algorithm):
    with pytest.raises(ValueError):
        algorithm.least_cost_path(np.ones((10, 10)), (0, 0), (9, 9), anisotropic=True)


# --------------------------------------------------------------------------
# Cost models
# --------------------------------------------------------------------------

def test_exponential_cost_holds_contrast_where_the_inverse_loses_it(algorithm):
    """The measured problem, as a test. Suitability compressed into [0.55, 0.87]
    — the real range on the Mantiqueira sheets — gives the inverse model about
    5:1 of dynamic range, while the exponential model keeps far more."""
    score = np.linspace(0.55, 0.87, 400).reshape(20, 20).astype(np.float32)

    inverse = algorithm.build_route_cost(score, algorithm.ROUTE_COST_INVERSE, 6.0)
    exponential = algorithm.build_route_cost(score, algorithm.ROUTE_COST_EXPONENTIAL, 6.0)

    inverse_contrast = inverse.max() / inverse.min()
    exponential_contrast = exponential.max() / exponential.min()

    assert inverse_contrast < 2.0
    assert exponential_contrast > 6.0
    assert exponential_contrast > inverse_contrast


def test_cost_models_all_rank_terrain_the_same_way(algorithm):
    """Whatever the transform, better terrain must never cost more."""
    score = np.linspace(0.05, 0.99, 100).reshape(10, 10).astype(np.float32)
    for model in (algorithm.ROUTE_COST_INVERSE, algorithm.ROUTE_COST_EXPONENTIAL,
                  algorithm.ROUTE_COST_TOBLER):
        cost = algorithm.build_route_cost(score, model, 6.0)
        flat_score = score.ravel()
        flat_cost = cost.ravel()
        order = np.argsort(flat_score)
        assert np.all(np.diff(flat_cost[order]) <= 1e-9), f"modelo {model} nao e monotonico"


def test_constraint_penalty_multiplies_cost(algorithm):
    score = np.full((10, 10), 0.7, np.float32)
    penalty = np.zeros((10, 10), bool)
    penalty[5, 5] = True
    cost = algorithm.build_route_cost(score, algorithm.ROUTE_COST_INVERSE, 6.0, penalty)
    assert cost[5, 5] == pytest.approx(
        cost[0, 0] * algorithm.CONSTRAINT_PENALTY_FACTOR, rel=1e-9)


def test_invalid_cells_are_impassable_in_every_model(algorithm):
    score = np.full((8, 8), 0.6, np.float32)
    score[3, 3] = np.nan
    for model in (algorithm.ROUTE_COST_INVERSE, algorithm.ROUTE_COST_EXPONENTIAL,
                  algorithm.ROUTE_COST_TOBLER):
        cost = algorithm.build_route_cost(score, model, 6.0)
        assert not np.isfinite(cost[3, 3])


# --------------------------------------------------------------------------
# What the field calibration proved, kept as executable claims
# --------------------------------------------------------------------------

def _rolling_terrain(seed=4, rows=60, cols=60):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:rows, 0:cols].astype(float)
    elevation = (300 + 40 * np.sin(x / 9) + 30 * np.cos(y / 7)
                 + rng.normal(0, 5, (rows, cols)))
    slowdown = 1 + 0.5 * rng.random((rows, cols))
    return elevation, slowdown


@pytest.mark.parametrize("vmax", [2.4, 3.0, 5.0, 8.0])
def test_the_route_does_not_depend_on_tobler_s_maximum_speed(algorithm, vmax):
    """The single most consequential result of the field calibration.

    110 hours of GPS showed Tobler's 6 km/h to be too fast for field survey work
    by a factor of 1.7 to 3.1. That sounds fatal for a routing tool, and it is
    not: A* compares costs, and scaling the speed by a constant divides every
    cost by that same constant, leaving the ordering -- and therefore the chosen
    path -- untouched. The error lands entirely on the reported duration, which
    scales exactly by 6 / vmax.

    So this test pins two things at once: the route is identical, and the cost
    scales by precisely the ratio of the speeds, with no residual.
    """
    elevation, slowdown = _rolling_terrain()
    original = algorithm.TOBLER_MAX_SPEED_KMH
    try:
        reference_path, reference_cost = algorithm.least_cost_path(
            slowdown, (5, 5), (54, 54), elevation=elevation,
            pixel_size_m=30.0, anisotropic=True)
        algorithm.TOBLER_MAX_SPEED_KMH = vmax
        path, cost = algorithm.least_cost_path(
            slowdown, (5, 5), (54, 54), elevation=elevation,
            pixel_size_m=30.0, anisotropic=True)
    finally:
        algorithm.TOBLER_MAX_SPEED_KMH = original

    assert path == reference_path, "the walking speed must not move the route"
    assert cost == pytest.approx(reference_cost * original / vmax, rel=1e-12)


def test_the_route_does_depend_on_the_decay(algorithm):
    """The converse, and the reason the decay was left at its published value
    rather than replaced by the field estimate: it does move the route. The
    calibration could not separate 1.3 from 3.5 with any confidence, so the
    published constant stands -- but this test records that the choice matters,
    so that nobody later assumes it is as harmless as the speed.
    """
    elevation, slowdown = _rolling_terrain()
    original = algorithm.TOBLER_DECAY
    try:
        reference_path, _ = algorithm.least_cost_path(
            slowdown, (5, 5), (54, 54), elevation=elevation,
            pixel_size_m=30.0, anisotropic=True)
        algorithm.TOBLER_DECAY = 1.3
        path, _ = algorithm.least_cost_path(
            slowdown, (5, 5), (54, 54), elevation=elevation,
            pixel_size_m=30.0, anisotropic=True)
    finally:
        algorithm.TOBLER_DECAY = original

    shared = len(set(path) & set(reference_path)) / len(path)
    assert shared < 0.5, "the decay must be able to change the route"
