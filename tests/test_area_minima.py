"""Area minima do fragmento automatica: 0,05% da area analisada, entre 1 e 50 ha.

Ate a 1.5.2 eram 50 ha fixos. Numa UC de ~10 mil ha isso deixava as faixas de
encosta sem zona: nas Carnaubas as zonas cobriam 4 de 10 faixas de altitude, no
MONA Mantiqueira Paulista 6 de 10. Em 15 UCs sorteadas do Cadastro Nacional, a
regra proporcional resolveu o aviso em 4 das 7 que avisavam com 50 ha, nao criou
aviso em nenhuma e, nas UCs de 100 mil ha ou mais, da os mesmos 50 ha.
"""

import pathlib
import re

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIALOG = (ROOT / "ui" / "topotrail_dialog.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("area_ha, esperado", [
    (500.0, 1.0),          # piso: UC pequena nao fica com fragmento de 0,25 ha
    (2000.0, 1.0),
    (6000.0, 3.0),
    (10000.0, 5.0),        # Carnaubas e MONA: 5,0 e 5,2 ha, a sugestao do relatorio
    (60000.0, 30.0),
    (100000.0, 50.0),      # a partir daqui, os 50 ha de antes
    (200000.0, 50.0),
])
def test_a_area_minima_automatica_acompanha_a_area(algorithm, area_ha, esperado):
    assert algorithm.automatic_min_patch_area_ha(area_ha) == pytest.approx(esperado)


def test_o_padrao_do_parametro_e_o_automatico(algorithm):
    assert algorithm.MIN_PATCH_AREA_AUTO == -1.0
    fonte = (ROOT / "processing" / "algorithm.py").read_text(encoding="utf-8")
    bloco = fonte[fonte.index("self.MIN_PATCH_AREA_HA,\n"):]
    bloco = bloco[:bloco.index("self.addParameter(")]
    assert "defaultValue=MIN_PATCH_AREA_AUTO" in bloco
    assert "minValue=MIN_PATCH_AREA_AUTO" in bloco


def test_a_janela_abre_no_automatico_e_mostra_o_nome(algorithm):
    """O minimo do campo e o valor automatico; nele o campo mostra o texto."""
    m = re.search(r"self\.min_area = _spin\(([^)]*)\)", DIALOG)
    minimo, _maximo, valor = (float(x) for x in m.group(1).split(",")[:3])
    assert minimo == algorithm.MIN_PATCH_AREA_AUTO and valor == algorithm.MIN_PATCH_AREA_AUTO
    assert '"min_area_auto", "setSpecialValueText"' in DIALOG


def test_zero_continua_desligando_o_filtro(algorithm, transform_10m):
    binario = np.zeros((20, 20), np.uint8)
    binario[2:4, 2:4] = 1                                  # 4 celulas, 0,04 ha
    saida = algorithm.filter_small_regions(binario, transform_10m, None, 0.0)
    assert int(saida.sum()) == 4
