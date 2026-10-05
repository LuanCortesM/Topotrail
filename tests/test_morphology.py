"""Componentes conexas e distancia euclidiana sem SciPy.

O caminho NumPy de `processing/morphology.py` e o que roda num QGIS sem SciPy.
Ele e conferido contra forca bruta (sempre) e contra o proprio SciPy (quando
houver): os rotulos tem de ser identicos, e as distancias iguais.
"""

import itertools

import numpy as np
import pytest


@pytest.fixture
def numpy_only(morphology, monkeypatch):
    monkeypatch.setattr(morphology, "FORCE_NUMPY", True)
    return morphology


def _brute_force_edt(feature, sy, sx):
    rows, cols = np.nonzero(feature)
    yy, xx = np.mgrid[0:feature.shape[0], 0:feature.shape[1]]
    d = np.full(feature.shape, np.inf)
    for r, c in zip(rows, cols):
        d = np.minimum(d, np.hypot(sy * (yy - r), sx * (xx - c)))
    return d


def test_eight_neighbours_join_a_diagonal_and_four_do_not(numpy_only):
    mask = np.array([[1, 0, 0],
                     [0, 1, 0],
                     [0, 0, 1]], dtype=bool)
    assert numpy_only.label(mask, 8)[1] == 1
    rotulos, n = numpy_only.label(mask, 4)
    assert n == 3
    assert list(rotulos[mask]) == [1, 2, 3]


def test_labels_follow_raster_scan_order(numpy_only):
    mask = np.array([[0, 0, 1, 1],
                     [1, 0, 0, 1],
                     [1, 0, 0, 0],
                     [0, 0, 1, 0]], dtype=bool)
    rotulos, n = numpy_only.label(mask, 8)
    assert n == 3
    assert rotulos[0, 2] == 1 and rotulos[1, 0] == 2 and rotulos[3, 2] == 3


def test_a_spiral_is_one_component(numpy_only):
    # O pior caso do union-find: um caminho longo e dobrado sobre si.
    mask = np.zeros((41, 41), dtype=bool)
    top, left, bottom, right = 0, 0, 40, 40
    while top <= bottom and left <= right:
        mask[top, left:right + 1] = True
        mask[top:bottom + 1, right] = True
        mask[bottom, left:right + 1] = True
        mask[top + 2:bottom + 1, left] = True
        if top + 2 <= bottom:
            mask[top + 2, left:right - 1] = True
        top, left, bottom, right = top + 4, left + 2, bottom - 2, right - 2
    assert numpy_only.label(mask, 4)[1] == numpy_only.label(mask, 8)[1] >= 1


def test_empty_mask_has_no_labels(numpy_only):
    rotulos, n = numpy_only.label(np.zeros((5, 4), dtype=bool))
    assert n == 0 and not rotulos.any()


@pytest.mark.parametrize("seed, density, conn", list(itertools.product(range(6), (0.35, 0.6), (4, 8))))
def test_numpy_labels_are_identical_to_scipy(morphology, monkeypatch, seed, density, conn):
    pytest.importorskip("scipy.ndimage")
    mask = np.random.default_rng(seed).random((47, 63)) < density
    monkeypatch.setattr(morphology, "FORCE_NUMPY", False)
    esperado = morphology.label(mask, conn)
    monkeypatch.setattr(morphology, "FORCE_NUMPY", True)
    obtido = morphology.label(mask, conn)
    assert obtido[1] == esperado[1]
    assert np.array_equal(obtido[0], esperado[0])


@pytest.mark.parametrize("seed, sampling", list(itertools.product(
    range(4), ((1.0, 1.0), (30.0, 30.0), (29.6, 31.2), (10.0, 3.0)))))
def test_numpy_distance_matches_brute_force(numpy_only, seed, sampling):
    rng = np.random.default_rng(seed)
    feature = rng.random((23, 31)) < 0.04
    feature[rng.integers(23), rng.integers(31)] = True
    d, (rr, cc) = numpy_only.distance_transform_edt(~feature, sampling, return_indices=True)
    assert np.allclose(d, _brute_force_edt(feature, *sampling), rtol=1e-12, atol=1e-9)
    # o indice devolvido e de uma feicao, e a distancia ate ela e a minima
    assert feature[rr, cc].all()
    yy, xx = np.mgrid[0:23, 0:31]
    assert np.allclose(np.hypot(sampling[0] * (yy - rr), sampling[1] * (xx - cc)), d)


def test_distance_is_zero_on_the_features_themselves(numpy_only):
    feature = np.zeros((6, 6), dtype=bool)
    feature[2, 3] = feature[5, 0] = True
    d = numpy_only.distance_transform_edt(~feature, (5.0, 5.0))
    assert d[2, 3] == 0 and d[5, 0] == 0 and d[0, 0] == pytest.approx(np.hypot(10.0, 15.0))


@pytest.mark.parametrize("seed", range(4))
def test_numpy_distance_equals_scipy(morphology, monkeypatch, seed):
    pytest.importorskip("scipy.ndimage")
    feature = np.random.default_rng(seed).random((70, 90)) < 0.02
    monkeypatch.setattr(morphology, "FORCE_NUMPY", False)
    esperado = morphology.distance_transform_edt(~feature, (30.0, 28.0))
    monkeypatch.setattr(morphology, "FORCE_NUMPY", True)
    obtido = morphology.distance_transform_edt(~feature, (30.0, 28.0))
    assert np.allclose(obtido, esperado, rtol=1e-12, atol=1e-9)


def _utm_wkt():
    pyproj = pytest.importorskip("pyproj")
    return pyproj.CRS.from_epsg(32723).to_wkt()


def test_minimum_area_filter_is_the_same_without_scipy(algorithm, monkeypatch):
    pytest.importorskip("scipy.ndimage")
    zonas = (np.random.default_rng(7).random((80, 90)) < 0.55).astype(np.uint8)
    transform = (500000.0, 30.0, 0.0, 7500000.0, 0.0, -30.0)
    com_scipy = algorithm.filter_small_regions(zonas, transform, _utm_wkt(), 0.5)
    monkeypatch.setattr(algorithm.morphology, "FORCE_NUMPY", True)
    sem_scipy = algorithm.filter_small_regions(zonas, transform, _utm_wkt(), 0.5)
    assert np.array_equal(com_scipy, sem_scipy)
    assert 0 < sem_scipy.sum() < zonas.sum()


def test_corner_contact_is_still_diagnosed_without_scipy(algorithm, monkeypatch):
    # Dois blocos passaveis que so se tocam pelo vertice entre (1,1) e (2,2).
    monkeypatch.setattr(algorithm.morphology, "FORCE_NUMPY", True)
    custo = np.ones((4, 4))
    custo[0:2, 2:4] = np.inf
    custo[2:4, 0:2] = np.inf
    assert algorithm._liga_apenas_pelo_canto(custo, (0, 0), (3, 3)) is True
