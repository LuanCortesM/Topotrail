"""Roda a janela do plugin sobre PyQt6, sem QGIS, e relata problemas.

Executado como processo separado por tests/test_qt6_runtime.py: PyQt5 e PyQt6
nao convivem no mesmo interpretador, e o resto da suite usa o QGIS, que hoje e
Qt5.

O que isto cobre: o QGIS 4 roda sobre Qt6, e o que muda para este plugin e o
Qt -- enums escopados, QAction mudando de modulo, sub-controles de folha de
estilo, QPainter.RenderHint. A camada `qgis.PyQt` existe para abstrair isso,
entao aponta-la para o PyQt6 exercita exatamente o codigo que quebraria.

O que isto NAO cobre: mudancas na API do proprio QGIS entre a 3 e a 4. Continua
sendo necessario um teste de fumaca num QGIS 4 real antes de anunciar suporte.
"""

import os
import sys
import types


def instalar_shim():
    import PyQt6.QtCore, PyQt6.QtGui, PyQt6.QtWidgets  # noqa: F401
    import PyQt6

    qgis = types.ModuleType("qgis")
    pyqt = types.ModuleType("qgis.PyQt")
    pyqt.__path__ = []
    qgis.PyQt = pyqt
    sys.modules["qgis"] = qgis
    sys.modules["qgis.PyQt"] = pyqt
    for nome in ("QtCore", "QtGui", "QtWidgets"):
        modulo = getattr(PyQt6, nome)
        setattr(pyqt, nome, modulo)
        sys.modules[f"qgis.PyQt.{nome}"] = modulo

    class Crs:
        def isValid(self): return True
        def authid(self): return "EPSG:32723"

    class Base:
        def __init__(self, *a, **k): pass
        def isValid(self): return True
        def crs(self): return Crs()
        def extent(self): return None
        def featureCount(self): return 1

    class Settings:
        _dados = {}
        def value(self, chave, padrao=None, type=None): return self._dados.get(chave, padrao)
        def setValue(self, chave, valor): self._dados[chave] = valor

    class Project:
        @classmethod
        def instance(cls): return cls
        @classmethod
        def crs(cls): return Crs()
        @classmethod
        def addMapLayer(cls, layer): return layer

    core = types.ModuleType("qgis.core")
    for nome in ("QgsProcessingFeedback", "QgsProcessingContext", "QgsRasterLayer",
                 "QgsVectorLayer", "QgsApplication", "QgsCoordinateReferenceSystem",
                 "QgsCoordinateTransform", "QgsColorRampShader", "QgsFillSymbol",
                 "QgsLineSymbol", "QgsMarkerSymbol", "QgsRasterShader", "QgsRasterTransparency",
                 "QgsSingleBandPseudoColorRenderer"):
        setattr(core, nome, type(nome, (Base,), {}))
    core.QgsSettings = Settings
    core.QgsProject = Project
    sys.modules["qgis.core"] = core
    qgis.core = core

    gui = types.ModuleType("qgis.gui")
    for nome in ("QgsMapToolEmitPoint", "QgsProjectionSelectionDialog",
                 "QgsProjectionSelectionWidget"):
        setattr(gui, nome, type(nome, (Base,), {}))
    sys.modules["qgis.gui"] = gui
    qgis.gui = gui

    processing = types.ModuleType("qgis.processing")
    processing.run = lambda *a, **k: {}
    sys.modules["qgis.processing"] = processing


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    instalar_shim()
    sys.path.insert(0, raiz)

    from PyQt6.QtCore import Qt, QT_VERSION_STR
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

    problemas = []
    app = QApplication([])
    from ui.topotrail_dialog import TopotrailDialog
    from ui import icons

    dialog = TopotrailDialog()
    dialog.resize(940, 720)          # o tamanho minimo declarado da janela
    dialog.show()
    app.processEvents()

    for code in ("pt", "en", "es", "fr", "zh", "ja"):
        indice = dialog.language_box.findData(code)
        if indice < 0:
            problemas.append(f"idioma {code} nao esta no seletor")
            continue
        dialog.language_box.setCurrentIndex(indice)
        dialog.want_route.setChecked(True)
        app.processEvents()
        if dialog.t("s1_title") == "s1_title":
            problemas.append(f"{code}: texto nao resolveu")
        for passo in range(4):
            dialog.stack.setCurrentIndex(passo)
            app.processEvents()
            for widget in dialog.findChildren(QLabel) + dialog.findChildren(QPushButton):
                texto = widget.text()
                if not texto or not widget.isVisible():
                    continue
                if isinstance(widget, QLabel) and widget.wordWrap():
                    continue
                if widget.width() < widget.sizeHint().width() - 1:
                    problemas.append(
                        f"{code} passo {passo+1}: '{texto[:26]}' cortado")
            from PyQt6.QtWidgets import QComboBox as _Combo
            for caixa in dialog.findChildren(_Combo):
                if not caixa.isVisible() or caixa.count() == 0:
                    continue
                if caixa.width() < caixa.sizeHint().width() - 1:
                    problemas.append(
                        f"{code} passo {passo+1}: opcao '{caixa.currentText()[:26]}' cortada")

    # Depois de passar por todos os idiomas e terminar em japones, nada pode
    # ter ficado em portugues: cada texto escrito uma vez na construcao, e nao
    # vinculado, e uma frase que sobrevive a troca de idioma.
    import json
    from PyQt6.QtWidgets import QCheckBox, QComboBox
    def _frases(code):
        with open(os.path.join(raiz, "i18n", f"{code}.json"), encoding="utf-8") as f:
            dados = json.load(f)
        frases = set()
        for valor in dados.values():
            if isinstance(valor, str) and len(valor) > 3:
                frases.add(valor)
            elif isinstance(valor, list):
                frases.update(valor)
        return frases
    em_ja = _frases("ja")
    em_outros = set()
    for code in ("pt", "en", "es", "fr", "zh"):
        em_outros |= _frases(code)
    em_outros -= em_ja
    dialog.language_box.setCurrentIndex(dialog.language_box.findData("ja"))
    app.processEvents()
    for widget in dialog.findChildren((QLabel, QPushButton, QCheckBox)):
        for texto in (widget.text(), widget.toolTip()):
            if texto in em_outros:
                problemas.append(f"ficou noutro idioma apos trocar para ja: '{texto[:40]}'")
    for caixa in dialog.findChildren(QComboBox):
        for i in range(caixa.count()):
            if caixa.itemText(i) in em_outros:
                problemas.append(f"opcao ficou noutro idioma: '{caixa.itemText(i)}'")

    for modo in ("light", "dark", "auto"):
        dialog.theme_mode = modo
        dialog._apply_theme()
        dialog._repaint_icons()
        app.processEvents()

    antes = dialog.want_streams.isChecked()
    evento = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Space.value,
                       Qt.KeyboardModifier.NoModifier)
    dialog.want_streams.keyPressEvent(evento)
    if dialog.want_streams.isChecked() == antes:
        problemas.append("cartao nao respondeu a barra de espaco")

    dialog.vertical_unit.setCurrentIndex(1)
    if not dialog.vertical_unit.currentText():
        problemas.append("controle segmentado vazio")

    for nome in icons.GLYPHS:
        for tamanho in (18, 24, 44):
            if icons.pixmap(nome, tamanho, "#0d452c").isNull():
                problemas.append(f"glifo {nome} nao desenhou em {tamanho} px")

    print(f"QT={QT_VERSION_STR}")
    for problema in problemas:
        print(f"PROBLEMA: {problema}")
    print(f"TOTAL={len(problemas)}")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
