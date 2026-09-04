"""The hydrology, checked against surfaces whose drainage is known on paper.

Flow accumulation is the one part of the model that cannot be eyeballed: it is
a sequential propagation over 10^6 cells and a wrong neighbour offset produces
a map that still *looks* like a drainage network. It looked like one for two
commits, while the accumulation was silently stalling. Every assertion below is
a number obtainable without running the code.
"""

import numpy as np
import pytest


def _ramp_west_to_east(rows, cols, spacing=10.0, drop_per_cell=1.0):
    """A plane descending to the east: every cell drains to its east neighbour,
    so the accumulation in each row is exactly 1, 2, 3, ... , cols."""
    col = np.mgrid[0:rows, 0:cols][1]
    return ((cols - 1 - col) * drop_per_cell).astype(np.float64)


TRANSFORM = (0.0, 10.0, 0.0, 1000.0, 0.0, -10.0)


# --------------------------------------------------------------------------
# Depression filling
# --------------------------------------------------------------------------

def test_filling_leaves_a_monotone_slope_essentially_untouched(hydrology):
    """There is nothing to fill on a surface that already drains everywhere.
    The only admissible change is the flat epsilon, 1 mm."""
    dem = _ramp_west_to_east(20, 20)
    filled = hydrology.fill_depressions(dem)
    assert np.all(filled >= dem - 1e-12)
    assert np.max(filled - dem) <= 10 * hydrology.FLAT_EPSILON_M


def test_a_pit_is_raised_to_its_spill_level(hydrology):
    """A single cell dug 50 m into a plane must come back up to the level of
    the lowest rim cell it could ever overflow through -- no higher, and not
    left as a hole."""
    dem = _ramp_west_to_east(21, 21).copy()
    original = dem[10, 10]
    dem[10, 10] = original - 50.0
    filled = hydrology.fill_depressions(dem)

    spill = min(dem[10, 11], dem[11, 11], dem[9, 11])   # the downslope rim
    assert filled[10, 10] > dem[10, 10]
    assert filled[10, 10] == pytest.approx(spill, abs=2 * hydrology.FLAT_EPSILON_M)


def test_a_flat_basin_is_filled_to_one_level(hydrology):
    """A 5x5 pan gouged out of the plane fills to a single surface, rising by
    at most one epsilon per cell across it, so that flow can cross."""
    dem = _ramp_west_to_east(25, 25).copy()
    dem[10:15, 10:15] = dem.min() - 20.0
    filled = hydrology.fill_depressions(dem)
    basin = filled[10:15, 10:15]
    assert basin.min() > dem[10, 10]
    assert basin.max() - basin.min() <= 25 * hydrology.FLAT_EPSILON_M


def test_filling_never_lowers_a_cell(hydrology):
    rng = np.random.default_rng(3)
    dem = (_ramp_west_to_east(30, 30) + rng.normal(0, 2.0, (30, 30)))
    filled = hydrology.fill_depressions(dem)
    assert np.all(filled >= dem - 1e-9)


def test_every_valid_cell_drains_after_filling(hydrology):
    """The property the whole fill exists to guarantee, and the one that failed
    silently before: no interior cell may be left without a downstream
    neighbour, or accumulation stops there."""
    rng = np.random.default_rng(5)
    dem = (_ramp_west_to_east(40, 40, drop_per_cell=0.4)
           + rng.normal(0, 3.0, (40, 40)))
    filled = hydrology.fill_depressions(dem)
    direction = hydrology.flow_direction(filled, 10.0, 10.0)
    interior = direction[1:-1, 1:-1]
    assert np.all(interior >= 0)


# --------------------------------------------------------------------------
# Flow direction
# --------------------------------------------------------------------------

def test_flow_direction_follows_the_gradient(hydrology):
    """On a plane descending east every cell points east: neighbour index 4 in
    this module's ordering. The diagonals lose because the drop is divided by
    the longer step -- which is precisely what the sqrt(2) weighting is for."""
    filled = hydrology.fill_depressions(_ramp_west_to_east(20, 20))
    direction = hydrology.flow_direction(filled, 10.0, 10.0)
    assert hydrology.NEIGHBOURS[4] == (0, 1)
    assert np.all(direction[1:-1, :-1] == 4)


