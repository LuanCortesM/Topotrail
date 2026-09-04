"""Assistente do TopoTrail: quatro passos, com o minimo obrigatorio em cada um.

A janela anterior mostrava treze campos numericos de uma vez, exigia quatro
rasters quando o motor deriva tres deles sozinho desde a versao 0.6, e nao dava
acesso a nada que foi acrescentado depois -- nem drenagem, nem transitabilidade,
nem tempo de caminhada de Tobler, nem destinos intermediarios. Dezesseis
parametros do algoritmo eram inalcancaveis pela interface.

O assistente inverte o padrao: o caminho normal pede so o MDE, e cada opcao
adicional so aparece quando o usuario diz que quer aquilo. Todo controle tem uma
frase explicando o que ele muda no resultado -- essa e a diferenca entre uma
ferramenta que so quem escreveu sabe usar e uma que um pesquisador de campo
abre e entende.
"""

import os
import traceback

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont, QFontMetrics, QPixmap
from qgis.PyQt.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)
from qgis.core import (
    QgsApplication, QgsProcessingContext, QgsProcessingFeedback,
    QgsProject, QgsRasterLayer, QgsVectorLayer,
)
import qgis.processing as processing

from . import icons
from . import i18n
from .support import (
    class_enum,
    TopotrailSupportMixin, append_gui_diagnostic_log, qt_enum,
    serialize_processing_params, size_policy,
)

PLUGIN_DIR = os.path.dirname(os.path.dirname(__file__))


def _plugin_version():
    """A versão declarada em metadata.txt.

    Lida do arquivo, e não por `from ..processing.algorithm import`: o import
    relativo só resolve quando o módulo é carregado como parte do pacote do
    plugin, e falhava em silêncio -- deixando a versão em branco na tela -- em
    qualquer outro contexto, inclusive nos testes.
    """
    try:
        with open(os.path.join(PLUGIN_DIR, "metadata.txt"), encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("version="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return "?"

# --------------------------------------------------------------------------
# Textos
# --------------------------------------------------------------------------
# Ficavam num dicionario aqui dentro, com dois idiomas. Agora vivem em
# i18n/<codigo>.json, um arquivo por lingua -- ver ui/i18n.py para o porque.

# --------------------------------------------------------------------------
# Pequenos construtores, para que cada controle saia com a mesma aparencia
# --------------------------------------------------------------------------

# Paleta tirada da logo do plugin: o verde-floresta #0d452c e a cor dominante
# dela. Uma ferramenta de campo em unidade de conservacao nao tem por que usar
# o azul generico de painel de controle.
#
# Os tons claro e escuro existem os dois porque o QGIS tem tema proprio e o
# usuario escolhe qual usar. Fixar a janela em escuro -- ou em claro -- garante
# que ela vai destoar da metade dos QGIS instalados, e no caso do escuro ainda
# apagaria as logos institucionais, que tem fundo branco. Entao a paleta e
# escolhida a partir do tema em vigor, e nao decidida aqui.

LIGHT = {
    "ink": "#1a2420", "muted": "#6b7a74", "forest": "#0d452c",
    "accent": "#17805a", "accent_hover": "#146f4e", "accent_soft": "#e8f3ee",
    "accent_tint": "#eef7f2", "canvas": "#f4f6f5", "surface": "#ffffff",
    "surface_alt": "#fbfcfb", "line": "#e2e8e5", "line_strong": "#c7d4cc",
    "gold": "#c98f22", "plate": "#ffffff", "disabled": "#7f8d87",
}

DARK = {
    "ink": "#e8efea", "muted": "#93a79e", "forest": "#0b2c20",
    "accent": "#3fae82", "accent_hover": "#4fc294", "accent_soft": "#16342a",
    "accent_tint": "#14342a", "canvas": "#141a17", "surface": "#1b231f",
    "surface_alt": "#182019", "line": "#2b3833", "line_strong": "#3b4b44",
    "gold": "#e4aa3b", "plate": "#ffffff", "disabled": "#68786f",
}

# Preenchido em tempo de execucao por _adopt_theme(); os nomes em maiuscula
# continuam existindo porque sao usados na construcao dos widgets.
T = dict(LIGHT)
INK = T["ink"]
MUTED = T["muted"]
FOREST = T["forest"]
ACCENT = T["accent"]
ACCENT_SOFT = T["accent_soft"]
CANVAS = T["canvas"]
LINE = T["line"]


def _is_dark_theme():
    """O QGIS esta em tema escuro?

    Lido da paleta em vigor do Qt, que e o que o proprio QGIS ajusta quando o
    usuario troca de tema, em vez de uma configuracao propria do plugin -- assim
    a janela acompanha o resto do programa sem ninguem precisar configurar nada.
    """
    try:
        from qgis.PyQt.QtWidgets import QApplication
        from qgis.PyQt.QtGui import QPalette
        application = QApplication.instance()
        if application is None:
            return False
        window = application.palette().color(class_enum(QPalette, "ColorRole", "Window"))
        return window.lightness() < 128
    except Exception:
        return False


def _adopt_theme():
    global T, INK, MUTED, FOREST, ACCENT, ACCENT_SOFT, CANVAS, LINE
    T = dict(DARK if _is_dark_theme() else LIGHT)
    INK, MUTED, FOREST = T["ink"], T["muted"], T["forest"]
    ACCENT, ACCENT_SOFT = T["accent"], T["accent_soft"]
    CANVAS, LINE = T["canvas"], T["line"]
    return T


def _help(text):
    """A frase que explica o controle. E o que torna a janela didatica, entao
    nao e opcional em nenhum campo que nao seja obvio."""
    label = QLabel(text)
    label.setObjectName("ttHelp")
    label.setWordWrap(True)
    label.setSizePolicy(size_policy("Preferred"), size_policy("Minimum"))
    return label


def _heading(text, size=15, bold=True):
    label = QLabel(text)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() + (size - 10) * 0.5)
    font.setBold(bold)
    label.setFont(font)
    label.setWordWrap(True)
    return label


def _icon(name, size=22, color=INK, width=1.9):
    label = QLabel()
    label.setPixmap(icons.pixmap(name, size, color, width))
    label.setFixedSize(size, size)
    return label


class OptionCard(QFrame):
    """Uma saída do plugin, apresentada como cartão e não como caixa numa lista.

    A diferença não é decorativa. Numa lista de caixas de marcação com um
    parágrafo embaixo de cada uma, tudo tem o mesmo peso e a tela vira um muro
    de texto -- foi o que a primeira versão do assistente produziu. Como cartão,
    cada saída ganha ícone, título e descrição em três níveis tipográficos
    distintos, a área clicável é o cartão inteiro, e o estado selecionado é
    visível de longe pela borda e pelo fundo.
    """

    def __init__(self, glyph, enabled=True, parent=None):
        super().__init__(parent)
        self.setObjectName("ttOption")
        self.glyph = glyph
        self._enabled = enabled
        self.setProperty("checked", "false")
        self.setProperty("locked", "false" if enabled else "true")
        if enabled:
            self.setCursor(qt_enum("CursorShape", "PointingHandCursor"))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 13, 15, 13)
        layout.setSpacing(13)

        self.icon_label = _icon(glyph, 24, MUTED, 1.85)
        layout.addWidget(self.icon_label, 0, qt_enum("AlignmentFlag", "AlignTop"))

        column = QVBoxLayout()
        column.setSpacing(3)
        self.title = QLabel()
        self.title.setObjectName("ttOptionTitle")
        self.title.setWordWrap(True)
        self.description = QLabel()
        self.description.setObjectName("ttHelp")
        self.description.setWordWrap(True)
        column.addWidget(self.title)
        column.addWidget(self.description)
        layout.addLayout(column, 1)

        self.tick = QLabel()
        self.tick.setObjectName("ttTick")
        self.tick.setAlignment(qt_enum("AlignmentFlag", "AlignRight"))
        # No alto, e nao ao centro: num cartao expandido (rota) o centro e o
        # meio do formulario, e a marca ficava boiando longe do titulo.
        layout.addWidget(self.tick, 0, qt_enum("AlignmentFlag", "AlignTop"))
        self.tick.setContentsMargins(0, 2, 0, 0)
        self.setFocusPolicy(qt_enum("FocusPolicy", "StrongFocus"))

        self.body = QWidget()
        self.body.setVisible(False)
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 10, 0, 0)
        body_layout.setSpacing(7)
        column.addWidget(self.body)
        self.body_layout = body_layout

        self._checked = False
        self._callbacks = []

    # -- estado -------------------------------------------------------------
    def isChecked(self):
        return self._checked

    def setChecked(self, value):
        value = bool(value)
        if value == self._checked:
            return
        self._checked = value
        self.setProperty("checked", "true" if value else "false")
        self.icon_label.setPixmap(icons.pixmap(
            self.glyph, 22, ACCENT if value else MUTED, 1.85))
        self.tick.setPixmap(icons.pixmap("check", 20, ACCENT, 1.9)
                            if value else QPixmap())
        self.style().unpolish(self); self.style().polish(self)
        for callback in self._callbacks:
            callback(value)

    def toggled(self, callback):
        self._callbacks.append(callback)

    def lock_checked(self, badge_text=""):
        """Saída obrigatória: sempre gerada, e dito com palavra.

        A versão anterior usava uma caixa de marcação marcada e desabilitada, e
        o resultado era uma caixa apagada que se lê como *desligada* -- foi
        exatamente assim que passou despercebido que essas saídas estavam
        ativas. Um selo escrito "Incluído" não depende de cor nem de convenção.
        """
        self._checked = True
        self._enabled = False
        self.setProperty("checked", "false")
        self.setProperty("locked", "true")
        self.setFocusPolicy(qt_enum("FocusPolicy", "NoFocus"))
        # Icone na cor de destaque, e nao apagado: o cartao e um produto que
        # SERA gerado. Apagar o icone e o titulo dizia o contrario.
        self.icon_label.setPixmap(icons.pixmap(self.glyph, 22, ACCENT, 1.85))
        self.tick.setPixmap(QPixmap())
        self.tick.setObjectName("ttIncludedPill")
        self.tick.setText(badge_text)
        self.tick.setAlignment(qt_enum("AlignmentFlag", "AlignCenter"))

    def refresh_theme(self):
        colour = ACCENT if (self._locked() or self._checked) else MUTED
        self.icon_label.setPixmap(icons.pixmap(self.glyph, 22, colour, 1.85))
        if self._checked and not self._locked():
            self.tick.setPixmap(icons.pixmap("check", 20, ACCENT, 1.9))

    def _locked(self):
        return self.property("locked") == "true"

    def mousePressEvent(self, event):
        if self._enabled:
            self.setChecked(not self._checked)

    def keyPressEvent(self, event):
        """Espaço e Enter alternam o cartão.

        Sem isto o cartão só existe para quem usa o mouse -- a versão anterior
        trocou caixas de marcação, que o Qt já tornava acessíveis por teclado,
        por um QFrame que não respondia a tecla nenhuma.
        """
        if self._enabled and event.key() in (qt_enum("Key", "Key_Space"), qt_enum("Key", "Key_Return"),
                                             qt_enum("Key", "Key_Enter")):
            self.setChecked(not self._checked)
            return
        super().keyPressEvent(event)


