"""Ícones vetoriais desenhados em tempo de execução.

Um plugin de QGIS não pode carregar uma biblioteca de ícones nem depender de
qtsvg estar presente, e um pacote de PNGs teria de vir em três resoluções para
não borrar em tela de alta densidade. Então os ícones são traçados com QPainter
na resolução exata pedida, na cor pedida: nítidos em qualquer DPI, recoloríveis
conforme o estado do controle, e sem nenhum arquivo binário no repositório.

O traço é aberto e de espessura constante, no mesmo espírito das famílias
Feather e Lucide, e todos os glifos são desenhados numa grade de 24 por 24 e
escalados na hora.
"""

from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

GRID = 24.0


def _qt(group, value):
    """Enum do Qt que funciona no Qt5 e no Qt6.

    O Qt6 -- e portanto o QGIS 4 -- removeu o acesso solto: `Qt.RoundCap` deixa
    de existir e vira `Qt.PenCapStyle.RoundCap`. Buscar o grupo com recurso ao
    proprio Qt cobre os dois casos sem `if` de versao espalhado pelo arquivo.
    """
    return getattr(getattr(Qt, group, Qt), value)


def _pen(color, width=1.9):
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(_qt("PenCapStyle", "RoundCap"))
    pen.setJoinStyle(_qt("PenJoinStyle", "RoundJoin"))
    return pen


