"""Regressoes dos defeitos achados na auditoria matematica e geografica (0.14).

Cada teste reproduz o defeito como ele foi medido, com o numero que saia antes
da correcao no comentario, para que a suite conte a historia.
"""

import numpy as np
import pytest

from conftest import inclined_plane


# ---- 1. borda de nodata --------------------------------------------------

def test_slope_next_to_nodata_is_the_true_slope(terrain, transform_10m):
    """Antes: 247% na primeira coluna valida de uma rampa de 30% a 2000 m."""
    dem = inclined_plane(40, 40, 10.0, 0.3) + 2000.0
    dem[:, :5] = np.nan
    slope = terrain.slope_percent_from_dem(dem, transform_10m)
    ring = slope[:, 5]
    assert np.all(np.isfinite(ring))
    assert np.allclose(ring, 30.0, atol=0.5), (ring.min(), ring.max())
    assert np.all(np.isnan(slope[:, :5]))


def test_interior_nodata_hole_does_not_create_cliffs(terrain, transform_10m):
    """Antes: vizinhos do buraco a 195-255%."""
    dem = inclined_plane(30, 30, 10.0, 0.3) + 2000.0
    dem[15, 15] = np.nan
    slope = terrain.slope_percent_from_dem(dem, transform_10m)
    neighbours = slope[14:17, 14:17][np.isfinite(slope[14:17, 14:17])]
    assert np.allclose(neighbours, 30.0, atol=0.5)
    curv_h, curv_v = terrain.curvatures_from_dem(dem, transform_10m)
    assert np.nanmax(np.abs(curv_v)) < 1e-6
    vrm = terrain.vector_ruggedness(dem, transform_10m)
    assert np.nanmax(vrm) < 1e-6


def test_twi_is_defined_up_to_the_nodata_edge(hydrology, transform_10m):
    dem = inclined_plane(30, 30, 10.0, 0.1) + 500.0
    dem[:, :4] = np.nan
    _channels, twi, _metrics = hydrology.analyse_hydrology(dem, transform_10m, 100.0)
    valid = np.isfinite(dem)
    # Toda celula valida do MDE tem TWI; nenhuma invalida tem.
    assert np.all(np.isfinite(twi[valid]))
    assert np.all(np.isnan(twi[~valid]))


def test_degenerate_rasters_are_rejected_with_a_message(terrain, transform_10m):
    for shape in ((1, 20), (20, 1), (1, 1)):
        with pytest.raises(ValueError, match="2 x 2"):
            terrain.slope_percent_from_dem(np.ones(shape), transform_10m)


# ---- 2. CRS projetado nao metrico ---------------------------------------

def test_feet_and_mercator_are_not_metric(algorithm):
    """So roda com o OSR real; o stub da suite nao sabe unidades."""
    osr = pytest.importorskip("osgeo.osr")
    if not hasattr(osr.SpatialReference(), "GetLinearUnits"):
        pytest.skip("OSR de verdade indisponivel")
    for epsg, ok in ((32723, True), (31983, True), (2229, False), (3857, False)):
        srs = osr.SpatialReference(); srs.ImportFromEPSG(epsg)
        assert algorithm.projected_crs_is_metric(srs)[0] is ok, epsg


def test_longitude_is_normalised_before_choosing_the_utm_zone(algorithm):
    meta = {"transform": (180.5 - 0.05, 0.001, 0, -22.0, 0, -0.001), "cols": 100, "rows": 100,
            "projection": ""}
    assert algorithm.automatic_utm_crs_for_geographic_raster(meta) == "EPSG:32701"


# ---- 3. pontos e celulas -------------------------------------------------

def test_world_to_pixel_uses_floor_not_round(algorithm):
    transform = (500000.0, 30.0, 0.0, 7500000.0, 0.0, -30.0)
    # 20,6 celulas para leste: dentro da celula 20, nao da 21.
    assert algorithm.world_to_pixel(transform, 500000.0 + 20.6 * 30, 7500000.0 - 0.5 * 30) == (0, 20)
    assert algorithm.world_to_pixel(transform, 500000.0 + 21.5 * 30, 7500000.0 - 21.5 * 30) == (21, 21)
    # ida e volta pelo centro da celula e identidade
    x, y = algorithm.pixel_to_world(transform, 7, 3)
    assert algorithm.world_to_pixel(transform, x, y) == (7, 3)


# ---- 4. drenagem nunca e parede para a rota -----------------------------

