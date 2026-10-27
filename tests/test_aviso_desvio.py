"""Aviso de desvio pela declividade maxima: a rota existe, mas contorna terreno acima do limite.

Em 23 de 95 trilhas reais a trilha sobe trecho que o MDE de 30 m ve acima de 85%, e ali a rota a 85% desviava,
as vezes por quilometros. O aviso compara a rota com a rota sem o limite e so dispara quando o desvio e longo:
ao menos 25% e 500 m a mais, e a rota sem limite de fato passa por terreno acima dele.
"""

import numpy as np
import pytest


def _parede(altura_pct=120.0):
    """Planalto com uma parede acima do limite na coluna 20, aberta so nas linhas de baixo."""
    declividade = np.full((40, 40), 10.0)
    declividade[:36, 20] = altura_pct
    return declividade


def _contorno():
    """Desce pela coluna 5, cruza pela linha 38 e sobe pela coluna 35."""
    return ([(r, 5) for r in range(5, 39)] + [(38, c) for c in range(6, 36)]
            + [(r, 35) for r in range(37, 4, -1)])


def _atravessa():
    return [(5, c) for c in range(5, 36)]


def test_comprimento_conta_o_passo_diagonal(algorithm):
    assert algorithm.path_length_m([(0, 0), (0, 1), (1, 2)], 30.0) == pytest.approx(30.0 + 30.0 * 2 ** 0.5)
    assert algorithm.path_length_m([(3, 3)], 30.0) == 0.0


def test_desvio_longo_avisa_e_diz_quanto_subir(algorithm):
    d = algorithm.slope_detour(_contorno(), _atravessa(), _parede(120.0), 85.0, 30.0)
    assert d["avisar"]
    assert d["razao"] == pytest.approx(d["comprimento_m"] / d["comprimento_sem_limite_m"])
    assert d["razao"] > 3
    assert d["declividade_que_encurta_pct"] == 120
    # a rota sem limite entra e sai da celula da parede: dois passos de 30 m
    assert d["metros_acima_do_limite"] == pytest.approx(60.0)


def test_desvio_curto_nao_avisa(algorithm):
    rota = [(5, c) for c in range(5, 18)] + [(6, 18), (7, 19), (7, 20)] + [(6, 21)] + [(5, c) for c in range(22, 36)]
    d = algorithm.slope_detour(rota, _atravessa(), _parede(120.0), 85.0, 30.0)
    assert d["razao"] < algorithm.DETOUR_WARN_RATIO
    assert not d["avisar"]


def test_desvio_proporcional_mas_de_poucos_metros_nao_avisa(algorithm):
    # a mesma geometria em celulas de 5 m: tres vezes mais longa, mas so ~300 m a mais
    d = algorithm.slope_detour(_contorno(), _atravessa(), _parede(120.0), 85.0, 5.0)
    assert d["razao"] > 3
    assert d["comprimento_m"] - d["comprimento_sem_limite_m"] < algorithm.DETOUR_WARN_MIN_M
    assert not d["avisar"]


def test_rota_perto_da_reta_nao_faz_a_segunda_rota(algorithm, monkeypatch):
    # 50 passos em linha reta: nem a rota sem limite poderia ser 25% mais curta
    score = np.ones((3, 60), dtype=np.float32)
    score[0, 30] = np.nan
    livre = np.ones((3, 60), dtype=np.float32)
    chamadas = []
    monkeypatch.setattr(algorithm, "multi_leg_route", lambda *a, **k: chamadas.append(1))
    rota = [(1, c) for c in range(5, 56)]
    assert algorithm.check_slope_detour(
        score, livre, [(1, 5), (1, 55)], rota, np.full((3, 60), 10.0), 85.0,
        algorithm.ROUTE_COST_TOBLER, 1.0, None, np.zeros((3, 60)), 30.0, True) is None
    assert chamadas == []


def test_sem_terreno_acima_do_limite_nao_avisa(algorithm):
    # a rota sem limite tambem nao passa por cima do limite: o desvio nao e da declividade
    d = algorithm.slope_detour(_contorno(), _atravessa(), _parede(60.0), 85.0, 30.0)
    assert d["metros_acima_do_limite"] == 0.0
    assert not d["avisar"]