def test_diagonal_wins_only_when_it_is_actually_steeper(hydrology):
    """A surface descending equally in x and y: the diagonal drop is twice the
    cardinal drop over sqrt(2) times the distance, so the diagonal is steeper
    by a factor sqrt(2) and must be chosen."""
    rows = cols = 15
    y, x = np.mgrid[0:rows, 0:cols].astype(np.float64)
    dem = (100.0 - x - y)
    direction = hydrology.flow_direction(dem, 10.0, 10.0)
    assert hydrology.NEIGHBOURS[7] == (1, 1)
    assert np.all(direction[1:-2, 1:-2] == 7)


def test_flat_surface_has_no_downstream(hydrology):
    flat = np.full((10, 10), 200.0)
    assert np.all(hydrology.flow_direction(flat, 10.0, 10.0) == -1)


# --------------------------------------------------------------------------
# Flow accumulation
# --------------------------------------------------------------------------

def test_accumulation_on_a_ramp_is_the_column_index(hydrology):
    """The closed form: on a plane draining east, the cell in column c has
    exactly c + 1 cells upslope of it, itself included."""
    rows, cols = 12, 20
    filled = hydrology.fill_depressions(_ramp_west_to_east(rows, cols))
    direction = hydrology.flow_direction(filled, 10.0, 10.0)
    valid = np.ones((rows, cols), bool)
    accumulated = hydrology.flow_accumulation(direction, valid, filled)
    expected = np.tile(np.arange(1, cols + 1), (rows, 1))
    assert np.array_equal(accumulated, expected)


def test_accumulation_conserves_cells(hydrology):
    """Every valid cell is counted once by exactly one outlet, so the
    accumulations of the cells with no downstream sum to the cell count. This
    is the invariant that a wrong neighbour offset breaks."""
    rng = np.random.default_rng(9)
    dem = (_ramp_west_to_east(30, 30, drop_per_cell=0.5)
           + rng.normal(0, 2.0, (30, 30)))
    filled = hydrology.fill_depressions(dem)
    direction = hydrology.flow_direction(filled, 10.0, 10.0)
    valid = np.ones((30, 30), bool)
    accumulated = hydrology.flow_accumulation(direction, valid, filled)
    assert accumulated[direction < 0].sum() == valid.sum()


def test_every_cell_counts_at_least_itself(hydrology):
    filled = hydrology.fill_depressions(_ramp_west_to_east(15, 15))
    direction = hydrology.flow_direction(filled, 10.0, 10.0)
    valid = np.ones((15, 15), bool)
    accumulated = hydrology.flow_accumulation(direction, valid, filled)
    assert accumulated.min() >= 1


def test_accumulation_is_monotone_downstream(hydrology):
    """A cell can never carry less than the cell that drains into it."""
    rng = np.random.default_rng(13)
    dem = (_ramp_west_to_east(25, 25, drop_per_cell=0.6)
           + rng.normal(0, 1.5, (25, 25)))
    filled = hydrology.fill_depressions(dem)
    direction = hydrology.flow_direction(filled, 10.0, 10.0)
    valid = np.ones((25, 25), bool)
    accumulated = hydrology.flow_accumulation(direction, valid, filled)

    rows, cols = accumulated.shape
    for row in range(rows):
        for col in range(cols):
            index = direction[row, col]
            if index < 0:
                continue
            d_row, d_col = hydrology.NEIGHBOURS[index]
            assert accumulated[row + d_row, col + d_col] >= accumulated[row, col]


def test_invalid_cells_carry_nothing(hydrology):
    dem = _ramp_west_to_east(15, 15).copy()
    dem[7, 7] = np.nan
    filled = hydrology.fill_depressions(dem)
    direction = hydrology.flow_direction(filled, 10.0, 10.0)
    valid = np.isfinite(dem)
    accumulated = hydrology.flow_accumulation(direction, valid, filled)
    assert accumulated[7, 7] == 0


# --------------------------------------------------------------------------
# Topographic wetness index
# --------------------------------------------------------------------------

