"""Regressoes dos defeitos achados na auditoria matematica e geografica (0.14).

Cada teste reproduz o defeito como ele foi medido, com o numero que saia antes
da correcao no comentario, para que a suite conte a historia.
"""

import numpy as np
from pathlib import Path

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
    """Chama a regra de verdade, nao uma copia dela.

    Ate a 1.1.2 este teste reimplementava a logica de `_run_algorithm` dentro
    do proprio corpo e verificava a copia -- isto e, passaria mesmo que alguem
    devolvesse a drenagem a mascara da rota, que e exatamente a regressao que
    ele existe para impedir (ver o changelog da 1.0.0: com a drenagem como
    parede a travessia Marins-Itaguare deixava de existir). A regra foi
    extraida para `combine_constraints`, e agora o teste chama essa funcao.
    """
    import numpy as np
    shape = (5, 5)
    valid = np.ones(shape, bool)
    stream = np.zeros(shape, bool)
    stream[:, 2] = True                       # rio norte-sul no meio da cena
    layer = np.zeros(shape, bool)
    layer[0, 0] = True                        # cerca num canto
    stream_factor = np.where(stream, 4.0, 1.0)

    route_mask, zone_mask, penalty, barrier, _tratamento = algorithm.combine_constraints(
        valid.copy(), valid.copy(), layer, stream_factor,
        algorithm.CONSTRAINT_AVOID)

    assert route_mask[:, 2].all(), "a rota tem de poder cruzar o rio"
    assert not route_mask[0, 0], "a cerca continua intransponivel"
    assert not zone_mask[:, 2].any(), "as zonas continuam fora do leito"
    assert not barrier[:, 2].any(), "curso vadeavel nao pode virar barreira"
    assert barrier[0, 0], "a camada em modo evitar e barreira"
    assert penalty is not None and (penalty[:, 2] == 4.0).all()

    # e o custo do leito e finito (cruzavel) e maior que o do terreno livre
    score = np.full(shape, 0.5, dtype=np.float32)
    cost = algorithm.build_route_cost(
        score, algorithm.ROUTE_COST_INVERSE, 1.0, penalty_mask=penalty)
    assert np.all(np.isfinite(cost[:, 2]))
    assert np.all(cost[:, 2] > cost[:, 1])


def test_a_stream_above_the_fordable_ceiling_is_the_only_stream_that_blocks(algorithm):
    """O teto vadeavel e a unica coisa que transforma drenagem em barreira."""
    import numpy as np
    shape = (5, 5)
    valid = np.ones(shape, bool)
    stream_factor = np.ones(shape)
    stream_factor[:, 2] = np.inf              # rio acima do teto declarado
    route_mask, _zone, penalty, barrier, _t = algorithm.combine_constraints(
        valid.copy(), valid.copy(), None, stream_factor,
        algorithm.CONSTRAINT_AVOID)
    assert not route_mask[:, 2].any(), "acima do teto a travessia nao e presumida"
    assert barrier[:, 2].all()
    assert not np.isfinite(penalty[:, 2]).any()


def test_the_route_gain_is_accumulated_climb_not_amplitude(algorithm):
    """ganho_m soma as subidas; a amplitude ate a cota maxima e outro campo.

    Ate a 1.1.2 o campo chamado `ganho_m` trazia max - inicio. Numa travessia
    em sobe-e-desce os dois numeros diferem por quase o dobro, e o valor errado
    chegou a ser citado como ganho acumulado.
    """
    altitudes = [1000.0, 1200.0, 1100.0, 1400.0, 1300.0]
    ganho = sum(max(b - a, 0.0) for a, b in zip(altitudes, altitudes[1:]))
    perda = sum(max(a - b, 0.0) for a, b in zip(altitudes, altitudes[1:]))
    assert ganho == 500.0                      # 200 + 300
    assert perda == 200.0                      # 100 + 100
    assert max(altitudes) - altitudes[0] == 400.0
    fonte = (Path(algorithm.__file__).read_text(encoding="utf-8")
             if hasattr(algorithm, "__file__") else "")
    if fonte:
        assert '"desnivel_max_m": max(route_altitudes) - route_altitudes[0]' in fonte
        assert '"ganho_m": float(sum(max(b - a, 0.0)' in fonte


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


# ---- 7. o registro de diagnostico descreve a execucao que aconteceu -------

def test_the_log_names_all_three_cost_models(algorithm):
    """Um enum de tres valores precisa de tres nomes.

    Ate a 1.1.2 o log montava esse texto com um condicional de duas vias: o
    modo Tobler, que e o padrao da janela, caia no ramo final e era gravado
    como modelo inverso.
    """
    nomes = {
        algorithm.cost_model_name(algorithm.ROUTE_COST_INVERSE),
        algorithm.cost_model_name(algorithm.ROUTE_COST_EXPONENTIAL),
        algorithm.cost_model_name(algorithm.ROUTE_COST_TOBLER),
    }
    assert len(nomes) == 3, nomes
    assert algorithm.cost_model_name(algorithm.ROUTE_COST_TOBLER) == "tobler"


def test_the_log_records_every_weight_that_enters_the_score(algorithm):
    """Os sete pesos entram no registro, nao quatro.

    A alegacao de reprodutibilidade do plugin depende disto: ate a 1.1.2 o log
    gravava altitude, declividade e as duas curvaturas, e omitia umidade,
    rugosidade e o raster extra -- justamente os que distinguem uma execucao
    da outra em relevo baixo.
    """
    fonte = Path(algorithm.__file__).read_text(encoding="utf-8")
    bloco = fonte[fonte.index('"pesos": {'):]
    bloco = bloco[:bloco.index("}")]
    for peso in ("altitude", "declividade", "curvatura_horizontal", "curvatura_vertical",
                 "umidade", "rugosidade", "raster_extra"):
        assert f'"{peso}"' in bloco, f"o log nao grava o peso {peso}"
    for parametro in ('"modelo_de_custo"', '"destinos_intermediarios"',
                      '"teto_vadeavel_km2"', '"restricao_modo"'):
        assert parametro in fonte, f"o log nao grava {parametro}"


def test_a_stream_crossed_diagonally_still_shows_up_in_the_list(algorithm):
    """A travessia que a rota corta pelo vertice tem de entrar na lista.

    A lista de travessias e o que o capitulo chama de "a parte que protege o
    usuario": cada cruzamento sai marcado para ser conferido em campo. Um passo
    diagonal entre duas celulas secas, contornando duas celulas de curso,
    cruzava o canal sem pousar nele e nao entrava na lista. Medido na cena da
    Mantiqueira, dois dos oito cruzamentos reais escapavam assim -- um quarto do
    total -- e em outra configuracao o log chegava a afirmar que a rota nao
    cruzava curso nenhum.
    """
    import numpy as np

    mask = np.zeros((9, 9), dtype=bool)
    mask[4, 3] = True                      # o canal corre na diagonal
    mask[3, 4] = True
    area = np.where(mask, 3.0, 0.0)
    classe = np.where(mask, 1, 0).astype(int)

    rota = [(2, 2), (3, 3), (4, 4), (5, 5)]   # passa pelo vertice, sem pousar no canal
    assert not any(mask[r, c] for r, c in rota)

    travessias = algorithm.detect_stream_crossings(rota, mask, area, classe)
    assert len(travessias) == 1, "a travessia diagonal nao foi detectada"
    assert travessias[0]["area_km2"] == 3.0
