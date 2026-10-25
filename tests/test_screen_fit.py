"""A janela cabe na tela de quem usa.

Ate a 1.5.0 o piso era 940 x 720 fixo. Num notebook 1920 x 1080 a 150% o Qt
enxerga 1280 x 720, e sem a barra de tarefas sobram 672 px; num 1366 x 768 a
125% sobram 566 px e o botao Continuar ficava fora da tela.
"""

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _carregar(nome):
    """Pelo caminho, e nao por `from ui import`: no CI o pytest nao roda da raiz
    do repositorio e o pacote `ui` nao esta no caminho de importacao."""
    spec = importlib.util.spec_from_file_location("tt_" + nome, ROOT / "ui" / (nome + ".py"))
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


screen_fit = _carregar("screen_fit")

# Area util em pixels logicos (tela / escala, menos a barra de tarefas de 48 px)
TELAS = {
    "1920x1080 a 100%": (0, 0, 1920, 1032),
    "1920x1080 a 125%": (0, 0, 1536, 816),
    "1920x1080 a 150%": (0, 0, 1280, 672),
    "1366x768 a 100%": (0, 0, 1366, 720),
    "1366x768 a 125%": (0, 0, 1093, 566),
    "1280x800 a 125%": (0, 0, 1024, 592),
}


@pytest.mark.parametrize("nome", sorted(TELAS))
def test_a_janela_inteira_cabe_na_area_util(nome):
    ax, ay, aw, ah = TELAS[nome]
    r = screen_fit.fit(TELAS[nome])
    x, y = r["position"]
    largura, altura = r["size"]
    assert ax <= x and x + largura + screen_fit.FRAME[0] <= ax + aw
    assert ay <= y and y + altura + screen_fit.FRAME[1] <= ay + ah
    # o piso nao pode impedir a janela de caber
    assert r["minimum"][0] <= largura and r["minimum"][1] <= altura


def test_em_tela_grande_o_piso_de_sempre_continua():
    r = screen_fit.fit(TELAS["1920x1080 a 100%"])
    assert r["minimum"] == screen_fit.FLOOR
    assert r["size"] == screen_fit.PREFERRED


def test_em_notebook_a_125_o_piso_encolhe_ate_caber():
    r = screen_fit.fit(TELAS["1366x768 a 125%"])
    assert r["minimum"][1] < screen_fit.FLOOR[1]
    assert r["size"][1] + screen_fit.FRAME[1] <= 566


def test_centraliza_no_qgis_sem_sair_da_tela():
    # QGIS encostado no canto direito: a janela vai para perto dele, mas inteira
    r = screen_fit.fit((0, 0, 1920, 1032), center=(1900, 1000))
    x, y = r["position"]
    assert x + r["size"][0] + screen_fit.FRAME[0] <= 1920
    assert y + r["size"][1] + screen_fit.FRAME[1] <= 1032
    centro = screen_fit.fit((0, 0, 1920, 1032), center=(960, 516))
    assert abs(centro["position"][0] + (centro["size"][0] + screen_fit.FRAME[0]) / 2 - 960) <= 1


def test_segundo_monitor_a_direita():
    r = screen_fit.fit((1920, 0, 1280, 672))
    assert 1920 <= r["position"][0] < 1920 + 1280