def test_wetness_index_matches_its_closed_form(hydrology):
    """TWI = ln(a / tan beta) with a = A / w. On the east-draining ramp the
    accumulation is known exactly, the cell is 10 m square, so a = 10 * (c + 1)
    and tan beta = 0.1 for a 1 m drop per 10 m cell."""
    rows, cols = 10, 20
    filled = hydrology.fill_depressions(_ramp_west_to_east(rows, cols))
    direction = hydrology.flow_direction(filled, 10.0, 10.0)
    valid = np.ones((rows, cols), bool)
    accumulated = hydrology.flow_accumulation(direction, valid, filled)
    twi = hydrology.wetness_index(accumulated, filled, 10.0, 10.0, valid)

    columns = np.arange(1, cols + 1)
    expected = np.log((columns * 10.0 * 10.0 / 10.0) / 0.1)
    assert np.allclose(twi[2:-2, 2:-2], expected[None, 2:-2], rtol=1e-4)


def test_wetness_rises_with_contributing_area(hydrology):
    """Doubling the upslope area adds ln 2 to the index, whatever the slope."""
    filled = np.full((5, 5), 100.0)
    valid = np.ones((5, 5), bool)
    small = hydrology.wetness_index(np.full((5, 5), 100, np.int64),
                                    filled, 10.0, 10.0, valid)
    large = hydrology.wetness_index(np.full((5, 5), 200, np.int64),
                                    filled, 10.0, 10.0, valid)
    assert np.allclose(large - small, np.log(2.0), atol=1e-5)


def test_wetness_falls_with_slope(hydrology):
    """Steeper ground sheds water: halving tan beta adds ln 2 to the index."""
    accumulated = np.full((21, 21), 500, np.int64)
    valid = np.ones((21, 21), bool)
    gentle = np.mgrid[0:21, 0:21][1] * 1.0                # tan beta = 0.1
    steep = np.mgrid[0:21, 0:21][1] * 2.0                 # tan beta = 0.2
    twi_gentle = hydrology.wetness_index(accumulated, gentle, 10.0, 10.0, valid)
    twi_steep = hydrology.wetness_index(accumulated, steep, 10.0, 10.0, valid)
    assert np.allclose(twi_gentle[2:-2, 2:-2] - twi_steep[2:-2, 2:-2],
                       np.log(2.0), atol=1e-4)


def test_flat_ground_does_not_produce_infinite_wetness(hydrology):
    """ln(a / 0) is infinite, and a real DEM has flats. The floor on tan beta
    is what keeps the index finite, and it must actually bind."""
    accumulated = np.full((8, 8), 40, np.int64)
    valid = np.ones((8, 8), bool)
    twi = hydrology.wetness_index(accumulated, np.full((8, 8), 300.0),
                                  10.0, 10.0, valid)
    assert np.all(np.isfinite(twi))
    assert np.allclose(twi, np.log(400.0 / hydrology.MIN_TAN_BETA), rtol=1e-5)


# --------------------------------------------------------------------------
# The whole chain
# --------------------------------------------------------------------------

def test_channels_form_a_connected_network_down_the_valley(hydrology):
    """A V-shaped valley must produce a channel along its axis and nowhere on
    the shoulders. This is the sanity check a user performs by eye, written
    down so continuous integration performs it too."""
    rows, cols = 60, 60
    y, x = np.mgrid[0:rows, 0:cols].astype(np.float64)
    dem = (500.0 - y * 2.0 + np.abs(x - cols / 2.0) * 3.0)
    channels, twi, metrics = hydrology.analyse_hydrology(
        dem, (0.0, 30.0, 0.0, 0.0, 0.0, -30.0), min_basin_km2=0.05)

    # D8 sends the whole valley into a single line of cells, so the channel is
    # exactly one cell wide -- not a band. That is a property of the method and
    # worth pinning: a three-cell "channel" would mean flow is being duplicated.
    assert np.all(channels[10:-2, cols // 2]), "the valley floor must be a channel"
    assert channels[10:-2, cols // 2 + 1].sum() == 0, "and only one cell wide"
    assert channels[10:-2, :10].sum() == 0, "the shoulders must not be"
    assert metrics["densidade_drenagem_km_por_km2"] > 0
    assert np.nanmean(twi[:, cols // 2 - 1:cols // 2 + 2]) > np.nanmean(twi[:, :10])


def test_hydrology_refuses_degenerate_input(hydrology):
    with pytest.raises(ValueError):
        hydrology.analyse_hydrology(np.zeros((10, 10)),
                                    (0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    with pytest.raises(ValueError):
        hydrology.analyse_hydrology(np.full((10, 10), np.nan), TRANSFORM)