def test_streams_are_a_cost_for_the_route_not_a_wall(algorithm):
    """A regra de negocio, isolada: com modo 'evitar', a camada do usuario sai
    da mascara da rota, mas a drenagem vai para a mascara de penalidade."""
    import numpy as np
    shape = (5, 5)
    valid = np.ones(shape, bool)
    stream = np.zeros(shape, bool); stream[:, 2] = True            # rio norte-sul no meio
    layer = np.zeros(shape, bool); layer[0, 0] = True              # cerca num canto
    route_mask = valid.copy(); zone_mask = valid.copy(); penalty = None
    restricted = stream | layer
    # espelho da logica de _run_algorithm no modo CONSTRAINT_AVOID
    zone_mask &= ~restricted
    route_mask &= ~layer
    penalty = stream
    assert route_mask[:, 2].all(), "a rota tem de poder cruzar o rio"
    assert not route_mask[0, 0], "a cerca continua intransponivel"
    assert not zone_mask[:, 2].any(), "as zonas continuam fora do leito"
    assert penalty[:, 2].all()
    # e o custo penalizado e finito (cruzavel), nao infinito
    score = np.full(shape, 0.5, dtype=np.float32)
    cost = algorithm.build_route_cost(score, algorithm.COST_MODEL_INVERSE if hasattr(algorithm, "COST_MODEL_INVERSE") else 0,
                                      1.0, penalty_mask=penalty)
    assert np.all(np.isfinite(cost[:, 2])) and np.all(cost[:, 2] > cost[:, 0])


# ---- 5. travessia graduada de cursos d'agua ------------------------------

def test_stream_crossing_factors_grade_by_basin_area(algorithm):
    import numpy as np
    shape = (7, 9)
    axis = np.zeros(shape, bool); axis[:, 2] = True; axis[:, 6] = True
    basin = np.full(shape, np.nan, np.float32)
    basin[:, 2] = 1.5      # corrego de cabeceira
    basin[:, 6] = 80.0     # rio
    faixa = axis.copy(); faixa[:, 1] = True; faixa[:, 3] = True; faixa[:, 5] = True; faixa[:, 7] = True
    factors, area, classes = algorithm.stream_crossing_factors(
        faixa, basin, 50.0, (0, 10.0, 0, 0, 0, -10.0), channel_axis=axis)
    assert np.all(factors[:, 0] == 1.0) and np.all(factors[:, 4] == 1.0) and np.all(factors[:, 8] == 1.0)
    assert np.all(factors[:, 1:4] == 2.0), factors[0]          # faixa herda a area do eixo
    assert np.all(~np.isfinite(factors[:, 5:8]))               # rio acima do teto: barreira
    assert np.all(classes[:, 1:4] == 0) and np.all(classes[:, 5:8] == len(algorithm.FORD_CLASSES))
    assert abs(float(area[3, 1]) - 1.5) < 1e-6 and abs(float(area[3, 7]) - 80.0) < 1e-6
    # subindo o teto, o rio vira "rio pequeno" com fator 8, cruzavel
    factors2, _, classes2 = algorithm.stream_crossing_factors(
        faixa, basin, 500.0, (0, 10.0, 0, 0, 0, -10.0), channel_axis=axis)
    assert np.all(factors2[:, 5:8] == 8.0) and np.all(classes2[:, 5:8] == 2)


def test_detect_stream_crossings_counts_runs_not_cells(algorithm):
    import numpy as np
    shape = (5, 12)
    faixa = np.zeros(shape, bool); faixa[:, 3:5] = True; faixa[:, 9] = True
    area = np.where(faixa, 2.5, np.nan).astype(np.float32); area[:, 9] = 12.0
    classes = np.where(faixa, 1, -1).astype(np.int8); classes[:, 9] = 2
    path = [(2, c) for c in range(12)]
    crossings = algorithm.detect_stream_crossings(path, faixa, area, classes)
    assert len(crossings) == 2
    assert crossings[0]["entrada"] == (2, 3) and crossings[0]["celulas"] == 2 and crossings[0]["classe"] == 1
    assert crossings[1]["entrada"] == (2, 9) and abs(crossings[1]["area_km2"] - 12.0) < 1e-6 and crossings[1]["classe"] == 2
    # rota que nao toca a faixa: nenhuma travessia
    assert algorithm.detect_stream_crossings([(0, 0), (0, 1)], faixa, area, classes) == []


def test_build_route_cost_accepts_factor_arrays_with_barriers(algorithm):
    import numpy as np
    score = np.full((3, 3), 0.5, np.float32)
    factor = np.ones((3, 3)); factor[:, 1] = 4.0; factor[0, 1] = np.inf
    cost = algorithm.build_route_cost(score, 0, 1.0, penalty_mask=factor)
    assert abs(cost[1, 1] / cost[1, 0] - 4.0) < 1e-9
    assert not np.isfinite(cost[0, 1])