def _card(title=None, glyph=None, badge=None):
    """Um bloco visual. Agrupar reduz a impressao de painel de controle."""
    frame = QFrame()
    frame.setObjectName("ttCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(9)
    if title or glyph:
        head = QHBoxLayout()
        head.setSpacing(10)
        if glyph:
            head.addWidget(_icon(glyph, 19, ACCENT, 1.9))
        label = QLabel(title or "")
        label.setObjectName("ttCardTitle")
        head.addWidget(label, 1)
        if badge:
            chip = QLabel()
            chip.setObjectName("ttBadgeChip")
            chip.setProperty("kind", badge)
            head.addWidget(chip, 0)
            frame._badge = chip
        holder = QWidget()
        holder.setLayout(head)
        head.setContentsMargins(0, 0, 0, 2)
        layout.addWidget(holder)
        frame._title_label = label
    return frame, layout


def _divider():
    line = QFrame()
    line.setObjectName("ttDivider")
    line.setFixedHeight(1)
    return line


def _spin(minimum, maximum, value, decimals=2, step=1.0, suffix=""):
    box = QDoubleSpinBox()
    box.setDecimals(decimals)
    box.setRange(minimum, maximum)
    box.setSingleStep(step)
    box.setValue(value)
    if suffix:
        box.setSuffix(suffix)
    box.setMinimumWidth(110)
    return box


class _FileRow(QWidget):
    """Campo de arquivo com botao. Usado para raster e para pontos."""

    def __init__(self, file_filter, dialog_title, parent=None):
        super().__init__(parent)
        self._filter = file_filter
        self._title = dialog_title
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.edit = QLineEdit()
        self.button = QPushButton("…")
        self.button.setObjectName("ttBrowse")
        self.button.setFixedWidth(52)
        self.button.setCursor(qt_enum("CursorShape", "PointingHandCursor"))
        self.button.clicked.connect(self._browse)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.button, 0)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, self._title, "", self._filter)
        if path:
            self.edit.setText(path)

    def text(self):
        return self.edit.text().strip()

    def setText(self, value):
        self.edit.setText(value)


class _Segmented(QWidget):
    """Escolha entre poucas opções, todas visíveis.

    Uma caixa de seleção para "metros ou pés" esconde metade da resposta atrás
    de um clique e não deixa claro que só existem duas opções. Com o controle
    segmentado as duas ficam à vista e a escolha é um clique, não dois.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ttSegment")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)
        self._buttons = []
        self._index = 0

    def addItems(self, labels):
        for button in self._buttons:
            button.setParent(None)
            button.deleteLater()
        self._buttons = []
        for position, text in enumerate(labels):
            button = QPushButton(text)
            button.setObjectName("ttSegmentButton")
            button.setCheckable(True)
            # A largura e reservada para o texto em semibold, que e o peso do
            # estado marcado: dimensionar pelo peso normal fazia o rotulo do
            # segmento ativo ser cortado no proprio botao.
            bold = button.font()
            bold.setBold(True)
            button.setMinimumWidth(
                QFontMetrics(bold).horizontalAdvance(text) + 40)
            button.setCursor(qt_enum("CursorShape", "PointingHandCursor"))
            button.clicked.connect(
                lambda _checked, index=position: self.setCurrentIndex(index))
            self.layout().addWidget(button)
            self._buttons.append(button)
        self.setCurrentIndex(min(self._index, len(labels) - 1))

    def clear(self):
        pass

    def currentIndex(self):
        return self._index

    def currentText(self):
        return self._buttons[self._index].text() if self._buttons else ""

    def setCurrentIndex(self, index):
        if not self._buttons:
            self._index = max(index, 0)
            return
        self._index = max(0, min(index, len(self._buttons) - 1))
        for position, button in enumerate(self._buttons):
            button.setChecked(position == self._index)


class _RasterChip(QWidget):
    """Campo de arquivo que, escolhido o raster, mostra o que foi lido dele.

    Um campo de texto vazio nao diz se o arquivo abriu, qual a resolucao, nem se
    o CRS esta definido -- e o usuario so descobre que escolheu o arquivo errado
    depois de rodar a analise inteira. Aqui o GDAL le o cabecalho na hora e a
    ficha responde antes: nome, formato, tamanho da celula e sistema de
    coordenadas, ou uma mensagem clara de que o arquivo nao serve.
    """

    def __init__(self, dialog, parent=None):
        super().__init__(parent)
        self.dialog = dialog
        self._path = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.empty = QWidget()
        empty_layout = QHBoxLayout(self.empty)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.setSpacing(7)
        self.edit = QLineEdit()
        self.edit.editingFinished.connect(lambda: self.set_path(self.edit.text()))
        self.browse = QPushButton("…")
        self.browse.setObjectName("ttBrowse")
        self.browse.setFixedWidth(52)
        self.browse.setCursor(qt_enum("CursorShape", "PointingHandCursor"))
        self.browse.clicked.connect(self._pick)
        empty_layout.addWidget(self.edit, 1)
        empty_layout.addWidget(self.browse, 0)
        layout.addWidget(self.empty)

        self.filled = QFrame()
        self.filled.setObjectName("ttChip")
        self.filled.setVisible(False)
        chip = QHBoxLayout(self.filled)
        chip.setContentsMargins(13, 11, 12, 11)
        chip.setSpacing(12)
        self.chip_icon = _icon("mountain", 21, ACCENT, 1.85)
        chip.addWidget(self.chip_icon, 0, qt_enum("AlignmentFlag", "AlignVCenter"))
        column = QVBoxLayout()
        column.setSpacing(2)
        self.name = QLabel()
        self.name.setObjectName("ttChipName")
        self.detail = QLabel()
        self.detail.setObjectName("ttChipDetail")
        column.addWidget(self.name)
        column.addWidget(self.detail)
        chip.addLayout(column, 1)
        self.change = QPushButton(dialog.t("change"))
        self.change.setCursor(qt_enum("CursorShape", "PointingHandCursor"))
        self.change.clicked.connect(self._pick)
        dialog._labels.append((self.change, "change", "setText"))
        chip.addWidget(self.change, 0)
        layout.addWidget(self.filled)

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.dialog.t("dem"), "",
            "GeoTIFF (*.tif *.tiff);;Todos (*)")
        if path:
            self.set_path(path)

    def text(self):
        return self._path

    def setText(self, value):
        self.set_path(value)

    def set_path(self, path):
        path = (path or "").strip()
        self._path = path
        if not path:
            self.empty.setVisible(True)
            self.filled.setVisible(False)
            self.edit.setText("")
            return
        self.empty.setVisible(False)
        self.filled.setVisible(True)
        self.name.setText(os.path.basename(path))
        self.detail.setText(self._describe(path))
        self.setToolTip(path)
        if hasattr(self.dialog, "footer_note"):
            self.dialog._refresh_context()

    def _describe(self, path):
        """Le o cabecalho do raster. Nunca levanta: um arquivo ilegivel aqui e
        informacao para o usuario, nao motivo para derrubar a janela."""
        try:
            from osgeo import gdal
            gdal.UseExceptions()
            dataset = gdal.Open(path)
            if dataset is None:
                return self.dialog.t("chip_unreadable")
            driver = dataset.GetDriver().ShortName
            transform = dataset.GetGeoTransform()
            size = abs(transform[1]) if transform else 0.0
            parts = [driver]
            if size:
                parts.append(f"{size:.6g} {self.dialog.t('chip_unit')}"
                             if size < 1 else f"{size:.0f} m")
            projection = dataset.GetProjection()
            if projection:
                from osgeo import osr
                reference = osr.SpatialReference(wkt=projection)
                code = reference.GetAuthorityCode(None)
                parts.append(f"EPSG:{code}" if code else self.dialog.t("chip_crs_ok"))
            else:
                parts.append(self.dialog.t("chip_no_crs"))
            parts.append(f"{dataset.RasterXSize} × {dataset.RasterYSize} px")
            return " · ".join(parts)
        except Exception:
            return self.dialog.t("chip_unreadable")


class _Section(QWidget):
    """Bloco que so aparece quando a caixa correspondente e marcada.

    E o mecanismo central da janela: nada de rota na tela enquanto o usuario nao
    disser que quer rota. Sem isso voltamos aos treze campos simultaneos.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(22, 4, 0, 8)
        self.layout_.setSpacing(6)

    def add(self, widget):
        self.layout_.addWidget(widget)
        return widget

    def add_form(self, rows):
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        holder = QWidget()
        holder._labels = []
        for index, (label, widget) in enumerate(rows):
            text = QLabel(label)
            text.setWordWrap(True)
            grid.addWidget(text, index, 0)
            grid.addWidget(widget, index, 1)
            holder._labels.append(text)
        grid.setColumnStretch(0, 1)
        holder.setLayout(grid)
        self.layout_.addWidget(holder)
        return holder


