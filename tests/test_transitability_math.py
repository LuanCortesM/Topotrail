"""As classes de transitabilidade: limites, modificadores e resolucao."""

import numpy as np
import pytest


def _slope(values):
    return np.array(values, np.float32).reshape(1, -1)


def test_breaks_are_half_open_upwards(transitability):
    """Uma celula exatamente no limite pertence a classe de cima. 20,0% nao e
    'suave': o teste fixa a convencao para que a legenda e o codigo digam a
    mesma coisa."""
    slope = _slope([0.0, 19.99, 20.0, 34.99, 35.0, 59.99, 60.0, 99.99, 100.0, 400.0])
    classes, _ = transitability.classify(slope, np.ones(slope.shape, bool))
    assert list(classes.ravel()) == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]


def test_classes_are_monotone_in_slope(transitability):
    rng = np.random.default_rng(2)
    slope = np.sort(rng.uniform(0, 200, 500)).astype(np.float32).reshape(1, -1)
    classes, _ = transitability.classify(slope, np.ones(slope.shape, bool))
    assert np.all(np.diff(classes.ravel().astype(int)) >= 0)


def test_custom_breaks_must_increase(transitability):
    slope = _slope([10.0, 50.0])
    with pytest.raises(ValueError):
        transitability.classify(slope, np.ones(slope.shape, bool),
                                slope_breaks=(20.0, 15.0, 60.0, 100.0))


def test_modifiers_worsen_by_one_class_and_never_reach_the_top(transitability):
    """Terreno rugoso ou encharcado e pior de caminhar, mas nao vira paredao:
    um modificador pode rebaixar uma classe e nunca criar a classe 5."""
    slope = np.full((1, 200), 10.0, np.float32)          # tudo classe 1
    valid = np.ones(slope.shape, bool)
    roughness = np.linspace(0, 100, 200).astype(np.float32).reshape(1, -1)
    classes, metrics = transitability.classify(slope, valid, roughness=roughness)
    assert set(np.unique(classes)) <= {1, 2}
    assert metrics["celulas_rebaixadas_por_rugosidade"] > 0

    steep = np.full((1, 200), 90.0, np.float32)          # tudo classe 4
    classes, _ = transitability.classify(steep, valid, roughness=roughness)
    assert 5 not in np.unique(classes), "um modificador nao pode criar classe 5"


def test_only_an_explicit_block_produces_class_five_below_the_top_break(transitability):
    slope = np.full((1, 10), 10.0, np.float32)
    valid = np.ones(slope.shape, bool)
    blocked = np.zeros(slope.shape, bool)
    blocked[0, :3] = True
    classes, metrics = transitability.classify(slope, valid, blocked_mask=blocked)
    assert list(classes.ravel()) == [5, 5, 5, 1, 1, 1, 1, 1, 1, 1]
    assert metrics["celulas_bloqueadas_por_restricao"] == 3


def test_invalid_cells_get_the_nodata_class(transitability):
    slope = _slope([10.0, np.nan, 10.0])
    valid = np.array([[True, True, False]])
    classes, _ = transitability.classify(slope, valid)
    assert list(classes.ravel()) == [1, 0, 0]


def test_walkable_fraction_is_a_proportion_of_valid_area(transitability):
    classes = np.array([[0, 0, 1, 1, 2, 3, 4, 5]], np.uint8)
    # 6 celulas validas, 3 ate a classe 2
    assert transitability.walkable_fraction(classes) == pytest.approx(0.5)
    assert transitability.walkable_fraction(classes, up_to=4) == pytest.approx(5 / 6)
    assert transitability.walkable_fraction(np.zeros((3, 3), np.uint8)) is None


def test_cell_size_is_recorded_in_the_metrics(transitability):
    """A distribuicao das classes depende fortemente da resolucao -- no mesmo
    terreno, a classe 1 vai de 48,2% a 30 m para 75,7% a 250 m. Qualquer numero
    tirado do mapa e ininterpretavel sem o tamanho da celula, entao ele tem de
    sair junto nas metricas."""
    slope = np.full((1, 10), 10.0, np.float32)
    _, metrics = transitability.classify(slope, np.ones(slope.shape, bool),
                                         cell_size_m=90.0)
    assert metrics["tamanho_celula_m"] == 90.0


def test_a_coarse_cell_raises_a_warning(transitability):
    class Feedback:
        def __init__(self): self.warnings = []
        def pushInfo(self, text): pass
        def pushWarning(self, text): self.warnings.append(text)

    slope = np.full((1, 10), 10.0, np.float32)
    valid = np.ones(slope.shape, bool)

    fine = Feedback()
    transitability.classify(slope, valid, feedback=fine, cell_size_m=30.0)
    assert not fine.warnings

    coarse = Feedback()
    transitability.classify(slope, valid, feedback=coarse, cell_size_m=90.0)
    assert coarse.warnings, "90 m precisa avisar que as classes ficam brandas"


def test_the_labels_do_not_claim_a_verdict_about_the_walker(transitability):
    """Os rotulos descrevem declividade, nao capacidade. A versao anterior
    chamava a classe 5 de 'intransitavel a pe' e o GPS de campo falsificou
    isso: a maior declividade efetivamente caminhada foi 115,8%. Este teste
    impede a volta silenciosa do rotulo."""
    for labels in (transitability.CLASS_LABELS, transitability.CLASS_LABELS_EN):
        joined = " ".join(labels.values()).lower()
        assert "intransit" not in joined
        assert "not walkable" not in joined
