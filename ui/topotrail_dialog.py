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
from qgis.PyQt.QtGui import QFont, QPixmap
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

from .support import (
    TopotrailSupportMixin, append_gui_diagnostic_log, qt_enum,
    serialize_processing_params, size_policy,
)

PLUGIN_DIR = os.path.dirname(os.path.dirname(__file__))

# --------------------------------------------------------------------------
# Textos
# --------------------------------------------------------------------------
# Mantidos num dicionario e nao em .ts porque o plugin precisa alternar idioma
# em tempo de execucao, com o botao PT-BR | ENG, e nao apenas no idioma do QGIS:
# equipes de campo brasileiras costumam rodar o QGIS em ingles e querer a
# ferramenta em portugues.

TEXTS = {
    "pt": {
        "window": "TopoTrail — planejamento de trilhas e acessos",
        "steps": ["1. Dados", "2. O que você quer", "3. Ajustes", "4. Executar"],
        "back": "◀ Voltar", "next": "Avançar ▶", "run": "Gerar resultados",
        "cancel": "Cancelar execução",

        "s1_title": "De que dados você dispõe?",
        "s1_sub": "Só o modelo digital de elevação é obrigatório. Declividade e "
                  "curvaturas são calculadas a partir dele.",
        "dem": "Modelo digital de elevação (MDE)",
        "dem_help": "Um raster de altitude em GeoTIFF. Serve qualquer fonte: "
                    "Copernicus, SRTM, ALOS, carta topográfica nacional.",
        "vunit": "Unidade vertical do MDE",
        "vunit_help": "Metros na quase totalidade dos produtos. Pés aparecem em "
                      "alguns dados dos Estados Unidos.",
        "own_rasters": "Já tenho declividade e curvaturas prontas e quero usá-las",
        "own_help": "Marque apenas se preferir seus próprios rasters. Deixar "
                    "desmarcado é o caminho recomendado: derivar do MDE elimina "
                    "problemas de unidade, de convenção de sinal e de "
                    "alinhamento de grade.",
        "slope": "Declividade", "curvh": "Curvatura horizontal",
        "curvv": "Curvatura vertical", "sunit": "Unidade da declividade",

        "s2_title": "O que você quer que o plugin produza?",
        "s2_sub": "Marque o que for útil. Os dois primeiros saem sempre.",
        "always": "Sempre gerados",
        "o_score": "Mapa de adequabilidade topográfica",
        "o_score_help": "Nota de 0 a 1 por célula, combinando os critérios "
                        "escolhidos no passo 3.",
        "o_risk": "Mapa de risco topográfico relativo",
        "o_risk_help": "O complemento da adequabilidade, para leitura direta de "
                       "onde o terreno é mais desfavorável.",
        "o_zones": "Zonas de acesso potencial (vetor)",
        "o_zones_help": "Converte as melhores áreas em polígonos, para recorte e "
                        "medida de área.",
        "o_transit": "Mapa de transitabilidade — “onde dá para andar”",
        "o_transit_help": "Cinco classes de declividade com legenda gravada no "
                          "arquivo. Abre já colorido no QGIS. Os rótulos "
                          "descrevem inclinação, não veredito sobre quem passa: "
                          "equipes de campo percorrem rotineiramente as classes "
                          "4 e 5.",
        "o_streams": "Levar cursos d'água em conta, extraídos do próprio MDE",
        "o_streams_help": "Deriva a rede de drenagem do relevo e a usa como "
                          "restrição da rota — não precisa de camada de "
                          "hidrografia. Cuidado em paisagem seca: as equipes "
                          "cruzam drenagem o dobro do acaso, então evitá-la "
                          "costuma afastar a rota do que se quer visitar.",
        "o_route": "Rota entre pontos e corredor de acesso",
        "o_route_help": "Caminho de menor custo entre a origem e o destino, "
                        "podendo passar por destinos intermediários.",
        "route_box": "Rota",
        "start": "Origem", "end": "Destino",
        "via": "Destinos intermediários, na ordem de visita (opcional)",
        "via_help": "Uma camada de pontos. A ordem das feições é a ordem da "
                    "travessia: desenhe Marins, Marinzinho e Itaguaré nessa "
                    "sequência e a rota sobe os três. Sem isso o algoritmo "
                    "contorna os cumes — corretamente, porque o cume é caro.",
        "optimise": "Deixar o plugin escolher a melhor ordem de visita",
        "optimise_help": "Resolve a ordem de menor custo exatamente, até oito "
                         "pontos intermediários. Ignora a ordem da camada.",
        "pick": "Marcar no mapa", "file": "Arquivo…",
        "cost": "Como medir o custo do caminho",
        "cost_help": "“Tempo de caminhada” usa a função de Tobler: subir custa "
                     "mais que descer, e o custo sai em horas. É o modelo "
                     "validado contra GPS de campo e o recomendado.",
        "corridor": "Largura do corredor (m)",
        "margin": "Margem lateral de busca (m)",
        "margin_help": "Quanto o algoritmo pode se afastar da linha reta entre "
                       "os pontos. Margem pequena demais força a rota a ser reta; "
                       "grande demais deixa o cálculo lento.",

        "s3_title": "Ajustes",
        "s3_sub": "Os valores padrão foram calibrados contra trilhas reais. "
                  "Mexer aqui é opcional.",
        "w_box": "Peso de cada critério",
        "w_help": "Quanto cada critério pesa na nota final. Zero desliga o "
                  "critério. Altitude vem em zero de propósito: faixas de "
                  "altitude descartam terreno bom em regiões montanhosas.",
        "w_alt": "Altitude", "w_slope": "Declividade",
        "w_curvh": "Curvatura horizontal", "w_curvv": "Curvatura vertical",
        "w_wet": "Umidade do terreno", "w_rough": "Rugosidade",
        "lim_box": "Limites do terreno",
        "slope_max": "Declividade máxima admitida (%)",
        "slope_max_help": "Acima disto a célula é considerada inviável. "
                          "100% equivale a 45 graus.",
        "slope_score": "Declividade de nota zero (%)",
        "slope_score_help": "Onde a nota de declividade chega a zero. Se a maior "
                            "parte da sua área passar deste valor, o critério "
                            "para de distinguir encostas e o plugin avisa.",
        "alt_min": "Altitude mínima (m)", "alt_max": "Altitude máxima (m)",
        "zone_box": "Como recortar as zonas",
        "percentile": "Percentil de corte",
        "percentile_help": "75 mantém o quarto melhor da área. Menor, mais "
                           "permissivo.",
        "min_area": "Área mínima do fragmento (ha)",
        "band": "Equilibrar zonas por faixa altimetrica",
        "band_size": "Tamanho da faixa (m)",
        "breaks": "Limites das classes de transitabilidade (%)",
        "breaks_help": "Quatro valores crescentes separando as cinco classes.",
        "extra_box": "Critério adicional (opcional)",
        "extra_layer": "Raster extra",
        "extra_help": "Qualquer raster seu pode entrar no modelo: pedregosidade, "
                      "cobertura vegetal, uma superfície de custo pronta.",
        "extra_weight": "Peso", "extra_dir": "Valores altos são",
        "cons_box": "Restrições (opcional)",
        "cons_layer": "Camada a evitar",
        "cons_help": "Vetor de feições a evitar: cerca, área vedada, propriedade "
                     "privada. Atenção com hidrografia: em paisagem seca as "
                     "equipes cruzam drenagem o dobro do acaso, então penalizá-la "
                     "costuma afastar a rota do que se quer visitar.",
        "cons_buffer": "Distância a manter (m)", "cons_mode": "Tratamento",

        "s4_title": "Onde salvar e executar",
        "s4_sub": "O cálculo roda em segundo plano; o QGIS continua utilizável.",
        "out": "Arquivo de saída", "fmt": "Formato do vetor",
        "crs": "CRS de saída (opcional)",
        "crs_help": "Em branco, usa o CRS do projeto.",
        "summary": "Resumo do que será gerado",
        "log": "Andamento",

        "err_title": "Falta um dado",
        "err_dem": "Escolha o modelo digital de elevação para continuar.",
        "err_dem_invalid": "Não consegui abrir este raster como camada válida:\n{path}",
        "err_dem_crs": "Este raster não tem CRS definido:\n{path}\n\n"
                       "Defina o sistema de coordenadas antes de usá-lo.",
        "err_rasters": "Você marcou que vai usar seus próprios rasters, então "
                       "declividade e as duas curvaturas são obrigatórias.",
        "err_points": "Para gerar rota é preciso informar origem e destino.",
        "err_out": "Escolha onde salvar o resultado.",
        "err_weights": "Ao menos um peso precisa ser maior que zero.",
        "err_alt": "A altitude mínima precisa ser menor que a máxima.",
        "err_breaks": "Os limites de transitabilidade precisam ser quatro "
                      "números crescentes, separados por vírgula.",
        "done_title": "Pronto",
        "done_text": "{count} camada(s) carregada(s) no projeto.",
        "fail_title": "A execução falhou",
        "fail_text": "{error}\n\nRegistro técnico: {log_path}",
        "cancelled": "Execução cancelada.",
    },
    "en": {
        "window": "TopoTrail — trail and access planning",
        "steps": ["1. Data", "2. What you want", "3. Tuning", "4. Run"],
        "back": "◀ Back", "next": "Next ▶", "run": "Generate results",
        "cancel": "Cancel run",

        "s1_title": "What data do you have?",
        "s1_sub": "Only the digital elevation model is required. Slope and "
                  "curvatures are derived from it.",
        "dem": "Digital elevation model (DEM)",
        "dem_help": "An elevation raster in GeoTIFF. Any source works: "
                    "Copernicus, SRTM, ALOS, a national topographic sheet.",
        "vunit": "DEM vertical unit",
        "vunit_help": "Metres for nearly every product. Feet appear in some "
                      "United States datasets.",
        "own_rasters": "I already have slope and curvature rasters and want to use them",
        "own_help": "Tick only if you prefer your own rasters. Leaving it "
                    "unticked is recommended: deriving from the DEM removes "
                    "unit, sign-convention and grid-alignment problems.",
        "slope": "Slope", "curvh": "Plan curvature",
        "curvv": "Profile curvature", "sunit": "Slope unit",

        "s2_title": "What should the plugin produce?",
        "s2_sub": "Tick whatever is useful. The first two are always produced.",
        "always": "Always produced",
        "o_score": "Topographic suitability map",
        "o_score_help": "A 0-to-1 score per cell, combining the criteria chosen "
                        "in step 3.",
        "o_risk": "Relative topographic risk map",
        "o_risk_help": "The complement of suitability, to read directly where "
                       "the terrain is least favourable.",
        "o_zones": "Potential access zones (vector)",
        "o_zones_help": "Turns the best areas into polygons, for clipping and "
                        "area measurement.",
        "o_transit": "Transitability map — “where can I walk”",
        "o_transit_help": "Five slope classes with the legend written into the "
                          "file, so it opens already coloured in QGIS. The "
                          "labels describe steepness, not a verdict on the "
                          "walker: field teams routinely cross classes 4 and 5.",
        "o_streams": "Take watercourses into account, extracted from the DEM",
        "o_streams_help": "Derives the drainage network from the relief and uses "
                          "it as a route constraint — no hydrography layer "
                          "needed. Careful in dry landscapes: teams cross "
                          "drainage at twice the rate of chance, so avoiding it "
                          "tends to push the route away from what you want to "
                          "visit.",
        "o_route": "Route between points, and access corridor",
        "o_route_help": "Least-cost path from origin to destination, optionally "
                        "through intermediate destinations.",
        "route_box": "Route",
        "start": "Origin", "end": "Destination",
        "via": "Intermediate destinations, in visiting order (optional)",
        "via_help": "A point layer. Feature order is the order of the traverse: "
                    "draw Marins, Marinzinho and Itaguaré in that sequence and "
                    "the route climbs all three. Without it the algorithm skirts "
                    "the summits — correctly, because a summit is expensive.",
        "optimise": "Let the plugin choose the best visiting order",
        "optimise_help": "Solves the cheapest order exactly, up to eight "
                         "intermediate points. Ignores the layer order.",
        "pick": "Pick on map", "file": "File…",
        "cost": "How to measure the cost of the path",
        "cost_help": "“Walking time” uses Tobler's function: uphill costs more "
                     "than downhill, and the cost comes out in hours. It is the "
                     "model validated against field GPS, and the recommended one.",
        "corridor": "Corridor width (m)",
        "margin": "Lateral search margin (m)",
        "margin_help": "How far the algorithm may stray from the straight line "
                       "between the points. Too small forces a straight route; "
                       "too large makes the computation slow.",

        "s3_title": "Tuning",
        "s3_sub": "The defaults were calibrated against real trails. Changing "
                  "anything here is optional.",
        "w_box": "Weight of each criterion",
        "w_help": "How much each criterion counts towards the final score. Zero "
                  "switches it off. Altitude is zero on purpose: altitude bands "
                  "discard good terrain in mountainous regions.",
        "w_alt": "Altitude", "w_slope": "Slope",
        "w_curvh": "Plan curvature", "w_curvv": "Profile curvature",
        "w_wet": "Terrain wetness", "w_rough": "Ruggedness",
        "lim_box": "Terrain limits",
        "slope_max": "Maximum admissible slope (%)",
        "slope_max_help": "Above this a cell counts as unusable. 100% is 45 degrees.",
        "slope_score": "Slope scoring zero (%)",
        "slope_score_help": "Where the slope score reaches zero. If most of your "
                            "area exceeds this, the criterion stops telling one "
                            "hillside from another and the plugin warns you.",
        "alt_min": "Minimum altitude (m)", "alt_max": "Maximum altitude (m)",
        "zone_box": "How to cut the zones",
        "percentile": "Cut percentile",
        "percentile_help": "75 keeps the best quarter of the area. Lower is more "
                           "permissive.",
        "min_area": "Minimum patch area (ha)",
        "band": "Balance zones by altitude band",
        "band_size": "Band size (m)",
        "breaks": "Transitability class breaks (%)",
        "breaks_help": "Four increasing values separating the five classes.",
        "extra_box": "Additional criterion (optional)",
        "extra_layer": "Extra raster",
        "extra_help": "Any raster of yours can enter the model: stoniness, "
                      "vegetation cover, a ready-made cost surface.",
        "extra_weight": "Weight", "extra_dir": "High values are",
        "cons_box": "Constraints (optional)",
        "cons_layer": "Layer to avoid",
        "cons_help": "Features to keep away from: a fence, a closed area, "
                     "private land. Careful with hydrography: in dry landscapes "
                     "teams cross drainage at twice the rate of chance, so "
                     "penalising it tends to push the route away from what you "
                     "want to visit.",
        "cons_buffer": "Distance to keep (m)", "cons_mode": "Treatment",

        "s4_title": "Where to save, and run",
        "s4_sub": "The computation runs in the background; QGIS stays usable.",
        "out": "Output file", "fmt": "Vector format",
        "crs": "Output CRS (optional)",
        "crs_help": "Left blank, the project CRS is used.",
        "summary": "Summary of what will be produced",
        "log": "Progress",

        "err_title": "Something is missing",
        "err_dem": "Choose the digital elevation model to continue.",
        "err_dem_invalid": "I could not open this raster as a valid layer:\n{path}",
        "err_dem_crs": "This raster has no CRS defined:\n{path}\n\n"
                       "Set its coordinate system before using it.",
        "err_rasters": "You ticked that you will use your own rasters, so slope "
                       "and both curvatures are required.",
        "err_points": "A route needs both an origin and a destination.",
        "err_out": "Choose where to save the result.",
        "err_weights": "At least one weight must be greater than zero.",
        "err_alt": "Minimum altitude must be lower than maximum.",
        "err_breaks": "Transitability breaks must be four increasing numbers, "
                      "separated by commas.",
        "done_title": "Done",
        "done_text": "{count} layer(s) loaded into the project.",
        "fail_title": "The run failed",
        "fail_text": "{error}\n\nTechnical log: {log_path}",
        "cancelled": "Run cancelled.",
    },
}