class TopotrailDialog(QDialog, TopotrailSupportMixin):
    """Assistente de quatro passos."""

    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        _adopt_theme()
        self.theme_mode = "auto"
        self.lang = self._remembered_language() or i18n.detect()
        self._option_cards = []
        self._static_icons = []
        self._temp_point_files = []
        self._task = None
        self._feedback = None
        self._labels = []          # (widget, chave) para troca de idioma
        self._format_initialised = False
        self.setMinimumSize(940, 720)
        self._build()
        self._retranslate()
        self._apply_theme()

    # -- infraestrutura de idioma ------------------------------------------
    def t(self, key):
        return i18n.text(self.lang, key)

    def _bind(self, widget, key, attribute="setText"):
        self._labels.append((widget, key, attribute))
        return widget

    def _label(self, key):
        return self._bind(QLabel(), key)

    def _help_label(self, key):
        return self._bind(_help(""), key)

    def _check(self, key):
        return self._bind(QCheckBox(), key)

    def _retranslate(self):
        self.setWindowTitle(self.t("window"))
        self.version_label.setText(f"v{_plugin_version()}")
        for widget, key, attribute in self._labels:
            text = self.t(key)
            if key == "eyebrow":
                text = text.format(n=getattr(widget, "_step_number", 1))
            getattr(widget, attribute)(text)
        self.theme_button.setText(self.t(f"theme_{self.theme_mode}"))
        if self.lang not in i18n.REVIEWED:
            self.language_box.setToolTip(self.t("translation_draft"))
        else:
            self.language_box.setToolTip("")
        nomes = self.t("steps")
        if isinstance(nomes, list):
            for index, name in enumerate(nomes[:len(self.step_labels)]):
                self.step_labels[index].setText(name)
                # Sem recalcular, a pílula mantém a largura do idioma anterior e
                # corta o rótulo novo -- "データ" virava "デー".
                # A largura e reservada para o texto em semibold, que e o peso
                # do passo ativo: dimensionar pelo peso normal cortava sempre a
                # etapa em que a pessoa esta -- "Produtos" virava "Produto".
                negrito = QFont(self.step_labels[index].font())
                negrito.setBold(True)
                self.step_labels[index].setMinimumWidth(
                    QFontMetrics(negrito).horizontalAdvance(name) + 2)
                self.step_labels[index].adjustSize()
                self._step_rows[index][0].adjustSize()
        self.back_button.setText(self.t("back"))
        self._update_nav()
        self._fill_enums()

    def _language_chosen(self, index):
        code = self.language_box.itemData(index)
        if code and code != self.lang:
            self.lang = code
            self._retranslate()
            self._remember_language(code)

    def _remember_language(self, code):
        """Guarda a escolha nas configuracoes do QGIS.

        Sem isto, quem trocou para espanhol reabre o plugin em ingles toda vez,
        porque a deteccao automatica volta a ler o idioma do QGIS -- que pode
        nao ser o idioma em que a pessoa quer trabalhar.
        """
        try:
            from qgis.core import QgsSettings
            QgsSettings().setValue("TopoTrail/language", code)
        except Exception:
            pass

    @staticmethod
    def _remembered_language():
        try:
            from qgis.core import QgsSettings
            code = QgsSettings().value("TopoTrail/language", "")
            if code in i18n.LANGUAGE_CODES:
                return code
        except Exception:
            pass
        return None

    # -- construcao ---------------------------------------------------------
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())

        self.stack = QStackedWidget()
        for builder in (self._step_data, self._step_outputs,
                        self._step_tuning, self._step_run):
            page = QWidget()
            page.setObjectName("ttPage")
            layout = QVBoxLayout(page)
            layout.setContentsMargins(34, 26, 34, 22)
            layout.setSpacing(14)
            builder(layout)
            layout.addStretch(1)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(class_enum(QFrame, "Shape", "NoFrame"))
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
        self.stack.currentChanged.connect(lambda _index: self._update_nav())
        outer.addWidget(self.stack, 1)
        outer.addWidget(self._build_footer())
        outer.addWidget(self._build_credits())

    def _build_header(self):
        """Marca, etapas e ações da janela, em três linhas finas no topo.

        A barra lateral saiu: numa janela de plugin, 270 px fixos a esquerda sao
        um quarto da largura util gastos em navegacao que cabe numa faixa. O
        credito institucional, que morava la, ganhou faixa propria no rodape --
        continua permanente, que era o requisito.
        """
        header = QFrame()
        header.setObjectName("ttHeader")
        column = QVBoxLayout(header)
        column.setContentsMargins(24, 16, 24, 0)
        column.setSpacing(12)

        brand = QHBoxLayout()
        brand.setSpacing(12)
        logo_path = os.path.join(PLUGIN_DIR, "logo.png")
        if os.path.exists(logo_path):
            plate = QLabel()
            plate.setObjectName("ttMark")
            plate.setFixedSize(42, 42)
            plate.setAlignment(qt_enum("AlignmentFlag", "AlignCenter"))
            plate.setPixmap(QPixmap(logo_path).scaled(
                32, 32, qt_enum("AspectRatioMode", "KeepAspectRatio"),
                qt_enum("TransformationMode", "SmoothTransformation")))
            brand.addWidget(plate)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        name = QLabel("TOPOTRAIL")
        name.setObjectName("ttBrand")
        self.tagline = QLabel()
        self.tagline.setObjectName("ttTagline")
        self._bind(self.tagline, "tagline")
        titles.addWidget(name)
        titles.addWidget(self.tagline)
        brand.addLayout(titles)
        brand.addStretch(1)

        self.theme_button = QPushButton()
        self.theme_button.setObjectName("ttHeaderAction")
        self.theme_button.setCursor(qt_enum("CursorShape", "PointingHandCursor"))
        self.theme_button.clicked.connect(self._cycle_theme)
        self._bind(self.theme_button, "theme_auto")
        brand.addWidget(self.theme_button)
        # Seletor, e nao um botao que alterna: com seis idiomas, alternar
        # obrigaria a passar por cinco para chegar ao sexto. Cada lingua aparece
        # escrita nela mesma, porque quem precisa do japones normalmente nao le
        # a palavra "japones".
        self.language_box = QComboBox()
        self.language_box.setObjectName("ttHeaderSelect")
        self.language_box.setCursor(qt_enum("CursorShape", "PointingHandCursor"))
        for code, name in i18n.available():
            self.language_box.addItem(name, code)
        index = self.language_box.findData(self.lang)
        if index >= 0:
            self.language_box.setCurrentIndex(index)
        self.language_box.currentIndexChanged.connect(self._language_chosen)
        brand.addWidget(self.language_box)
        column.addLayout(brand)

        steps = QHBoxLayout()
        steps.setSpacing(8)
        self.step_labels = []
        self._step_rows = []
        for index in range(4):
            pill = QFrame()
            pill.setObjectName("ttPill")
            pill.setProperty("active", "false")
            pill.setCursor(qt_enum("CursorShape", "PointingHandCursor"))
            pill.mousePressEvent = lambda event, target=index: self._jump_to(target)
            inner = QHBoxLayout(pill)
            inner.setContentsMargins(13, 8, 16, 8)
            inner.setSpacing(10)
            badge = QLabel(str(index + 1))
            badge.setObjectName("ttBadge")
            badge.setFixedSize(24, 24)
            badge.setAlignment(qt_enum("AlignmentFlag", "AlignCenter"))
            label = QLabel()
            label.setObjectName("ttStepText")
            inner.addWidget(badge)
            inner.addWidget(label)
            self.step_labels.append(label)
            self._step_rows.append((pill, badge))
            steps.addWidget(pill)
        steps.addStretch(1)
        # "Sobre" e a versao moram na mesma linha das etapas, a direita: numa
        # linha propria eram 30 px de faixa quase vazia entre o cabecalho e o
        # conteudo, e a janela e menor do que parece num plugin.
        self.about_button = QPushButton()
        self.about_button.setObjectName("ttQuiet")
        self.about_button.setCursor(qt_enum("CursorShape", "PointingHandCursor"))
        self.about_button.clicked.connect(self._show_about)
        self._bind(self.about_button, "about")
        steps.addWidget(self.about_button, 0, qt_enum("AlignmentFlag", "AlignVCenter"))
        self.version_label = QLabel()
        self.version_label.setObjectName("ttQuietText")
        steps.addWidget(self.version_label, 0, qt_enum("AlignmentFlag", "AlignVCenter"))
        column.addLayout(steps)
        column.addSpacing(12)
        return header

    def _build_credits(self):
        """Faixa de crédito institucional, fixa na base.

        Numa placa clara de propósito: as três marcas têm fundo branco, e sobre
        o fundo escuro da janela elas apareceriam como retângulos brancos soltos.
        """
        strip = QFrame()
        strip.setObjectName("ttCreditStrip")
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(24, 9, 24, 11)
        layout.setSpacing(12)

        plate = QFrame()
        plate.setObjectName("ttCredit")
        plate_layout = QHBoxLayout(plate)
        plate_layout.setContentsMargins(12, 6, 12, 6)
        plate_layout.setSpacing(13)
        for filename, height in (("logo_herpeto_mantiqueira.png", 30),
                                 ("logo_enbt.jpg", 27), ("logo_jbrj.jpg", 30)):
            path = os.path.join(PLUGIN_DIR, "assets", filename)
            if not os.path.exists(path):
                continue
            mark = QLabel()
            mark.setPixmap(QPixmap(path).scaledToHeight(
                height, qt_enum("TransformationMode", "SmoothTransformation")))
            plate_layout.addWidget(mark)
        layout.addWidget(plate)

        # A autoria fica junto das logos, a esquerda: e credito de pessoa, e nao
        # de instituicao, e some se ficar na mesma linha corrida que elas.
        self.author_label = QLabel()
        self.author_label.setObjectName("ttAuthor")
        self._bind(self.author_label, "developed_by")
        layout.addWidget(self.author_label)

        layout.addStretch(1)
        # O nome das instituicoes saiu daqui: as tres logos ao lado dizem
        # exatamente isso, e repetir em texto so competia por largura -- em
        # 940 px a linha era cortada. Fica como dica de ferramenta da placa,
        # onde continua legivel por leitor de tela e por quem nao reconhece uma
        # das marcas.
        self._bind(plate, "credit_line", "setToolTip")
        return strip

    def _build_footer(self):
        footer = QFrame()
        footer.setObjectName("ttFooter")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(38, 14, 38, 16)
        layout.setSpacing(10)
        self.back_button = QPushButton()
        self.back_button.setObjectName("ttGhost")
        self.back_button.clicked.connect(lambda: self._go(-1))
        layout.addWidget(self.back_button)
        layout.addStretch(1)
        self.footer_note = QLabel()
        self.footer_note.setObjectName("ttFooterNote")
        layout.addWidget(self.footer_note)
        layout.addStretch(1)
        self.next_button = QPushButton()
        self.next_button.setObjectName("ttPrimary")
        self.next_button.setMinimumWidth(200)
        self.next_button.setCursor(qt_enum("CursorShape", "PointingHandCursor"))
        self.next_button.clicked.connect(self._next_clicked)
        layout.addWidget(self.next_button)
        return footer

    def _show_about(self):
        """Creditos completos. As logos ja estao na lateral; aqui fica o texto."""
        QMessageBox.about(self, self.t("about"),
                          self.t("about_text").format(version=_plugin_version()))

    def _page_head(self, layout, glyph, title_key, subtitle_key, step=1):
        row = QHBoxLayout()
        row.setSpacing(11)
        mark = _icon(glyph, 17, ACCENT, 1.9)
        self._static_icons = getattr(self, "_static_icons", [])
        self._static_icons.append((mark, glyph, 17, 1.9))
        row.addWidget(mark, 0, qt_enum("AlignmentFlag", "AlignVCenter"))
        eyebrow = QLabel()
        eyebrow.setObjectName("ttEyebrow")
        eyebrow.setText(self.t("eyebrow").format(n=step))
        self._labels.append((eyebrow, "eyebrow", "setText"))
        eyebrow._step_number = step
        row.addWidget(eyebrow)
        row.addStretch(1)
        holder_top = QWidget(); holder_top.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(holder_top)

        row = QHBoxLayout()
        row.setSpacing(13)
        column = QVBoxLayout()
        column.setSpacing(4)
        title = QLabel()
        title.setObjectName("ttPageTitle")
        title.setWordWrap(True)
        self._bind(title, title_key)
        subtitle = QLabel()
        subtitle.setObjectName("ttPageSub")
        subtitle.setWordWrap(True)
        self._bind(subtitle, subtitle_key)
        column.addWidget(title)
        column.addWidget(subtitle)
        row.addLayout(column, 1)
        holder = QWidget()
        holder.setLayout(row)
        row.setContentsMargins(0, 0, 0, 4)
        layout.addWidget(holder)

    # -- passo 1: dados -----------------------------------------------------
    def _step_data(self, layout):
        self._page_head(layout, "mountain", "s1_title", "s1_sub", 1)

        banner = QFrame()
        banner.setObjectName("ttBanner")
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(14, 11, 14, 11)
        banner_layout.setSpacing(10)
        banner_layout.addWidget(_icon("check", 17, ACCENT, 1.85), 0,
                                qt_enum("AlignmentFlag", "AlignTop"))
        note = QLabel()
        note.setObjectName("ttBannerText")
        note.setWordWrap(True)
        self._bind(note, "s1_banner")
        banner_layout.addWidget(note, 1)
        layout.addWidget(banner)

        card, inner = _card(self.t("dem_card"), "mountain", badge="required")
        self._bind(card._title_label, "dem_card")
        self._bind(card._badge, "badge_required")
        self.dem_file = _RasterChip(self)
        inner.addWidget(self.dem_file)
        inner.addWidget(self._help_label("dem_help"))

        row = QHBoxLayout()
        row.addWidget(self._label("vunit"))
        row.addStretch(1)
        self.vertical_unit = _Segmented()
        row.addWidget(self.vertical_unit)
        inner.addLayout(row)
        inner.addWidget(self._help_label("vunit_help"))
        layout.addWidget(card)

        card, inner = _card(self.t("own_card"), "plus-layer")
        self._bind(card._title_label, "own_card")
        self.own_rasters = self._check("own_rasters")
        inner.addWidget(self.own_rasters)
        inner.addWidget(self._help_label("own_help"))

        self.own_section = _Section()
        self.slope_file = _FileRow("GeoTIFF (*.tif *.tiff)", "Declividade")
        self.curvh_file = _FileRow("GeoTIFF (*.tif *.tiff)", "Curvatura H")
        self.curvv_file = _FileRow("GeoTIFF (*.tif *.tiff)", "Curvatura V")
        self.slope_unit = QComboBox()
        form = self.own_section.add_form([
            (self.t("slope"), self.slope_file),
            (self.t("sunit"), self.slope_unit),
            (self.t("curvh"), self.curvh_file),
            (self.t("curvv"), self.curvv_file),
        ])
        for label, key in zip(form._labels, ("slope", "sunit", "curvh", "curvv")):
            self._bind(label, key)
        self.own_rasters.toggled.connect(self.own_section.setVisible)
        inner.addWidget(self.own_section)
        layout.addWidget(card)

    # -- passo 2: saidas ----------------------------------------------------
    def _option(self, glyph, title_key, help_key, checked=False, locked=False):
        card = OptionCard(glyph, enabled=not locked)
        self._bind(card.title, title_key)
        self._bind(card.description, help_key)
        if locked:
            card.lock_checked(self.t("badge_included"))
            self._labels.append((card.tick, "badge_included", "setText"))
        elif checked:
            card.setChecked(True)
        self._option_cards.append(card)
        return card

    def _group_head(self, title_key, subtitle_key, chip=False):
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(2, 4, 2, 2)
        row.setSpacing(10)
        column = QVBoxLayout()
        column.setSpacing(1)
        title = QLabel(); title.setObjectName("ttGroupLabel")
        self._bind(title, title_key)
        subtitle = QLabel(); subtitle.setObjectName("ttGroupSub")
        column.addWidget(title); column.addWidget(subtitle)
        row.addLayout(column, 1)
        holder._subtitle = subtitle
        holder._subtitle_key = subtitle_key
        if chip:
            badge = QLabel(); badge.setObjectName("ttCountChip")
            row.addWidget(badge, 0, qt_enum("AlignmentFlag", "AlignTop"))
            holder._chip = badge
        else:
            # Vinculado, e nao so escrito: escrito uma vez, ficava em portugues
            # depois de a pessoa trocar para japones.
            self._bind(subtitle, subtitle_key)
        return holder

    def _step_outputs(self, layout):
        self._page_head(layout, "layers", "s2_title", "s2_sub", 2)

        layout.addWidget(self._group_head("always", "group_always_sub"))
        layout.addWidget(self._option("grid", "o_score", "o_score_help", locked=True))
        layout.addWidget(self._option("alert", "o_risk", "o_risk_help", locked=True))
        layout.addSpacing(6)
        self.optional_head = self._group_head(
            "optional_group", "group_optional_sub", chip=True)
        layout.addWidget(self.optional_head)

        self.want_zones = self._option("polygon", "o_zones", "o_zones_help", checked=True)
        self.want_transit = self._option("boot", "o_transit", "o_transit_help", checked=True)
        self.want_streams = self._option("drop", "o_streams", "o_streams_help")
        for card in (self.want_zones, self.want_transit, self.want_streams):
            layout.addWidget(card)

        self.want_route = self._option("route", "o_route", "o_route_help")
        layout.addWidget(self.want_route)
        optional_cards = [self.want_zones, self.want_transit,
                          self.want_streams, self.want_route]
        for card, tip in ((self.want_transit, "o_transit_tip"),
                          (self.want_streams, "o_streams_tip"),
                          (self.want_route, "o_route_tip")):
            self._labels.append((card, tip, "setToolTip"))

        # Os campos da rota moram dentro do proprio cartao: aparecem no lugar
        # onde a pessoa acabou de dizer que quer rota, e nao num bloco solto
        # mais abaixo.
        body = self.want_route.body_layout
        self.start_file = _FileRow("Vetores (*.gpkg *.shp *.kml *.geojson)", "Origem")
        self.end_file = _FileRow("Vetores (*.gpkg *.shp *.kml *.geojson)", "Destino")
        self.via_file = _FileRow("Vetores (*.gpkg *.shp *.kml *.geojson)", "Waypoints")
        self.start_coord = QLineEdit(); self.start_coord.setPlaceholderText("X, Y")
        self.end_coord = QLineEdit(); self.end_coord.setPlaceholderText("X, Y")
        self.pick_start = QPushButton(); self.pick_end = QPushButton()
        self._bind(self.pick_start, "pick"); self._bind(self.pick_end, "pick")
        self.pick_start.clicked.connect(lambda: self.start_map_pick("start"))
        self.pick_end.clicked.connect(lambda: self.start_map_pick("end"))
        for button in (self.pick_start, self.pick_end):
            button.setCursor(qt_enum("CursorShape", "PointingHandCursor"))

        def point_row(key, file_row, coord, button):
            holder = QWidget()
            box = QHBoxLayout(holder)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(7)
            label = self._label(key)
            # Largura minima, e nao fixa: "Destination" precisa de 98 px e ficava
            # cortado em 64, enquanto "Origem" cabia. Um numero fixo so serve
            # para a lingua em que foi medido.
            label.setMinimumWidth(70)
            box.addWidget(label)
            box.addWidget(file_row, 3)
            box.addWidget(coord, 2)
            box.addWidget(button, 0)
            return holder

        body.addWidget(point_row("start", self.start_file, self.start_coord, self.pick_start))
        body.addWidget(point_row("end", self.end_file, self.end_coord, self.pick_end))
        body.addWidget(_divider())
        body.addWidget(self._label("via"))
        body.addWidget(self.via_file)
        body.addWidget(self._help_label("via_help"))
        self.optimise_order = QCheckBox()
        self._bind(self.optimise_order, "optimise")
        body.addWidget(self.optimise_order)
        body.addWidget(self._help_label("optimise_help"))
        body.addWidget(_divider())
        self.cost_model = QComboBox()
        body.addWidget(self._label("cost"))
        body.addWidget(self.cost_model)
        body.addWidget(self._help_label("cost_help"))
        self.corridor_m = _spin(1, 100000, 100.0, 0, 10, " m")
        self.margin_m = _spin(1, 200000, 5000.0, 0, 100, " m")
        for key, widget in (("corridor", self.corridor_m), ("margin", self.margin_m)):
            line = QHBoxLayout()
            line.addWidget(self._label(key)); line.addStretch(1); line.addWidget(widget)
            holder = QWidget(); holder.setLayout(line)
            line.setContentsMargins(0, 0, 0, 0)
            body.addWidget(holder)
        body.addWidget(self._help_label("margin_help"))
        self.want_route.toggled(self.want_route.body.setVisible)
        for card in optional_cards:
            card.toggled(lambda _value: self._refresh_context())

    # -- passo 3: ajustes ---------------------------------------------------
    def _step_tuning(self, layout):
        self._page_head(layout, "sliders", "s3_title", "s3_sub", 3)

        card, inner = _card(self.t("w_box"), "scale")
        self._bind(card._title_label, "w_box")
        inner.addWidget(self._help_label("w_help"))
        self.w_alt = _spin(0, 100, 0.0)
        self.w_slope = _spin(0, 100, 1.0)
        self.w_curvh = _spin(0, 100, 1.0)
        self.w_curvv = _spin(0, 100, 1.0)
        self.w_wet = _spin(0, 100, 0.0)
        self.w_rough = _spin(0, 100, 0.0)
        grid = QGridLayout()
        for index, (key, widget) in enumerate((
                ("w_alt", self.w_alt), ("w_slope", self.w_slope),
                ("w_curvh", self.w_curvh), ("w_curvv", self.w_curvv),
                ("w_wet", self.w_wet), ("w_rough", self.w_rough))):
            grid.addWidget(self._label(key), index // 2, (index % 2) * 2)
            grid.addWidget(widget, index // 2, (index % 2) * 2 + 1)
        grid.setColumnStretch(0, 1); grid.setColumnStretch(2, 1)
        holder = QWidget(); holder.setLayout(grid)
        inner.addWidget(holder)
        layout.addWidget(card)

        card, inner = _card(self.t("lim_box"), "ruler")
        self._bind(card._title_label, "lim_box")
        self.slope_max = _spin(0.1, 10000, 55.0, 1, 1, " %")
        self.slope_score_max = _spin(0.1, 10000, 50.0, 1, 1, " %")
        self.alt_min = _spin(-500, 9000, 0.0, 0, 10, " m")
        self.alt_max = _spin(-500, 9000, 2600.0, 0, 10, " m")
        for key, widget, help_key in (("slope_max", self.slope_max, "slope_max_help"),
                                      ("slope_score", self.slope_score_max, "slope_score_help")):
            line = QHBoxLayout()
            line.addWidget(self._label(key)); line.addWidget(widget); line.addStretch(1)
            inner.addLayout(line)
            inner.addWidget(self._help_label(help_key))
        row = QHBoxLayout()
        row.addWidget(self._label("alt_min")); row.addWidget(self.alt_min)
        row.addWidget(self._label("alt_max")); row.addWidget(self.alt_max)
        row.addStretch(1)
        inner.addLayout(row)
        layout.addWidget(card)

        card, inner = _card(self.t("zone_box"), "crop")
        self._bind(card._title_label, "zone_box")
        self.percentile = _spin(0.1, 99.9, 75.0, 1, 1)
        self.min_area = _spin(0, 1e6, 50.0, 1, 5, " ha")
        self.altitude_band = self._check("band"); self.altitude_band.setChecked(True)
        self.band_size = _spin(1, 5000, 200.0, 0, 10, " m")
        inner.addWidget(self._label("percentile")); inner.addWidget(self.percentile)
        inner.addWidget(self._help_label("percentile_help"))
        inner.addWidget(self._label("min_area")); inner.addWidget(self.min_area)
        inner.addWidget(self.altitude_band)
        inner.addWidget(self.band_size)
        self.breaks_edit = QLineEdit("20, 35, 60, 100")
        inner.addWidget(self._label("breaks")); inner.addWidget(self.breaks_edit)
        inner.addWidget(self._help_label("breaks_help"))
        layout.addWidget(card)

        card, inner = _card(self.t("extra_box"), "plus-layer")
        self._bind(card._title_label, "extra_box")
        inner.addWidget(self._help_label("extra_help"))
        self.extra_file = _FileRow("GeoTIFF (*.tif *.tiff)", "Criterio adicional")
        self.extra_weight = _spin(0, 100, 0.0)
        self.extra_direction = QComboBox()
        inner.addWidget(self._label("extra_layer")); inner.addWidget(self.extra_file)
        row = QHBoxLayout()
        row.addWidget(self._label("extra_weight")); row.addWidget(self.extra_weight)
        row.addWidget(self._label("extra_dir")); row.addWidget(self.extra_direction)
        row.addStretch(1)
        inner.addLayout(row)
        layout.addWidget(card)

        card, inner = _card(self.t("cons_box"), "shield")
        self._bind(card._title_label, "cons_box")
        inner.addWidget(self._help_label("cons_help"))
        self.constraint_file = _FileRow("Vetores (*.gpkg *.shp *.kml *.geojson)", "Restricao")
        self.constraint_buffer = _spin(0, 100000, 30.0, 0, 5, " m")
        self.constraint_mode = QComboBox()
        inner.addWidget(self._label("cons_layer")); inner.addWidget(self.constraint_file)
        row = QHBoxLayout()
        row.addWidget(self._label("cons_buffer")); row.addWidget(self.constraint_buffer)
        row.addWidget(self._label("cons_mode")); row.addWidget(self.constraint_mode)
        row.addStretch(1)
        inner.addLayout(row)
        layout.addWidget(card)

    # -- passo 4: executar --------------------------------------------------
    def _step_run(self, layout):
        self._page_head(layout, "play", "s4_title", "s4_sub", 4)

        card, inner = _card(self.t("out_box"), "save")
        self._bind(card._title_label, "out_box")
        inner.addWidget(self._label("out"))
        row = QHBoxLayout()
        self.output_edit = QLineEdit()
        button = QPushButton("…")
        button.setObjectName("ttBrowse")
        button.setFixedWidth(52)
        button.setCursor(qt_enum("CursorShape", "PointingHandCursor"))
        button.clicked.connect(self._browse_output)
        row.addWidget(self.output_edit, 1); row.addWidget(button, 0)
        inner.addLayout(row)
        row = QHBoxLayout()
        self.output_format = QComboBox()
        self.crs_edit = QLineEdit(); self.crs_edit.setPlaceholderText("EPSG:31983")
        row.addWidget(self._label("fmt")); row.addWidget(self.output_format)
        row.addWidget(self._label("crs")); row.addWidget(self.crs_edit, 1)
        inner.addLayout(row)
        inner.addWidget(self._help_label("crs_help"))
        layout.addWidget(card)

        card, inner = _card(self.t("summary"), "check")
        self._bind(card._title_label, "summary")
        self.summary_label = _help("")
        # Sem altura fixa: o resumo cresce conforme o numero de saidas marcadas,
        # e com altura fixa a ultima linha ficava cortada.
        self.summary_label.setSizePolicy(size_policy("Preferred"), size_policy("Minimum"))
        self.summary_label.setAlignment(qt_enum("AlignmentFlag", "AlignTop"))
        inner.addWidget(self.summary_label)
        layout.addWidget(card)

        card, inner = _card(self.t("log"), "pulse")
        self._bind(card._title_label, "log")
        self.progress = QProgressBar()
        self.progress.setValue(0)
        inner.addWidget(self.progress)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(150)
        self.log_view.setObjectName("ttLog")
        self._bind(self.log_view, "log_empty", "setPlaceholderText")
        inner.addWidget(self.log_view)
        layout.addWidget(card)

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("out"), "", "GeoPackage (*.gpkg);;Shapefile (*.shp)")
        if path:
            self.output_edit.setText(path)

    # -- enums e tema -------------------------------------------------------
    def _fill_enums(self):
        """Preenche as listas de opções no idioma em vigor.

        Ficavam com o texto escrito direto aqui, em dois idiomas, escolhidos por
        um `if lang == "pt"`. Com seis línguas isso não escala, e o resultado era
        uma tela em japonês com "Metres | Feet" no meio dela.
        """
        def fill(box, keys):
            current = box.currentIndex()
            box.blockSignals(True)
            box.clear()
            box.addItems([self.t(key) for key in keys])
            box.setCurrentIndex(max(current, 0))
            box.blockSignals(False)

        fill(self.vertical_unit, ["unit_metres", "unit_feet"])
        fill(self.slope_unit, ["slope_percent", "slope_degrees"])
        fill(self.cost_model, ["cost_inverse", "cost_exponential", "cost_tobler"])
        if self.cost_model.currentIndex() == 0:
            self.cost_model.setCurrentIndex(2)
        fill(self.extra_direction, ["dir_low", "dir_high"])
        fill(self.constraint_mode, ["cons_avoid", "cons_penalise"])
        # A ordem tem de bater com options= do algoritmo: enum do QGIS viaja
        # como índice, não como texto.
        fill(self.output_format, ["fmt_shp", "fmt_gpkg", "fmt_kml"])
        if not self._format_initialised:
            self.output_format.setCurrentIndex(1)
            self._format_initialised = True

    def _cycle_theme(self):
        """auto → claro → escuro → auto.

        Existe porque o QGIS tem tema proprio: seguir o tema em vigor e o
        comportamento certo por padrao, mas quem quiser a janela escura num QGIS
        claro (ou o contrario) nao deveria ter de trocar o tema do programa
        inteiro para isso.
        """
        order = ["auto", "light", "dark"]
        self.theme_mode = order[(order.index(self.theme_mode) + 1) % 3]
        self._apply_theme()
        self._retranslate()
        self._repaint_icons()

    def _apply_theme(self):
        global T, INK, MUTED, FOREST, ACCENT, ACCENT_SOFT, CANVAS, LINE
        mode = getattr(self, "theme_mode", "auto")
        dark = _is_dark_theme() if mode == "auto" else (mode == "dark")
        T = dict(DARK if dark else LIGHT)
        INK, MUTED, FOREST = T["ink"], T["muted"], T["forest"]
        ACCENT, ACCENT_SOFT = T["accent"], T["accent_soft"]
        CANVAS, LINE = T["canvas"], T["line"]
        t = T
        header_bg = "#0f1a15" if dark else "#0d452c"
        self.setStyleSheet(f"""
            QDialog {{ background: {t['canvas']}; }}
            QLabel {{ color: {t['ink']}; font-size: 13px; }}
            QPushButton {{ font-size: 13px; }}

            #ttHeader {{ background: {header_bg};
                         border-bottom: 1px solid {'#22302a' if dark else '#0a3a25'}; }}
            #ttMark {{ background: {t['plate']}; border-radius: 11px; }}
            #ttBrand {{ color: #ffffff; font-size: 13px; font-weight: 700;
                        letter-spacing: 1.4px; }}
            #ttTagline {{ color: #86a89a; font-size: 11px; }}
            #ttHeaderSelect {{ background: rgba(255,255,255,0.08); border: none;
                               color: #cfe3d8; font-size: 11px; padding: 6px 10px;
                               border-radius: 8px; }}
            #ttHeaderSelect::drop-down {{ border: none; width: 18px; }}
            #ttHeaderSelect QAbstractItemView {{ background: {t['surface']};
                                                 color: {t['ink']};
                                                 selection-background-color: {t['accent']};
                                                 border: 1px solid {t['line']}; }}
            #ttHeaderAction {{ background: rgba(255,255,255,0.08); border: none;
                               color: #cfe3d8; font-size: 11px; padding: 7px 12px;
                               border-radius: 8px; }}
            #ttHeaderAction:hover {{ background: rgba(255,255,255,0.16);
                                     color: #ffffff; }}
            #ttQuiet {{ background: transparent; border: none; color: #7d9a8d;
                        font-size: 11px; padding: 4px 2px; text-align: left; }}
            #ttQuiet:hover {{ color: #ffffff; }}
            #ttQuietText {{ color: #7d9a8d; font-size: 11px; padding-left: 4px; }}

            #ttPill {{ background: transparent; border-radius: 10px; }}
            #ttPill:hover {{ background: rgba(255,255,255,0.06); }}
            #ttPill[active="true"] {{ background: rgba(255,255,255,0.13); }}
            #ttStepText {{ color: #83a696; font-size: 12px; }}
            #ttStepText[active="true"] {{ color: #ffffff; font-weight: 600; }}
            #ttStepText[active="done"] {{ color: #b9d5c7; }}
            #ttBadge {{ border-radius: 12px; font-size: 11px; font-weight: 700;
                        background: rgba(255,255,255,0.09); color: #83a696; }}
            #ttBadge[active="true"] {{ background: {t['gold']}; color: #26200c; }}
            #ttBadge[active="done"] {{ background: rgba(63,174,130,0.22);
                                       color: {t['accent']}; }}

            #ttPage {{ background: {t['canvas']}; }}
            #ttEyebrow {{ color: {t['accent']}; font-size: 10px; font-weight: 700;
                          letter-spacing: 1.3px; }}
            #ttPageTitle {{ font-size: 22px; font-weight: 600; color: {t['ink']}; }}
            #ttPageSub {{ font-size: 13px; color: {t['muted']}; }}
            #ttGroupLabel {{ font-size: 14px; font-weight: 600; color: {t['ink']}; }}
            #ttGroupSub {{ font-size: 12px; color: {t['muted']}; }}
            #ttCountChip {{ background: {t['accent_soft']}; color: {t['accent']};
                            font-size: 10px; font-weight: 600; padding: 4px 9px;
                            border-radius: 9px; }}

            #ttBanner {{ background: {t['accent_soft']};
                         border: 1px solid {'#24483b' if dark else '#cfe6da'};
                         border-radius: 10px; }}
            #ttBannerText {{ color: {t['accent'] if dark else '#14614a'};
                             font-size: 12px; }}

            #ttCard {{ background: {t['surface']}; border: 1px solid {t['line']};
                       border-radius: 14px; }}
            #ttCardTitle {{ font-size: 14px; font-weight: 600; color: {t['ink']}; }}
            #ttBadgeChip {{ background: {t['accent_soft']}; color: {t['accent']};
                            font-size: 10px; font-weight: 700; padding: 4px 9px;
                            border-radius: 8px; }}
            #ttHelp {{ color: {t['muted']}; font-size: 12px; }}
            #ttDivider {{ background: {t['line']}; border: none; }}

            #ttChip {{ background: {t['surface_alt']}; border: 1px solid {t['line']};
                       border-radius: 11px; }}
            #ttChipName {{ font-size: 13px; font-weight: 600; color: {t['ink']}; }}
            #ttChipDetail {{ font-size: 11px; color: {t['muted']}; }}

            #ttSegment {{ background: {t['surface_alt']};
                          border: 1px solid {t['line']}; border-radius: 10px; }}
            #ttSegmentButton {{ background: transparent; border: none;
                                color: {t['muted']}; font-size: 12px;
                                padding: 6px 18px; border-radius: 7px; }}
            #ttSegmentButton:checked {{ background: {t['accent']}; color: #ffffff;
                                        font-weight: 600; }}

            #ttOption {{ background: {t['surface']}; border: 1px solid {t['line']};
                         border-radius: 12px; }}
            #ttOption:hover {{ border-color: {t['line_strong']}; }}
            #ttOption[checked="true"] {{ border: 1.5px solid {t['accent']};
                                         background: {t['accent_tint']}; }}
            #ttOption[locked="true"] {{ background: {t['surface_alt']};
                                        border: 1px dashed {t['line_strong']}; }}
            #ttOption[locked="true"]:hover {{ border-color: {t['line_strong']}; }}
            #ttOptionTitle {{ font-size: 13px; font-weight: 600; color: {t['ink']}; }}
            #ttTick {{ color: {t['muted']}; font-size: 10px; }}
            #ttIncludedPill {{ background: {t['accent_soft']}; color: {t['accent']};
                               font-size: 10px; font-weight: 700; padding: 4px 10px;
                               border-radius: 9px; }}

            #ttFooter {{ background: {t['surface']};
                         border-top: 1px solid {t['line']}; }}
            #ttFooterNote {{ color: {t['muted']}; font-size: 12px; }}
            #ttPrimary {{ background: {t['accent']}; color: #ffffff; font-size: 13px;
                          font-weight: 600; padding: 10px 22px; border: none;
                          border-radius: 9px; }}
            #ttPrimary:hover {{ background: {t['accent_hover']}; }}
            #ttPrimary:disabled {{ background: {t['line_strong']}; }}
            #ttGhost {{ background: transparent; color: {t['muted']}; border: none;
                        padding: 10px 12px; font-size: 12px; }}
            #ttGhost:hover {{ color: {t['ink']}; }}
            #ttGhost:disabled {{ color: {t['line_strong']}; }}

            #ttCreditStrip {{ background: {header_bg};
                              border-top: 1px solid {'#22302a' if dark else '#0a3a25'}; }}
            #ttCredit {{ background: {t['plate']}; border-radius: 9px; }}
            #ttAuthor {{ color: #b9d5c7; font-size: 11px; font-weight: 600; }}

            QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QTextEdit {{
                border: 1px solid {t['line']}; border-radius: 8px; font-size: 13px;
                padding: 7px 9px; background: {t['surface_alt']}; color: {t['ink']};
                selection-background-color: {t['accent']};
            }}
            QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus,
            QComboBox:focus, QTextEdit:focus {{ border: 1px solid {t['accent']}; }}
            QComboBox::drop-down {{ border: none; width: 22px; }}
            QDoubleSpinBox::up-button, QSpinBox::up-button,
            QDoubleSpinBox::down-button, QSpinBox::down-button {{
                width: 0; height: 0; border: none;
            }}

            QPushButton {{ background: {t['surface_alt']};
                           border: 1px solid {t['line']}; border-radius: 8px;
                           padding: 7px 13px; color: {t['ink']}; }}
            QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
            #ttBrowse {{ padding: 7px 0; font-size: 15px; color: {t['muted']}; }}

            QCheckBox {{ spacing: 10px; color: {t['ink']}; font-size: 13px; }}
            QCheckBox::indicator {{ width: 17px; height: 17px;
                                    border: 1px solid {t['line_strong']};
                                    border-radius: 5px; background: {t['surface_alt']}; }}
            QCheckBox::indicator:checked {{ background: {t['accent']};
                                            border-color: {t['accent']}; }}
            #ttToggle::indicator {{ width: 40px; height: 22px; border-radius: 11px;
                                    background: {t['line_strong']};
                                    border: none; }}
            #ttToggle::indicator:checked {{ background: {t['accent']}; }}

            QProgressBar {{ border: none; border-radius: 5px; height: 8px;
                            text-align: center; color: transparent;
                            background: {t['line']}; }}
            QProgressBar::chunk {{ background: {t['accent']}; border-radius: 5px; }}
            #ttLog {{ background: {t['surface_alt']}; font-family: "DejaVu Sans Mono",
                      Consolas, monospace; font-size: 11px; color: {t['muted']}; }}

            QToolTip {{ background: {'#0b1310' if dark else t['ink']}; color: #ffffff;
                        border: 1px solid {t['line']}; padding: 9px 11px;
                        border-radius: 7px; font-size: 12px; }}
            QScrollArea {{ background: {t['canvas']}; }}
            QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
            QScrollBar::handle:vertical {{ background: {t['line_strong']};
                                           border-radius: 5px; min-height: 30px; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
        """)
        # Sem repolir explicitamente, a folha nova so alcanca os filhos no
        # proximo show(): trocar de tema com a janela aberta nao surtia efeito
        # nenhum, que e justamente quando o botao de tema e usado.
        for widget in self.findChildren(QWidget):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def showEvent(self, event):
        """Reaplica o tema quando a janela aparece.

        O Qt só termina de polir a árvore de widgets no primeiro show, e uma
        folha de estilo aplicada antes disso não alcança o que está dentro da
        área de rolagem: cabeçalho e rodapé ficavam escuros e o miolo continuava
        claro. Reaplicar aqui, uma vez, resolve sem depender da ordem de chamada.
        """
        super().showEvent(event)
        if not getattr(self, "_theme_settled", False):
            self._theme_settled = True
            self._apply_theme()
            self._repaint_icons()

    def _repaint_icons(self):
        """Redesenha os glifos na cor do tema em vigor.

        Os ícones são pixmaps traçados com a cor embutida, então trocar a folha
        de estilo não os alcança -- é o preço de desenhá-los em tempo de
        execução, e a contrapartida é que aqui basta redesenhar.
        """
        for card in getattr(self, "_option_cards", []):
            card.refresh_theme()
        for label, name, size, width in getattr(self, "_static_icons", []):
            label.setPixmap(icons.pixmap(name, size, ACCENT, width))

    # -- navegacao ----------------------------------------------------------
    def _go(self, delta):
        target = self.stack.currentIndex() + delta
        if 0 <= target < self.stack.count():
            self.stack.setCurrentIndex(target)
            self._update_nav()

    def route_widgets(self, target):
        """Contrato do TopotrailSupportMixin: quais campos guardam cada ponto."""
        if target == "start":
            return self.start_file, self.start_coord
        return self.end_file, self.end_coord

    def _jump_to(self, target):
        """Voltar clicando no indicador. So para tras: avancar continua
        passando pela validacao do passo atual, senao daria para chegar ao
        botao de executar sem MDE nenhum."""
        if target < self.stack.currentIndex():
            self.stack.setCurrentIndex(target)

    def _next_clicked(self):
        index = self.stack.currentIndex()
        if index == self.stack.count() - 1:
            if self._task is not None:
                self._cancel()
            else:
                self._run()
            return
        error = self._validate(index)
        if error:
            QMessageBox.warning(self, self.t("err_title"), error)
            return
        self._go(1)

    def _update_nav(self):
        index = self.stack.currentIndex()
        self.back_button.setEnabled(index > 0)
        last = index == self.stack.count() - 1
        if last and self._task is not None:
            self.next_button.setText(self.t("cancel"))
        else:
            self.next_button.setText(
                self.t("run") if last else self.t("next_alt"))
        for position, (row, badge) in enumerate(self._step_rows):
            state = "true" if position == index else (
                "done" if position < index else "false")
            badge.setText("✓" if state == "done" else str(position + 1))
            for widget in (row, badge, self.step_labels[position]):
                widget.setProperty("active", state)
                widget.style().unpolish(widget)
                widget.style().polish(widget)
        self._refresh_context()
        if last:
            self._refresh_summary()

    def _refresh_context(self):
        """A mensagem do rodapé e os contadores do passo 2.

        O rodapé tinha espaço vazio entre "Voltar" e "Avançar", e a pergunta que
        o usuário faz nesse ponto é sempre a mesma -- posso seguir? o que falta?
        Agora é ali que está a resposta.
        """
        optional = [self.want_zones, self.want_transit,
                    self.want_streams, self.want_route]
        chosen = sum(card.isChecked() for card in optional)
        if hasattr(self, "optional_head"):
            self.optional_head._subtitle.setText(
                self.t("group_optional_sub").format(n=chosen))
            self.optional_head._chip.setText(
                self.t("total_chip").format(n=chosen + 2))

        index = self.stack.currentIndex()
        if not self.dem_file.text():
            note = self.t("note_need_dem")
        elif index == 1:
            note = self.t("note_outputs").format(n=chosen + 2)
        elif index == 2:
            note = self.t("note_tuning")
        elif index == 3:
            note = self.t("note_review")
        else:
            note = self.t("note_outputs").format(n=chosen + 2)
        self.footer_note.setText(note)

    def _refresh_summary(self):
        pt = self.lang == "pt"
        items = ["• " + self.t("o_score"), "• " + self.t("o_risk")]
        if self.want_zones.isChecked():
            items.append("• " + self.t("o_zones"))
        if self.want_transit.isChecked():
            items.append("• " + self.t("o_transit"))
        if self.want_streams.isChecked():
            items.append("• " + self.t("o_streams"))
        if self.want_route.isChecked():
            route = "• " + self.t("o_route")
            if self.via_file.text():
                route += (" (com destinos intermediários)" if pt
                          else " (with intermediate destinations)")
            items.append(route)
        self.summary_label.setText("\n".join(items))

    # -- validacao ----------------------------------------------------------
    def _validate(self, index):
        if index == 0:
            path = self.dem_file.text()
            if not path:
                return self.t("err_dem")
            layer = QgsRasterLayer(path, "dem")
            if not layer.isValid():
                return self.t("err_dem_invalid").format(path=path)
            if not layer.crs().isValid():
                return self.t("err_dem_crs").format(path=path)
            if self.own_rasters.isChecked() and not all(
                    [self.slope_file.text(), self.curvh_file.text(),
                     self.curvv_file.text()]):
                return self.t("err_rasters")
        if index == 1 and self.want_route.isChecked():
            has_start = bool(self.start_file.text() or self.start_coord.text().strip())
            has_end = bool(self.end_file.text() or self.end_coord.text().strip())
            if not (has_start and has_end):
                return self.t("err_points")
        if index == 2:
            weights = [self.w_alt, self.w_slope, self.w_curvh, self.w_curvv,
                       self.w_wet, self.w_rough]
            if all(spin.value() == 0 for spin in weights):
                return self.t("err_weights")
            if self.alt_min.value() >= self.alt_max.value():
                return self.t("err_alt")
            if self._parse_breaks() is None:
                return self.t("err_breaks")
        return None

    def _parse_breaks(self):
        try:
            values = [float(part) for part in
                      self.breaks_edit.text().replace(";", ",").split(",")]
        except ValueError:
            return None
        if len(values) != 4 or any(values[i] >= values[i + 1] for i in range(3)):
            return None
        return values

    # -- execucao -----------------------------------------------------------
    def _collect(self):
        start_path, end_path = self.resolve_route_points() \
            if self.want_route.isChecked() else (None, None)
        breaks = self._parse_breaks() or [20.0, 35.0, 60.0, 100.0]
        params = {
            "INPUT_DEM": self.dem_file.text(),
            "DERIVE_FROM_DEM": not self.own_rasters.isChecked(),
            "VERTICAL_UNIT": self.vertical_unit.currentIndex(),
            "WEIGHT_ALT": self.w_alt.value(),
            "WEIGHT_SLOPE": self.w_slope.value(),
            "WEIGHT_CURVH": self.w_curvh.value(),
            "WEIGHT_CURVV": self.w_curvv.value(),
            "WEIGHT_WETNESS": self.w_wet.value(),
            "WEIGHT_ROUGHNESS": self.w_rough.value(),
            "ALT_MIN": self.alt_min.value(),
            "ALT_MAX": self.alt_max.value(),
            "SLOPE_MAX": self.slope_max.value(),
            "SLOPE_SCORE_MAX": self.slope_score_max.value(),
            "THRESHOLD": 0.0,
            "AUTO_PERCENTILE": self.percentile.value(),
            "MIN_PATCH_AREA_HA": self.min_area.value(),
            "ALTITUDE_BAND_THRESHOLD": self.altitude_band.isChecked(),
            "ALTITUDE_BAND_SIZE_M": self.band_size.value(),
            "GENERATE_ZONES": self.want_zones.isChecked(),
            "STREAMS_FROM_DEM": self.want_streams.isChecked(),
            "STREAM_MIN_BASIN_KM2": 1.0,
            "TRANSITABILITY_BREAKS": ", ".join(f"{value:g}" for value in breaks),
            "OUTPUT_FILE": self.output_edit.text(),
            "OUTPUT_FORMAT": self.output_format.currentIndex(),
        }
        if self.own_rasters.isChecked():
            params.update({
                "INPUT_SLOPE": self.slope_file.text(),
                "INPUT_CURVH": self.curvh_file.text(),
                "INPUT_CURVV": self.curvv_file.text(),
                "SLOPE_UNIT": self.slope_unit.currentIndex(),
            })
        if self.crs_edit.text().strip():
            params["OUTPUT_CRS"] = self.crs_edit.text().strip()
        if self.want_route.isChecked():
            params.update({
                "START_POINT_FILE": start_path,
                "END_POINT_FILE": end_path,
                "VIA_POINTS_FILE": self.via_file.text() or None,
                "OPTIMISE_ORDER": self.optimise_order.isChecked(),
                "ROUTE_COST_MODEL": self.cost_model.currentIndex(),
                "ROUTE_BUFFER_M": self.corridor_m.value(),
                "ROUTE_MARGIN_M": self.margin_m.value(),
            })
        if self.extra_file.text() and self.extra_weight.value() > 0:
            params.update({
                "EXTRA_CRITERION_LAYER": self.extra_file.text(),
                "EXTRA_CRITERION_WEIGHT": self.extra_weight.value(),
                "EXTRA_CRITERION_DIRECTION": self.extra_direction.currentIndex(),
            })
        if self.constraint_file.text():
            params.update({
                "CONSTRAINT_LAYER": self.constraint_file.text(),
                "CONSTRAINT_BUFFER_M": self.constraint_buffer.value(),
                "CONSTRAINT_MODE": self.constraint_mode.currentIndex(),
            })
        return params

    def _run(self):
        if not self.output_edit.text().strip():
            QMessageBox.warning(self, self.t("err_title"), self.t("err_out"))
            return
        params = self._collect()
        self.log_view.clear()
        self.progress.setRange(0, 0)

        feedback = QgsProcessingFeedback()
        feedback.progressChanged.connect(self._on_progress)
        try:
            feedback.pushInfo = self._log_line
            feedback.pushWarning = lambda text: self._log_line("⚠ " + text)
        except (AttributeError, TypeError):
            pass
        self._feedback = feedback

        alg = QgsApplication.processingRegistry().algorithmById("topotrail:topotrail")
        if alg is None:
            self._finish_error(Exception(
                "O algoritmo topotrail:topotrail nao esta registrado no QGIS."), params)
            return
        try:
            from qgis.core import QgsProcessingAlgRunnerTask
            context = QgsProcessingContext()
            context.setProject(QgsProject.instance())
            self._context = context
            task = QgsProcessingAlgRunnerTask(alg, params, context, feedback)
            task.executed.connect(lambda ok, results: self._finish(ok, results, params))
            self._task = task
            self._update_nav()
            QgsApplication.taskManager().addTask(task)
        except Exception:
            # Sem gerenciador de tarefas (execucao em script, QGIS antigo):
            # roda de forma sincrona em vez de falhar.
            try:
                results = processing.run("topotrail:topotrail", params,
                                         feedback=feedback)
                self._finish(True, results, params)
            except Exception as error:
                self._finish_error(error, params)

    def _cancel(self):
        if self._task is not None:
            self._task.cancel()
            self._log_line(self.t("cancelled"))
            self._task = None
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self._update_nav()

    def _on_progress(self, value):
        self.progress.setRange(0, 100)
        self.progress.setValue(int(value))

    def _log_line(self, text):
        self.log_view.append(str(text))
        self.log_view.ensureCursorVisible()
        QApplication.processEvents()

    def _finish(self, ok, results, params):
        self._task = None
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if ok else 0)
        self._update_nav()
        if not ok:
            self._finish_error(Exception("\n".join(
                self.log_view.toPlainText().splitlines()[-8:]) or "?"), params)
            return
        loaded = self._load_results(results or {})
        self.cleanup_temp_point_files()
        QMessageBox.information(self, self.t("done_title"),
                                self.t("done_text").format(count=loaded))

    def _finish_error(self, error, params):
        self._task = None
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._update_nav()
        log_path = append_gui_diagnostic_log(
            self.output_edit.text(), "interface_erro", erro=str(error),
            traceback=traceback.format_exc(),
            parametros=serialize_processing_params(params))
        self.cleanup_temp_point_files()
        QMessageBox.critical(self, self.t("fail_title"),
                             self.t("fail_text").format(error=str(error),
                                                        log_path=log_path))

    def _load_results(self, results):
        """Carrega tudo o que o algoritmo produziu, ja estilizado.

        Inclui o mapa de transitabilidade, que existia desde a versao 0.6.2 e
        que a janela anterior simplesmente nunca carregava.
        """
        project = QgsProject.instance()
        rasters = [
            ("OUTPUT_SCORE_RASTER", "TopoTrail — adequabilidade", self.style_score_layer),
            ("OUTPUT_RISK_RASTER", "TopoTrail — risco topográfico", self.style_risk_layer),
            ("OUTPUT_TRANSITABILITY", "TopoTrail — transitabilidade", None),
        ]
        vectors = [
            ("OUTPUT_VECTOR", "TopoTrail — zonas", self.style_zone_layer),
            ("OUTPUT_ROUTE", "TopoTrail — rota", self.style_route_layer),
            ("OUTPUT_CORRIDOR", "TopoTrail — corredor", self.style_corridor_layer),
        ]
        loaded = []
        for key, title, styler in rasters:
            path = results.get(key)
            if not path or not os.path.exists(str(path)):
                continue
            layer = QgsRasterLayer(str(path), title)
            if not layer.isValid():
                continue
            if styler:
                try:
                    styler(layer)
                except Exception:
                    pass
            project.addMapLayer(layer)
            loaded.append(layer)
        for key, title, styler in vectors:
            path = results.get(key)
            if not path or not os.path.exists(str(path)):
                continue
            layer = QgsVectorLayer(str(path), title, "ogr")
            if not layer.isValid() or layer.featureCount() == 0:
                continue
            if styler:
                try:
                    styler(layer)
                except Exception:
                    pass
            project.addMapLayer(layer)
            loaded.append(layer)
        if loaded and self.iface:
            self.iface.mapCanvas().setExtent(loaded[0].extent())
            self.iface.mapCanvas().refresh()
        return len(loaded)