def _poly(painter, points, close=False):
    path = QPainterPath(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(QPointF(*point))
    if close:
        path.closeSubpath()
    painter.drawPath(path)


# -- glifos ----------------------------------------------------------------
# Cada função recebe o painter já escalado para a grade 24x24.

def _mountain(painter):
    """Relevo: o dado de entrada do plugin."""
    _poly(painter, [(2, 18), (8.5, 8), (12.5, 13.5), (15, 10), (22, 18)])
    _poly(painter, [(6.6, 10.6), (10.4, 10.6)])


def _layers(painter):
    """Saídas empilhadas."""
    _poly(painter, [(12, 3), (21, 8), (12, 13), (3, 8)], close=True)
    _poly(painter, [(3.4, 12), (12, 17), (20.6, 12)])
    _poly(painter, [(3.4, 16), (12, 21), (20.6, 16)])


def _sliders(painter):
    """Ajustes."""
    for y, knob in ((7.0, 15.0), (12.0, 9.0), (17.0, 17.0)):
        _poly(painter, [(3, y), (21, y)])
        painter.drawEllipse(QPointF(knob, y), 2.5, 2.5)


def _play(painter):
    """Executar."""
    painter.drawEllipse(QRectF(3, 3, 18, 18))
    _poly(painter, [(10, 8.4), (16.4, 12), (10, 15.6)], close=True)


def _grid_map(painter):
    """Superfície contínua: adequabilidade."""
    painter.drawRoundedRect(QRectF(3, 4.5, 18, 15), 2.4, 2.4)
    _poly(painter, [(9, 4.5), (9, 19.5)])
    _poly(painter, [(15, 4.5), (15, 19.5)])
    _poly(painter, [(3, 9.5), (21, 9.5)])
    _poly(painter, [(3, 14.5), (21, 14.5)])


def _alert(painter):
    """Risco."""
    _poly(painter, [(12, 3.4), (21.6, 19.4), (2.4, 19.4)], close=True)
    _poly(painter, [(12, 9.6), (12, 13.8)])
    painter.drawEllipse(QPointF(12, 16.6), 0.85, 0.85)


def _polygon(painter):
    """Zonas vetoriais."""
    _poly(painter, [(5, 8), (12, 4), (20, 9), (17, 18), (7, 17)], close=True)
    for x, y in ((5, 8), (12, 4), (20, 9), (17, 18), (7, 17)):
        painter.drawEllipse(QPointF(x, y), 1.05, 1.05)


def _boot(painter):
    """Transitabilidade.

    Uma escada, e nao uma bota nem uma pegada. As duas primeiras tentativas
    falharam no teste que importa -- olhar o glifo a 22 px sem legenda -- e a
    escada diz exatamente o que o mapa mostra: graus de inclinacao, do suave ao
    escarpado.
    """
    _poly(painter, [(2.5, 20), (7.5, 20), (7.5, 15.5), (12.5, 15.5),
                    (12.5, 11), (17.5, 11), (17.5, 6.5), (21.5, 6.5)])


def _drop(painter):
    """Curso d'água."""
    path = QPainterPath(QPointF(12, 3))
    path.cubicTo(QPointF(18.5, 10.5), QPointF(19.5, 13.5), QPointF(19, 15.5))
    path.cubicTo(QPointF(18, 19.6), QPointF(14.5, 21), QPointF(12, 21))
    path.cubicTo(QPointF(9.5, 21), QPointF(6, 19.6), QPointF(5, 15.5))
    path.cubicTo(QPointF(4.5, 13.5), QPointF(5.5, 10.5), QPointF(12, 3))
    painter.drawPath(path)


def _route(painter):
    """Rota entre pontos."""
    path = QPainterPath(QPointF(5.5, 18.5))
    path.cubicTo(QPointF(12, 18.5), QPointF(6, 12), QPointF(12, 12))
    path.cubicTo(QPointF(18, 12), QPointF(12, 5.5), QPointF(18.5, 5.5))
    painter.drawPath(path)
    painter.drawEllipse(QPointF(5.5, 18.5), 2.1, 2.1)
    painter.drawEllipse(QPointF(18.5, 5.5), 2.1, 2.1)


def _scale(painter):
    """Pesos dos critérios."""
    _poly(painter, [(12, 4), (12, 20)])
    _poly(painter, [(5, 7.5), (19, 7.5)])
    _poly(painter, [(5, 7.5), (2.5, 13.5), (7.5, 13.5)], close=True)
    _poly(painter, [(19, 7.5), (16.5, 13.5), (21.5, 13.5)], close=True)
    _poly(painter, [(8.5, 20), (15.5, 20)])


def _ruler(painter):
    """Limites do terreno."""
    painter.drawRoundedRect(QRectF(2.5, 8, 19, 8), 2.0, 2.0)
    for x in (6.5, 10.5, 14.5, 18.5):
        _poly(painter, [(x, 8), (x, 11.6)])


def _crop(painter):
    """Recorte das zonas."""
    _poly(painter, [(6, 2.5), (6, 18)])
    _poly(painter, [(2.5, 6), (18, 6)])
    _poly(painter, [(6, 6), (18, 6), (18, 18), (6, 18)], close=True)
    _poly(painter, [(18, 6), (21.5, 6)])
    _poly(painter, [(18, 18), (18, 21.5)])


def _plus_layer(painter):
    """Critério adicional."""
    painter.drawRoundedRect(QRectF(2.5, 5, 13, 13), 2.2, 2.2)
    _poly(painter, [(18, 13), (18, 21)])
    _poly(painter, [(14, 17), (22, 17)])


def _shield(painter):
    """Restrições."""
    _poly(painter, [(12, 2.8), (20, 6), (20, 12), (12, 21), (4, 12), (4, 6)],
          close=True)


def _save(painter):
    """Arquivo de saída."""
    _poly(painter, [(4, 3.5), (17, 3.5), (20.5, 7), (20.5, 20.5), (4, 20.5)],
          close=True)
    _poly(painter, [(8, 3.5), (8, 9.5), (16, 9.5), (16, 3.5)])
    painter.drawRoundedRect(QRectF(8, 13.5, 8, 7), 1.2, 1.2)


def _check(painter):
    """Resumo."""
    painter.drawEllipse(QRectF(3, 3, 18, 18))
    _poly(painter, [(8, 12.2), (11, 15.2), (16.4, 9)])


def _pulse(painter):
    """Andamento."""
    _poly(painter, [(2.5, 12), (7.5, 12), (10, 6.5), (14, 17.5), (16.5, 12), (21.5, 12)])


GLYPHS = {
    "mountain": _mountain, "layers": _layers, "sliders": _sliders, "play": _play,
    "grid": _grid_map, "alert": _alert, "polygon": _polygon, "boot": _boot,
    "drop": _drop, "route": _route, "scale": _scale, "ruler": _ruler,
    "crop": _crop, "plus-layer": _plus_layer, "shield": _shield, "save": _save,
    "check": _check, "pulse": _pulse,
}


def pixmap(name, size=22, color="#1a2420", width=1.9, ratio=1):
    """Devolve o glifo como QPixmap, já pronto para telas de alta densidade."""
    glyph = GLYPHS.get(name)
    device = int(size * ratio)
    image = QPixmap(device, device)
    image.fill(QColor(0, 0, 0, 0))
    if glyph is None:
        return image
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.scale(device / GRID, device / GRID)
    painter.setPen(_pen(color, width))
    painter.setBrush(_qt("BrushStyle", "NoBrush"))
    glyph(painter)
    painter.end()
    image.setDevicePixelRatio(ratio)
    return image
