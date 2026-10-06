"""Quando o terreno nao cabe nos padroes, a mensagem tem de dizer o que fazer.

Medido no Khumbu (Copernicus GLO-30): com os padroes da janela a execucao
inteira parava por falta de zonas (altitude 0-2600 m), e, com a faixa
corrigida, a rota falhava pedindo "aumente a declividade maxima" sem dizer para
quanto.
"""

import numpy as np
import pytest


def _crista(altura_pct=70.0):
    """Dois planaltos separados por uma faixa de declividade conhecida."""
    declividade = np.full((20, 30), 10.0)
    declividade[:, 14:16] = altura_pct
    return declividade


def test_minimum_connecting_slope_is_the_ridge(algorithm):
    declividade = _crista(70.0)
    barreira = np.zeros(declividade.shape, dtype=bool)
    assert algorithm.minimum_connecting_slope(declividade, barreira, [(10, 2), (10, 27)], 55.0) == 70


def test_minimum_connecting_slope_none_when_a_barrier_separates(algorithm):
    declividade = _crista(70.0)
    barreira = np.zeros(declividade.shape, dtype=bool)
    barreira[:, 20] = True          # um rio intransponivel, de margem a margem
    assert algorithm.minimum_connecting_slope(declividade, barreira, [(10, 2), (10, 27)], 55.0) is None


def test_connectivity_error_names_the_slope_that_connects(algorithm):
    declividade = _crista(83.2)
    custo = np.where(declividade <= 55.0, 1.0, np.inf)
    with pytest.raises(Exception) as erro:
        algorithm.check_route_connectivity(custo, [(10, 2), (10, 27)], declividade, None, 55.0, 30.0)
    assert "84%" in str(erro.value) and "55%" in str(erro.value)


def test_connected_points_pass_silently(algorithm):
    custo = np.ones((10, 10))
    algorithm.check_route_connectivity(custo, [(0, 0), (9, 9)], None, None, 55.0)


def test_empty_mask_explains_altitude_and_slope(algorithm):
    dem = np.linspace(2800, 6500, 400).reshape(20, 20)
    declividade = np.full((20, 20), 70.0)
    valido = np.ones((20, 20), dtype=bool)
    texto = algorithm.explain_empty_mask(dem, declividade, valido, 0.0, 2600.0, 55.0)
    assert "0 a 2600 m" in texto and "2800" in texto and "6500" in texto
    assert "55%" in texto and "70%" in texto


def _cena_com_agua():
    rng = np.random.default_rng(3)
    dem = 200.0 + rng.normal(0, 3, size=(60, 80))      # terreno com relevo
    dem[:, :20] = 0.0                                    # mar achatado em 0 m
    dem[30:50, 50:70] = 512.0                            # lago achatado
    dem[5:8, 60:63] = 300.0                              # trecho plano pequeno
    return dem


def test_flat_water_separates_sea_from_lake(algorithm):
    mar, lagos = algorithm.flat_water_masks(_cena_com_agua(), pixel_area_m2=900.0,
                                            min_area_m2=200 * 900.0)
    assert mar[:, :19].all() and not mar[:, 21:].any()
    assert lagos[31:49, 51:69].all()
    assert not lagos[5:8, 60:63].any()                   # pequeno demais
    assert not (mar | lagos)[10:25, 25:45].any()         # terreno de verdade


def test_terrain_without_flats_has_no_water(algorithm):
    dem = 100.0 + np.random.default_rng(9).normal(0, 1, size=(40, 40))
    mar, lagos = algorithm.flat_water_masks(dem, pixel_area_m2=900.0, min_area_m2=9000.0)
    assert not mar.any() and not lagos.any()


def test_nodata_written_as_zero_counts_as_sea(algorithm):
    dem = 800.0 + np.random.default_rng(1).normal(0, 2, size=(40, 40))
    dem[:, 30:] = 0.0                                    # borda preenchida com zero
    mar, _ = algorithm.flat_water_masks(dem, pixel_area_m2=900.0, min_area_m2=9000.0)
    assert mar[:, 31:].all()