# --------------------------------------------------------------------------
# Pequenos construtores, para que cada controle saia com a mesma aparencia
# --------------------------------------------------------------------------

MUTED = "#5a6472"
ACCENT = "#1f6feb"


def _help(text):
    """A frase que explica o controle. E o que torna a janela didatica, entao
    nao e opcional em nenhum campo que nao seja obvio."""
    label = QLabel(text)
    label.setWordWrap(True)
    font = label.font()
    font.setPointSizeF(max(font.pointSizeF() - 1.0, 7.5))
    label.setFont(font)
    label.setStyleSheet(f"color: {MUTED};")
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


def _card(title=None):
    """Um bloco visual. Agrupar reduz a impressao de painel de controle."""
    frame = QFrame()
    frame.setObjectName("ttCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(8)
    if title:
        layout.addWidget(_heading(title, size=12))
    return frame, layout


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
        self.button.setFixedWidth(38)
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
        for index, (label, widget) in enumerate(rows):
            text = QLabel(label)
            text.setWordWrap(True)
            grid.addWidget(text, index, 0)
            grid.addWidget(widget, index, 1)
        grid.setColumnStretch(0, 1)
        holder = QWidget()
        holder.setLayout(grid)
        self.layout_.addWidget(holder)
        return holder


class TopotrailDialog(QDialog, TopotrailSupportMixin):
    """Assistente de quatro passos."""

    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.lang = "pt"
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
        return TEXTS[self.lang].get(key, TEXTS["pt"].get(key, key))

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
        for widget, key, attribute in self._labels:
            getattr(widget, attribute)(self.t(key))
        for index, name in enumerate(self.t("steps")):
            self.step_labels[index].setText(name)
        self.back_button.setText(self.t("back"))
        self._update_nav()
        self._fill_enums()

    def _toggle_language(self):
        self.lang = "en" if self.lang == "pt" else "pt"
        self._retranslate()

    # -- construcao ---------------------------------------------------------
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())
        outer.addWidget(self._build_steps_bar())

        self.stack = QStackedWidget()
        for builder in (self._step_data, self._step_outputs,
                        self._step_tuning, self._step_run):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(24, 18, 24, 12)
            layout.setSpacing(12)
            builder(layout)
            layout.addStretch(1)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
        self.stack.currentChanged.connect(lambda _index: self._update_nav())
        outer.addWidget(self.stack, 1)
        outer.addWidget(self._build_footer())

    def _build_header(self):
        header = QFrame()
        header.setObjectName("ttHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 12, 20, 12)
        logo_path = os.path.join(PLUGIN_DIR, "logo.png")
        if os.path.exists(logo_path):
            logo = QLabel()
            logo.setPixmap(QPixmap(logo_path).scaledToHeight(
                42, qt_enum("TransformationMode", "SmoothTransformation")))
            layout.addWidget(logo)
        title = _heading("TopoTrail", size=17)
        layout.addWidget(title)
        layout.addStretch(1)
        self.language_button = QPushButton("PT-BR | ENG")
        self.language_button.setMinimumWidth(
            self.language_button.fontMetrics().horizontalAdvance("PT-BR | ENG") + 34)
        self.language_button.clicked.connect(self._toggle_language)
        layout.addWidget(self.language_button)
        return header

    def _build_steps_bar(self):
        bar = QFrame()
        bar.setObjectName("ttSteps")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 8, 20, 8)
        layout.setSpacing(6)
        self.step_labels = []
        for index in range(4):
            label = QLabel()
            label.setAlignment(qt_enum("AlignmentFlag", "AlignCenter"))
            label.setObjectName("ttStep")
            label.setCursor(qt_enum("CursorShape", "PointingHandCursor"))
            label.mousePressEvent = (
                lambda event, target=index: self._jump_to(target))
            self.step_labels.append(label)
            layout.addWidget(label, 1)
        return bar

    def _build_footer(self):
        footer = QFrame()
        footer.setObjectName("ttFooter")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(20, 10, 20, 12)
        self.back_button = QPushButton()
        self.back_button.clicked.connect(lambda: self._go(-1))
        layout.addWidget(self.back_button)
        layout.addStretch(1)
        self.next_button = QPushButton()
        self.next_button.setObjectName("ttPrimary")
        self.next_button.setMinimumWidth(220)
        self.next_button.clicked.connect(self._next_clicked)
        layout.addWidget(self.next_button)
        return footer

    # -- passo 1: dados -----------------------------------------------------
    def _step_data(self, layout):
        layout.addWidget(self._bind(_heading(""), "s1_title"))
        layout.addWidget(self._help_label("s1_sub"))

        card, inner = _card()
        inner.addWidget(self._label("dem"))
        self.dem_file = _FileRow("GeoTIFF (*.tif *.tiff);;Todos (*)", "MDE")
        inner.addWidget(self.dem_file)
        inner.addWidget(self._help_label("dem_help"))

        row = QHBoxLayout()
        row.addWidget(self._label("vunit"))
        self.vertical_unit = QComboBox()
        row.addWidget(self.vertical_unit)
        row.addStretch(1)
        inner.addLayout(row)
        inner.addWidget(self._help_label("vunit_help"))
        layout.addWidget(card)

        self.own_rasters = self._check("own_rasters")
        layout.addWidget(self.own_rasters)
        layout.addWidget(self._help_label("own_help"))

        self.own_section = _Section()
        self.slope_file = _FileRow("GeoTIFF (*.tif *.tiff)", "Declividade")
        self.curvh_file = _FileRow("GeoTIFF (*.tif *.tiff)", "Curvatura H")
        self.curvv_file = _FileRow("GeoTIFF (*.tif *.tiff)", "Curvatura V")
        self.slope_unit = QComboBox()
        self.own_section.add_form([
            (self.t("slope"), self.slope_file),
            (self.t("sunit"), self.slope_unit),
            (self.t("curvh"), self.curvh_file),
            (self.t("curvv"), self.curvv_file),
        ])
        self.own_rasters.toggled.connect(self.own_section.setVisible)
        layout.addWidget(self.own_section)

    # -- passo 2: saidas ----------------------------------------------------
    def _step_outputs(self, layout):
        layout.addWidget(self._bind(_heading(""), "s2_title"))
        layout.addWidget(self._help_label("s2_sub"))

        card, inner = _card()
        inner.addWidget(self._bind(_heading(""), "always"))
        for key, help_key in (("o_score", "o_score_help"), ("o_risk", "o_risk_help")):
            check = self._check(key)
            check.setChecked(True)
            check.setEnabled(False)
            inner.addWidget(check)
            inner.addWidget(self._help_label(help_key))
        layout.addWidget(card)

        card, inner = _card()
        self.want_zones = self._check("o_zones")
        self.want_zones.setChecked(True)
        inner.addWidget(self.want_zones)
        inner.addWidget(self._help_label("o_zones_help"))

        self.want_transit = self._check("o_transit")
        self.want_transit.setChecked(True)
        inner.addWidget(self.want_transit)
        inner.addWidget(self._help_label("o_transit_help"))

        self.want_streams = self._check("o_streams")
        inner.addWidget(self.want_streams)
        inner.addWidget(self._help_label("o_streams_help"))
        layout.addWidget(card)

        card, inner = _card()
        self.want_route = self._check("o_route")
        inner.addWidget(self.want_route)
        inner.addWidget(self._help_label("o_route_help"))

        self.route_section = _Section()
        self.start_file = _FileRow("Vetores (*.gpkg *.shp *.kml *.geojson)", "Origem")
        self.end_file = _FileRow("Vetores (*.gpkg *.shp *.kml *.geojson)", "Destino")
        self.via_file = _FileRow("Vetores (*.gpkg *.shp *.kml *.geojson)", "Waypoints")
        self.start_coord = QLineEdit(); self.start_coord.setPlaceholderText("X, Y")
        self.end_coord = QLineEdit(); self.end_coord.setPlaceholderText("X, Y")
        self.pick_start = QPushButton(); self.pick_end = QPushButton()
        self._bind(self.pick_start, "pick"); self._bind(self.pick_end, "pick")
        self.pick_start.clicked.connect(lambda: self.start_map_pick("start"))
        self.pick_end.clicked.connect(lambda: self.start_map_pick("end"))

        def point_row(file_row, coord, button):
            holder = QWidget(); box = QHBoxLayout(holder)
            box.setContentsMargins(0, 0, 0, 0); box.setSpacing(6)
            box.addWidget(file_row, 2); box.addWidget(coord, 1); box.addWidget(button, 0)
            return holder

        self.route_section.add_form([
            (self.t("start"), point_row(self.start_file, self.start_coord, self.pick_start)),
            (self.t("end"), point_row(self.end_file, self.end_coord, self.pick_end)),
        ])
        self.route_section.add(self._label("via"))
        self.route_section.add(self.via_file)
        self.route_section.add(self._help_label("via_help"))
        self.optimise_order = self._check("optimise")
        self.route_section.add(self.optimise_order)
        self.route_section.add(self._help_label("optimise_help"))

        self.cost_model = QComboBox()
        self.corridor_m = _spin(1, 100000, 100.0, 0, 10, " m")
        self.margin_m = _spin(1, 200000, 5000.0, 0, 100, " m")
        self.route_section.add(self._label("cost"))
        self.route_section.add(self.cost_model)
        self.route_section.add(self._help_label("cost_help"))
        self.route_section.add_form([
            (self.t("corridor"), self.corridor_m),
            (self.t("margin"), self.margin_m),
        ])
        self.route_section.add(self._help_label("margin_help"))
        self.want_route.toggled.connect(self.route_section.setVisible)
        inner.addWidget(self.route_section)
        layout.addWidget(card)

    # -- passo 3: ajustes ---------------------------------------------------
    def _step_tuning(self, layout):
        layout.addWidget(self._bind(_heading(""), "s3_title"))
        layout.addWidget(self._help_label("s3_sub"))

        card, inner = _card()
        inner.addWidget(self._bind(_heading(""), "w_box"))
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

        card, inner = _card()
        inner.addWidget(self._bind(_heading(""), "lim_box"))
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

        card, inner = _card()
        inner.addWidget(self._bind(_heading(""), "zone_box"))
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

        card, inner = _card()
        inner.addWidget(self._bind(_heading(""), "extra_box"))
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

        card, inner = _card()
        inner.addWidget(self._bind(_heading(""), "cons_box"))
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
        layout.addWidget(self._bind(_heading(""), "s4_title"))
        layout.addWidget(self._help_label("s4_sub"))

        card, inner = _card()
        inner.addWidget(self._label("out"))
        row = QHBoxLayout()
        self.output_edit = QLineEdit()
        button = QPushButton("…"); button.setFixedWidth(38)
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

        card, inner = _card()
        inner.addWidget(self._bind(_heading(""), "summary"))
        self.summary_label = _help("")
        self.summary_label.setSizePolicy(size_policy("Preferred"), size_policy("Expanding"))
        self.summary_label.setMinimumHeight(96)
        self.summary_label.setAlignment(qt_enum("AlignmentFlag", "AlignTop"))
        inner.addWidget(self.summary_label)
        layout.addWidget(card)

        card, inner = _card()
        inner.addWidget(self._bind(_heading(""), "log"))
        self.progress = QProgressBar()
        self.progress.setValue(0)
        inner.addWidget(self.progress)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(150)
        inner.addWidget(self.log_view)
        layout.addWidget(card)

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("out"), "", "GeoPackage (*.gpkg);;Shapefile (*.shp)")
        if path:
            self.output_edit.setText(path)

    # -- enums e tema -------------------------------------------------------
    def _fill_enums(self):
        pt = self.lang == "pt"
        def fill(box, options):
            current = box.currentIndex()
            box.clear()
            box.addItems(options)
            box.setCurrentIndex(max(current, 0))
        fill(self.vertical_unit, ["Metros", "Pés"] if pt else ["Metres", "Feet"])
        fill(self.slope_unit, ["Porcentagem (%)", "Graus"] if pt
             else ["Percent (%)", "Degrees"])
        fill(self.cost_model,
             ["Inverso da adequabilidade (legado)",
              "Exponencial — contraste ajustável",
              "Tempo de caminhada (Tobler) — recomendado"] if pt else
             ["Inverse of suitability (legacy)",
              "Exponential — adjustable contrast",
              "Walking time (Tobler) — recommended"])
        if self.cost_model.currentIndex() == 0:
            self.cost_model.setCurrentIndex(2)
        fill(self.extra_direction,
             ["Ruins (menor é melhor)", "Bons (maior é melhor)"] if pt else
             ["Bad (lower is better)", "Good (higher is better)"])
        fill(self.constraint_mode,
             ["Evitar completamente", "Apenas encarecer"] if pt else
             ["Avoid completely", "Only make expensive"])
        # A ordem precisa bater exatamente com options= do algoritmo. Quando nao
        # batia, escolher "GeoPackage" produzia um Shapefile em silencio.
        fill(self.output_format, ["Shapefile", "GeoPackage", "KML"])
        if not self._format_initialised:
            self.output_format.setCurrentIndex(1)      # GeoPackage
            self._format_initialised = True

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QDialog {{ background: palette(window); }}
            #ttHeader {{ background: palette(base); border-bottom: 1px solid #d4d9e0; }}
            #ttSteps {{ background: palette(base); border-bottom: 1px solid #d4d9e0; }}
            #ttFooter {{ background: palette(base); border-top: 1px solid #d4d9e0; }}
            #ttCard {{ background: palette(base); border: 1px solid #d9dee5;
                       border-radius: 8px; }}
            #ttStep {{ padding: 6px 4px; border-radius: 6px; color: {MUTED}; }}
            #ttStep[active="true"] {{ background: {ACCENT}; color: white;
                                      font-weight: bold; }}
            #ttPrimary {{ background: {ACCENT}; color: white; font-weight: bold;
                          padding: 9px 18px; border: none; border-radius: 6px; }}
            #ttPrimary:disabled {{ background: #9db6dd; }}
            QPushButton {{ padding: 6px 12px; }}
        """)

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
            self.next_button.setText(self.t("run") if last else self.t("next"))
        for position, label in enumerate(self.step_labels):
            label.setProperty("active", "true" if position == index else "false")
            label.style().unpolish(label); label.style().polish(label)
        if last:
            self._refresh_summary()

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
