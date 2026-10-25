"""Tamanho e posicao da janela a partir da area util da tela.

Ate a 1.5.0 a janela tinha piso fixo de 940 x 720 e abria onde o sistema
quisesse. Num notebook 1920 x 1080 com escala de 150% -- o padrao do Windows
em telas de 13 e 14 polegadas -- o Qt enxerga 1280 x 720, e sem a barra de
tarefas sobram 672 px: a faixa de baixo ficava fora da tela. Num 1366 x 768 a
125% sumia tambem o botao Continuar, e quem nao sabe arrastar a janela pelo
titulo nao passava do primeiro passo.

O conteudo aguenta bem menos que o piso, porque cada passo rola. Entao o piso
continua onde cabe e encolhe ate a tela onde nao cabe.

Sem Qt aqui de proposito: a conta e testada sem QGIS (tests/test_screen_fit.py)
e a janela so passa a area util e o centro desejado.
"""

# Tamanho de abertura quando a tela permite: um pouco mais alto que o piso,
# porque os passos 2 e 3 sao longos e cada pixel a mais e rolagem a menos.
PREFERRED = (980, 820)
# O piso da 1.5.0, mantido nas telas em que cabe.
FLOOR = (940, 720)
# Barra de titulo e bordas, que o Qt nao conta no tamanho da janela. Estimadas
# por cima (Windows 11 a 100%: 31 px de titulo, 8 de borda invisivel).
FRAME = (16, 40)
# Folga entre a janela e a borda da area util.
GAP = 8


def fit(available, center=None):
    """Piso, tamanho e posicao da janela numa area util.

    available: (x, y, largura, altura) da area util da tela, em pixels logicos.
    center: (x, y) onde centralizar -- o centro da janela do QGIS --, ou None
    para o centro da area util.

    Devolve {"minimum": (l, a), "size": (l, a), "position": (x, y)}. Tamanhos
    sao da area cliente; a posicao e a do canto da moldura, como em move().
    """
    ax, ay, aw, ah = (int(v) for v in available)
    cabe_l = max(aw - FRAME[0] - 2 * GAP, 1)
    cabe_a = max(ah - FRAME[1] - 2 * GAP, 1)
    minimo = (min(FLOOR[0], cabe_l), min(FLOOR[1], cabe_a))
    tamanho = (min(PREFERRED[0], cabe_l), min(PREFERRED[1], cabe_a))

    total_l = tamanho[0] + FRAME[0]
    total_a = tamanho[1] + FRAME[1]
    if center is None:
        center = (ax + aw / 2.0, ay + ah / 2.0)
    x = int(round(center[0] - total_l / 2.0))
    y = int(round(center[1] - total_a / 2.0))
    # Centralizar sobre o QGIS nao pode empurrar a janela para fora da tela.
    x = max(ax + GAP, min(x, ax + aw - total_l - GAP))
    y = max(ay + GAP, min(y, ay + ah - total_a - GAP))
    return {"minimum": minimo, "size": tamanho, "position": (x, y)}
