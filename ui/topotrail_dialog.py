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

from . import icons
from .support import (
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
# Mantidos num dicionario e nao em .ts porque o plugin precisa alternar idioma
# em tempo de execucao, com o botao PT-BR | ENG, e nao apenas no idioma do QGIS:
# equipes de campo brasileiras costumam rodar o QGIS em ingles e querer a
# ferramenta em portugues.

TEXTS = {
    "pt": {
        "window": "TopoTrail — planejamento de trilhas e acessos",
        "steps": ["Dados", "O que você quer", "Ajustes", "Executar"],
        "about": "Sobre",
        "status_title": "SELEÇÃO ATUAL",
        "status_no_dem": "Nenhum MDE escolhido",
        "status_no_output": "Sem arquivo de saída",
        "status_outputs_n": "{n} saídas marcadas",
        "about_text": (
            "<h3 style='margin-bottom:2px'>TopoTrail</h3>"
            "<p style='color:#6b7a74;margin-top:0'>Versão {version}</p>"
            "<p>Ferramenta de apoio ao planejamento de trilhas, acessos e "
            "deslocamentos de campo em áreas naturais e unidades de "
            "conservação, integrando altitude, declividade, curvaturas do "
            "relevo, umidade e rugosidade por análise multicritério em SIG, "
            "com rota de menor custo e tempo de caminhada.</p>"
            "<p><b>Desenvolvimento:</b> Luan da Silva Cortes Maciel "
            "(MACIEL, L. S. C.)<br>"
            "<b>Orientação:</b> Leandro Freitas<br>"
            "<b>Projeto associado:</b> Herpeto Mantiqueira</p>"
            "<p><b>Contexto:</b> desenvolvido como produto da pesquisa de "
            "mestrado em Biodiversidade em Unidades de Conservação, Escola "
            "Nacional de Botânica Tropical / Instituto de Pesquisas Jardim "
            "Botânico do Rio de Janeiro.</p>"
            "<p style='color:#6b7a74'>Os resultados são evidência de apoio à "
            "decisão e exigem validação em campo.</p>"
            "<p>Licença MIT · plugins.qgis.org/plugins/TopoTrail</p>"),
        "back": "◀ Voltar", "next": "Avançar ▶", "run": "Gerar resultados",
        "cancel": "Cancelar execução",

        "s1_title": "De que dados você dispõe?",
        "s1_sub": "Só o modelo digital de elevação é obrigatório. Declividade e "
                  "curvaturas são calculadas a partir dele.",
        "dem": "Arquivo do MDE",
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
        "always": "SEMPRE GERADOS",
        "optional_group": "OPCIONAIS — MARQUE O QUE PRECISAR",
        "o_transit_tip": "Os rótulos descrevem inclinação, não um veredito sobre "
                         "quem passa: em trilhas reais percorridas a pé, equipes "
                         "de campo cruzam rotineiramente as classes 4 e 5.\n\n"
                         "A distribuição das classes depende fortemente da "
                         "resolução do MDE — informe o tamanho da célula ao lado "
                         "de qualquer número tirado deste mapa.",
        "o_streams_tip": "Não precisa de camada de hidrografia. Cuidado em "
                         "paisagem sazonalmente seca: o leito seco costuma ser a "
                         "melhor superfície de caminhada, e em levantamento "
                         "biológico a drenagem é alvo de amostragem — evitá-la "
                         "pode afastar a rota do que você quer visitar.",
        "o_route_tip": "Use os destinos intermediários para encadear objetivos: "
                       "subir um cume, depois outro, passar por um ponto de "
                       "coleta, então descer.",
        "dem_card": "Modelo digital de elevação",
        "own_card": "Rasters próprios",
        "out_box": "Destino do resultado",
        "o_score": "Mapa de adequabilidade topográfica",
        "o_score_help": "Nota de 0 a 1 por célula, combinando os critérios "
                        "escolhidos no passo 3.",
        "o_risk": "Mapa de risco topográfico relativo",
        "o_risk_help": "O complemento da adequabilidade, para ler direto onde "
                       "o terreno é mais desfavorável.",
        "o_zones": "Zonas de acesso potencial (vetor)",
        "o_zones_help": "As melhores áreas como polígonos, para recorte e "
                        "medida de área.",
        "o_transit": "Mapa de transitabilidade — “onde dá para andar”",
        "o_transit_help": "Cinco classes de declividade, com a legenda gravada no arquivo.",
        "o_streams": "Levar cursos d'água em conta, extraídos do próprio MDE",
        "o_streams_help": "Deriva a drenagem do relevo e a usa como restrição da rota.",
        "o_route": "Rota entre pontos e corredor de acesso",
        "o_route_help": "Caminho de menor custo entre a origem e o destino, "
                        "passando por onde você quiser.",
        "route_box": "Rota",
        "start": "Origem", "end": "Destino",
        "via": "Destinos intermediários, na ordem de visita (opcional)",
        "via_help": "Uma camada de pontos: a ordem das feições é a ordem da "
                    "travessia. Sem ela o algoritmo contorna os pontos altos — "
                    "e com razão, o cume é o lugar caro.",
        "optimise": "Deixar o plugin escolher a melhor ordem de visita",
        "optimise_help": "Ordem exata de menor custo, até oito pontos.",
        "pick": "Marcar no mapa", "file": "Arquivo…",
        "cost": "Como medir o custo do caminho",
        "cost_help": "Tobler: subir custa mais que descer e o custo sai em "
                     "horas. É o modelo validado contra GPS de campo.",
        "corridor": "Largura do corredor (m)",
        "margin": "Margem lateral de busca (m)",
        "margin_help": "Quanto a rota pode se afastar da linha reta. Pequena "
                       "demais força uma reta; grande demais deixa lento.",

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
                     "privada, zona de exclusão. Vale para qualquer restrição "
                     "que exista no seu contexto — a camada é sua.",
        "cons_buffer": "Distância a manter (m)", "cons_mode": "Tratamento",

        "s4_title": "Onde salvar e executar",
        "s4_sub": "O cálculo roda em segundo plano; o QGIS continua utilizável.",
        "out": "Arquivo de saída", "fmt": "Formato do vetor",
        "crs": "CRS de saída (opcional)",
        "crs_help": "Em branco, usa o CRS do projeto.",
        "summary": "Resumo do que será gerado",
        "log": "Andamento",
        "log_empty": "As mensagens do cálculo aparecem aqui durante a execução.",

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
        "steps": ["Data", "What you want", "Tuning", "Run"],
        "about": "About",
        "status_title": "CURRENT SELECTION",
        "status_no_dem": "No DEM chosen",
        "status_no_output": "No output file",
        "status_outputs_n": "{n} outputs ticked",
        "about_text": (
            "<h3 style='margin-bottom:2px'>TopoTrail</h3>"
            "<p style='color:#6b7a74;margin-top:0'>Version {version}</p>"
            "<p>A tool supporting the planning of trails, access routes and "
            "field movement in natural and protected areas, combining "
            "elevation, slope, relief curvature, wetness and ruggedness by "
            "GIS multicriteria analysis, with least-cost routing and walking "
            "time.</p>"
            "<p><b>Development:</b> Luan da Silva Cortes Maciel "
            "(MACIEL, L. S. C.)<br>"
            "<b>Supervision:</b> Leandro Freitas<br>"
            "<b>Associated project:</b> Herpeto Mantiqueira</p>"
            "<p><b>Context:</b> developed as a product of master's research in "
            "Biodiversity in Protected Areas, Escola Nacional de Botânica "
            "Tropical / Rio de Janeiro Botanical Garden Research Institute.</p>"
            "<p style='color:#6b7a74'>Results are decision-support evidence and "
            "require field validation.</p>"
            "<p>MIT licence · plugins.qgis.org/plugins/TopoTrail</p>"),
        "back": "◀ Back", "next": "Next ▶", "run": "Generate results",
        "cancel": "Cancel run",

        "s1_title": "What data do you have?",
        "s1_sub": "Only the digital elevation model is required. Slope and "
                  "curvatures are derived from it.",
        "dem": "DEM file",
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
        "always": "ALWAYS PRODUCED",
        "optional_group": "OPTIONAL — TICK WHAT YOU NEED",
        "o_transit_tip": "The labels describe steepness, not a verdict on the "
                         "walker: on real walked trails, field teams routinely "
                         "cross classes 4 and 5.\n\nThe class distribution "
                         "depends strongly on DEM resolution — quote the cell "
                         "size beside any number taken from this map.",
        "o_streams_tip": "No hydrography layer needed. Careful in seasonally dry "
                         "landscapes: a dry bed is often the best walking "
                         "surface, and in biological survey work drainage is a "
                         "sampling target — avoiding it can push the route away "
                         "from what you want to visit.",
        "o_route_tip": "Use intermediate destinations to chain objectives: climb "
                       "one summit, then another, call at a sampling point, then "
                       "descend.",
        "dem_card": "Digital elevation model",
        "own_card": "Your own rasters",
        "out_box": "Where the result goes",
        "o_score": "Topographic suitability map",
        "o_score_help": "A 0-to-1 score per cell, combining the criteria from step 3.",
        "o_risk": "Relative topographic risk map",
        "o_risk_help": "The complement of suitability, to read directly where "
                       "the terrain is least favourable.",
        "o_zones": "Potential access zones (vector)",
        "o_zones_help": "The best areas as polygons, for clipping and area measurement.",
        "o_transit": "Transitability map — “where can I walk”",
        "o_transit_help": "Five slope classes, with the legend written into the file.",
        "o_streams": "Take watercourses into account, extracted from the DEM",
        "o_streams_help": "Derives drainage from the relief and uses it as a route constraint.",
        "o_route": "Route between points, and access corridor",
        "o_route_help": "Least-cost path from origin to destination, calling "
                        "wherever you want on the way.",
        "route_box": "Route",
        "start": "Origin", "end": "Destination",
        "via": "Intermediate destinations, in visiting order (optional)",
        "via_help": "A point layer: feature order is the order of the traverse. "
                    "Without it the algorithm skirts the high ground — rightly, "
                    "since a summit is the expensive place.",
        "optimise": "Let the plugin choose the best visiting order",
        "optimise_help": "Exact cheapest order, up to eight points.",
        "pick": "Pick on map", "file": "File…",
        "cost": "How to measure the cost of the path",
        "cost_help": "Tobler: uphill costs more than downhill and the cost "
                     "comes out in hours. Validated against field GPS.",
        "corridor": "Corridor width (m)",
        "margin": "Lateral search margin (m)",
        "margin_help": "How far the route may stray from the straight line. "
                       "Too small forces a straight route; too large is slow.",

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
                     "private land, an exclusion zone. Anything that constrains "
                     "movement where you work — the layer is yours.",
        "cons_buffer": "Distance to keep (m)", "cons_mode": "Treatment",

        "s4_title": "Where to save, and run",
        "s4_sub": "The computation runs in the background; QGIS stays usable.",
        "out": "Output file", "fmt": "Vector format",
        "crs": "Output CRS (optional)",
        "crs_help": "Left blank, the project CRS is used.",
        "summary": "Summary of what will be produced",
        "log": "Progress",
        "log_empty": "Messages from the computation appear here while it runs.",

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

# Paleta tirada da logo do plugin: o verde-floresta #0d452c e a cor dominante
# dela. Uma ferramenta de campo em unidade de conservacao nao tem por que usar
# o azul generico de painel de controle.
INK = "#1a2420"
MUTED = "#6b7a74"
FOREST = "#0d452c"
ACCENT = "#17805a"
ACCENT_SOFT = "#e8f3ee"
CANVAS = "#f4f6f5"
LINE = "#e2e8e5"


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


class _StepTrack(QFrame):
    """Desenha o fio vertical que liga os marcadores dos passos.

    Feito com paintEvent e não com um QFrame de 2 px entre as linhas porque o
    fio precisa passar por trás dos marcadores e acompanhar a posição real
    deles, que muda com a fonte e o DPI do sistema.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ttStepTrack")
        self._badges = []

    def set_rows(self, badges):
        self._badges = badges

    def paintEvent(self, event):
        super().paintEvent(event)
        if len(self._badges) < 2:
            return
        from qgis.PyQt.QtGui import QPainter, QPen, QColor
        first, last = self._badges[0], self._badges[-1]
        top = first.mapTo(self, first.rect().center())
        bottom = last.mapTo(self, last.rect().center())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(255, 255, 255, 38))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(top.x(), top.y(), bottom.x(), bottom.y())
        painter.end()


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
            self.setCursor(Qt.PointingHandCursor)

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
        self.tick.setFixedSize(22, 22)
        layout.addWidget(self.tick, 0, qt_enum("AlignmentFlag", "AlignTop"))

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
            self.glyph, 24, ACCENT if value else MUTED, 1.85))
        self.tick.setPixmap(icons.pixmap("check", 22, ACCENT, 1.9)
                            if value else QPixmap())
        self.style().unpolish(self); self.style().polish(self)
        for callback in self._callbacks:
            callback(value)

    def toggled(self, callback):
        self._callbacks.append(callback)

    def lock_checked(self):
        """Saída obrigatória: marcada, sem interação, e visivelmente assim."""
        self._checked = True
        self._enabled = False
        self.setProperty("checked", "false")
        self.setProperty("locked", "true")
        self.icon_label.setPixmap(icons.pixmap(self.glyph, 24, "#9ab0a6", 1.85))
        self.tick.setPixmap(icons.pixmap("check", 22, "#9ac7b3", 1.9))

    def mousePressEvent(self, event):
        if self._enabled:
            self.setChecked(not self._checked)


def _card(title=None, glyph=None):
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
        self.version_label.setText(f"v{_plugin_version()}")
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
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_sidebar())

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.stack = QStackedWidget()
        for builder in (self._step_data, self._step_outputs,
                        self._step_tuning, self._step_run):
            page = QWidget()
            page.setObjectName("ttPage")
            layout = QVBoxLayout(page)
            layout.setContentsMargins(38, 34, 38, 26)
            layout.setSpacing(16)
            builder(layout)
            layout.addStretch(1)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
        self.stack.currentChanged.connect(lambda _index: self._update_nav())
        right_layout.addWidget(self.stack, 1)
        right_layout.addWidget(self._build_footer())
        outer.addWidget(right, 1)

    def _build_sidebar(self):
        """Barra lateral: marca, progresso, estado atual e crédito institucional.

        A primeira versão errava três coisas. A logo aparecia a 32 px ao lado de
        um rótulo de texto "TopoTrail" -- mas a logo *é* um lockup que já contém
        a palavra, então o nome saía duplicado e ilegível nos dois lugares. A
        linha de apoio era um parágrafo de 11 px em três linhas, que se lê como
        letra miúda. E sobravam 250 px de vazio entre os passos e o rodapé.

        Aqui a marca aparece uma vez, no tamanho em que se lê; e o vazio virou
        um painel de estado que responde à pergunta "o que já está escolhido?"
        sem obrigar a voltar passo a passo.
        """
        side = QFrame()
        side.setObjectName("ttSide")
        side.setFixedWidth(272)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(20, 20, 20, 18)
        layout.setSpacing(0)

        logo_path = os.path.join(PLUGIN_DIR, "logo.png")
        if os.path.exists(logo_path):
            plate = QFrame()
            plate.setObjectName("ttPlate")
            plate_layout = QVBoxLayout(plate)
            plate_layout.setContentsMargins(16, 14, 16, 14)
            mark = QLabel()
            mark.setAlignment(qt_enum("AlignmentFlag", "AlignCenter"))
            mark.setPixmap(QPixmap(logo_path).scaledToWidth(
                122, qt_enum("TransformationMode", "SmoothTransformation")))
            plate_layout.addWidget(mark)
            layout.addWidget(plate)
        else:
            name = QLabel("TopoTrail")
            name.setObjectName("ttBrand")
            layout.addWidget(name)

        self.version_label = QLabel()
        self.version_label.setObjectName("ttVersion")
        self.version_label.setAlignment(qt_enum("AlignmentFlag", "AlignCenter"))
        layout.addSpacing(9)
        layout.addWidget(self.version_label)
        layout.addSpacing(22)

        layout.addWidget(self._build_steps())
        layout.addSpacing(18)
        layout.addWidget(self._build_status())
        layout.addStretch(1)

        credit = QFrame()
        credit.setObjectName("ttCredit")
        credit_layout = QVBoxLayout(credit)
        credit_layout.setContentsMargins(12, 14, 12, 14)
        logos = QHBoxLayout()
        logos.setSpacing(11)
        logos.addStretch(1)
        # Alturas diferentes de proposito: as tres logos tem proporcoes muito
        # distintas -- uma circular, duas verticais -- e igualar a altura faria a
        # circular dominar. Estas alturas equilibram a area ocupada por cada uma.
        for filename, height in (("logo_herpeto_mantiqueira.png", 62),
                                 ("logo_enbt.jpg", 56), ("logo_jbrj.jpg", 62)):
            path = os.path.join(PLUGIN_DIR, "assets", filename)
            if not os.path.exists(path):
                continue
            mark = QLabel()
            mark.setPixmap(QPixmap(path).scaledToHeight(
                height, qt_enum("TransformationMode", "SmoothTransformation")))
            logos.addWidget(mark)
        logos.addStretch(1)
        credit_layout.addLayout(logos)
        layout.addWidget(credit)
        layout.addSpacing(12)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.about_button = QPushButton()
        self.about_button.setObjectName("ttSideLink")
        self.about_button.setCursor(qt_enum("CursorShape", "PointingHandCursor"))
        self.about_button.clicked.connect(self._show_about)
        self._bind(self.about_button, "about")
        self.language_button = QPushButton("PT-BR | ENG")
        self.language_button.setObjectName("ttSideLink")
        self.language_button.setCursor(qt_enum("CursorShape", "PointingHandCursor"))
        self.language_button.clicked.connect(self._toggle_language)
        row.addWidget(self.about_button, 3)
        row.addWidget(self.language_button, 2)
        holder = QWidget(); holder.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(holder)
        return side

    def _build_steps(self):
        """Os quatro passos, com o fio que liga os marcadores.

        O fio não é enfeite: é o que transforma quatro linhas soltas numa
        sequência com começo e fim, e mostra de relance quanto falta.
        """
        block = _StepTrack()
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.step_labels = []
        self._step_rows = []
        for index in range(4):
            row = QFrame()
            row.setObjectName("ttStepRow")
            row.setProperty("active", "false")
            row.setCursor(qt_enum("CursorShape", "PointingHandCursor"))
            row.mousePressEvent = lambda event, target=index: self._jump_to(target)
            inner = QHBoxLayout(row)
            inner.setContentsMargins(10, 11, 12, 11)
            inner.setSpacing(13)
            badge = QLabel(str(index + 1))
            badge.setObjectName("ttBadge")
            badge.setFixedSize(28, 28)
            badge.setAlignment(qt_enum("AlignmentFlag", "AlignCenter"))
            label = QLabel()
            label.setObjectName("ttStepText")
            inner.addWidget(badge)
            inner.addWidget(label, 1)
            self.step_labels.append(label)
            self._step_rows.append((row, badge))
            layout.addWidget(row)
        block.set_rows([badge for _row, badge in self._step_rows])
        return block

    def _build_status(self):
        """Painel de estado: o que já foi escolhido, sem voltar passo a passo."""
        panel = QFrame()
        panel.setObjectName("ttStatus")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 13, 14, 13)
        layout.setSpacing(9)
        title = QLabel()
        title.setObjectName("ttStatusTitle")
        self._bind(title, "status_title")
        layout.addWidget(title)
        self.status_rows = {}
        for key, glyph in (("status_dem", "mountain"),
                           ("status_outputs", "layers"),
                           ("status_output_file", "save")):
            row = QHBoxLayout()
            row.setSpacing(9)
            row.addWidget(_icon(glyph, 15, "#7fa694", 1.8), 0,
                          qt_enum("AlignmentFlag", "AlignTop"))
            value = QLabel("—")
            value.setObjectName("ttStatusValue")
            value.setMinimumWidth(1)
            row.addWidget(value, 1)
            holder = QWidget(); holder.setLayout(row)
            row.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(holder)
            self.status_rows[key] = value
        return panel

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

    def _page_head(self, layout, glyph, title_key, subtitle_key):
        row = QHBoxLayout()
        row.setSpacing(13)
        row.addWidget(_icon(glyph, 27, ACCENT, 2.0), 0,
                      qt_enum("AlignmentFlag", "AlignTop"))
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
        row.setContentsMargins(0, 0, 0, 6)
        layout.addWidget(holder)

    # -- passo 1: dados -----------------------------------------------------
    def _step_data(self, layout):
        self._page_head(layout, "mountain", "s1_title", "s1_sub")

        card, inner = _card(self.t("dem_card"), "mountain")
        self._bind(card._title_label, "dem_card")
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
        self.own_section.add_form([
            (self.t("slope"), self.slope_file),
            (self.t("sunit"), self.slope_unit),
            (self.t("curvh"), self.curvh_file),
            (self.t("curvv"), self.curvv_file),
        ])
        self.own_rasters.toggled.connect(self.own_section.setVisible)
        inner.addWidget(self.own_section)
        layout.addWidget(card)

    # -- passo 2: saidas ----------------------------------------------------
    def _option(self, glyph, title_key, help_key, checked=False, locked=False):
        card = OptionCard(glyph, enabled=not locked)
        self._bind(card.title, title_key)
        self._bind(card.description, help_key)
        if locked:
            card.lock_checked()
        elif checked:
            card.setChecked(True)
        return card

    def _step_outputs(self, layout):
        self._page_head(layout, "layers", "s2_title", "s2_sub")

        band = QLabel()
        band.setObjectName("ttGroupLabel")
        self._bind(band, "always")
        layout.addWidget(band)
        layout.addWidget(self._option("grid", "o_score", "o_score_help", locked=True))
        layout.addWidget(self._option("alert", "o_risk", "o_risk_help", locked=True))

        band = QLabel()
        band.setObjectName("ttGroupLabel")
        self._bind(band, "optional_group")
        layout.addSpacing(4)
        layout.addWidget(band)

        self.want_zones = self._option("polygon", "o_zones", "o_zones_help", checked=True)
        self.want_transit = self._option("boot", "o_transit", "o_transit_help", checked=True)
        self.want_streams = self._option("drop", "o_streams", "o_streams_help")
        for card in (self.want_zones, self.want_transit, self.want_streams):
            layout.addWidget(card)

        self.want_route = self._option("route", "o_route", "o_route_help")
        layout.addWidget(self.want_route)
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
            label.setFixedWidth(64)
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

    # -- passo 3: ajustes ---------------------------------------------------
    def _step_tuning(self, layout):
        self._page_head(layout, "sliders", "s3_title", "s3_sub")

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
        self._page_head(layout, "play", "s4_title", "s4_sub")

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
            QDialog {{ background: {CANVAS}; }}
            QLabel {{ color: {INK}; }}

            /* Lateral: verde-floresta da propria logo. */
            #ttSide {{ background: {FOREST}; }}
            #ttBrand {{ color: #ffffff; font-size: 21px; font-weight: 600; }}
            #ttPlate {{ background: #ffffff; border-radius: 14px; }}
            #ttVersion {{ color: #7fa694; font-size: 11px; letter-spacing: 0.6px; }}
            #ttStepTrack {{ background: transparent; }}
            #ttStatus {{ background: rgba(255,255,255,0.07); border-radius: 11px; }}
            #ttStatusTitle {{ color: #7fa694; font-size: 9.5px; font-weight: 700;
                              letter-spacing: 1.1px; }}
            #ttStatusValue {{ color: #cfe3d8; font-size: 11.5px; }}
            #ttSideLink {{ background: rgba(255,255,255,0.07); border: none;
                           color: #b9d5c7; font-size: 11.5px; padding: 9px 6px;
                           border-radius: 8px; }}
            #ttSideLink:hover {{ background: rgba(255,255,255,0.15);
                                 color: #ffffff; }}

            #ttStepRow {{ border-radius: 8px; background: transparent; }}
            #ttStepRow[active="true"] {{ background: rgba(255,255,255,0.13); }}
            #ttStepText {{ color: #9dc4b1; font-size: 13.5px; }}
            #ttStepText[active="true"] {{ color: #ffffff; font-weight: 600; }}
            #ttStepText[active="done"] {{ color: #cfe3d8; }}
            #ttBadge {{ border-radius: 14px; font-size: 12px; font-weight: 700;
                        background: {FOREST}; color: #8fb5a3;
                        border: 2px solid rgba(255,255,255,0.16); }}
            #ttBadge[active="true"] {{ background: #ffffff; color: {FOREST};
                                       border: 2px solid #ffffff; }}
            #ttBadge[active="done"] {{ background: {ACCENT}; color: #ffffff;
                                       border: 2px solid {ACCENT}; }}

            #ttCredit {{ background: #ffffff; border-radius: 10px; }}

            #ttPage {{ background: {CANVAS}; }}
            #ttPageTitle {{ font-size: 20px; font-weight: 600; color: {INK};
                            letter-spacing: -0.2px; }}
            #ttPageSub {{ font-size: 12.5px; color: {MUTED}; }}
            #ttCardTitle {{ font-size: 14px; font-weight: 600; color: {INK}; }}
            #ttGroupLabel {{ font-size: 10.5px; font-weight: 700; color: #93a29b;
                             letter-spacing: 1.1px; padding: 6px 2px 2px 2px; }}
            #ttDivider {{ background: {LINE}; border: none; }}

            /* Cartao de saida: estado visivel de longe, area clicavel inteira. */
            #ttOption {{ background: #ffffff; border: 1px solid {LINE};
                         border-radius: 12px; }}
            #ttOption:hover {{ border-color: #b9cfc4; }}
            #ttOption[checked="true"] {{ border: 1.6px solid {ACCENT};
                                         background: #eef7f2; }}
            #ttOption[locked="true"] {{ background: #fbfcfb; border-style: dashed; }}
            #ttOption[locked="true"]:hover {{ border-color: {LINE}; }}
            #ttOptionTitle {{ font-size: 13.5px; font-weight: 600; color: {INK}; }}
            #ttOption[locked="true"] #ttOptionTitle {{ color: #7f8d87; }}
            #ttCard {{ background: #ffffff; border: 1px solid {LINE};
                       border-radius: 12px; }}
            #ttFooter {{ background: #ffffff; border-top: 1px solid {LINE}; }}

            #ttPrimary {{ background: {ACCENT}; color: #ffffff; font-size: 13px;
                          font-weight: 600; padding: 11px 22px; border: none;
                          border-radius: 9px; }}
            #ttPrimary:hover {{ background: #146f4e; }}
            #ttPrimary:disabled {{ background: #a8c9ba; }}
            #ttGhost {{ background: transparent; color: {MUTED}; border: none;
                        padding: 11px 14px; font-size: 12.5px; }}
            #ttGhost:hover {{ color: {INK}; }}
            #ttGhost:disabled {{ color: #c3ccc8; }}

            QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QTextEdit {{
                border: 1px solid {LINE}; border-radius: 7px;
                padding: 7px 9px; background: #ffffff; color: {INK};
                selection-background-color: {ACCENT};
            }}
            QDoubleSpinBox, QSpinBox {{ padding-right: 9px; }}
            QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus,
            QComboBox:focus, QTextEdit:focus {{ border: 1px solid {ACCENT}; }}
            QComboBox::drop-down {{ border: none; width: 22px; }}

            /* Os botoes de incremento ficam ocultos de proposito. Com a borda
               arredondada o Qt perde a geometria padrao deles e eles saem como
               um traco ou um quadrado escuro; desenhar a seta por borda CSS nao
               funciona em sub-controle. O valor e digitado e a roda do mouse
               continua ajustando, entao nao se perde nada e a tela fica limpa. */
            QDoubleSpinBox::up-button, QSpinBox::up-button,
            QDoubleSpinBox::down-button, QSpinBox::down-button {{
                width: 0; height: 0; border: none;
            }}

            QPushButton {{ background: #ffffff; border: 1px solid {LINE};
                           border-radius: 7px; padding: 7px 13px; color: {INK}; }}
            QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}

            /* O rotulo pesa mais que a explicacao; antes era o contrario e a
               tela parecia toda no mesmo nivel. */
            #ttHelp {{ color: {MUTED}; font-size: 11.5px; }}
            #ttMark {{ background: #ffffff; border-radius: 11px; }}
            #ttBrowse {{ padding: 7px 0; font-size: 15px; color: {MUTED}; }}
            QCheckBox {{ spacing: 10px; color: {INK}; font-size: 13.5px;
                         font-weight: 500; }}
            QCheckBox::indicator {{ width: 17px; height: 17px;
                                    border: 1px solid #c2ccc7; border-radius: 5px;
                                    background: #ffffff; }}
            QCheckBox::indicator:checked {{ background: {ACCENT};
                                            border-color: {ACCENT}; }}
            /* Marcada e desabilitada continua parecendo marcada: as saidas
               obrigatorias apareciam como se estivessem desligadas. */
            QCheckBox::indicator:checked:disabled {{ background: #9ac7b3;
                                                     border-color: #9ac7b3; }}
            QCheckBox::indicator:unchecked:disabled {{ background: {ACCENT_SOFT};
                                                       border-color: #c9ded4; }}
            QCheckBox:disabled {{ color: #7f8d87; }}

            QProgressBar {{ border: none; border-radius: 5px; height: 8px;
                            text-align: center; color: transparent;
                            background: #e6ebe8; }}
            QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
            #ttLog {{ background: #fbfcfb; font-family: "DejaVu Sans Mono",
                      Consolas, monospace; font-size: 11px; color: #46534c; }}

            QToolTip {{ background: {INK}; color: #ffffff; border: none;
                        padding: 9px 11px; border-radius: 7px; font-size: 11.5px; }}
            QScrollArea {{ background: {CANVAS}; }}
            QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
            QScrollBar::handle:vertical {{ background: #ccd6d1; border-radius: 5px;
                                           min-height: 30px; }}
            QScrollBar::handle:vertical:hover {{ background: #b3c2bb; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
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
        for position, (row, badge) in enumerate(self._step_rows):
            state = "true" if position == index else (
                "done" if position < index else "false")
            for widget in (row, badge, self.step_labels[position]):
                widget.setProperty("active", state)
                widget.style().unpolish(widget)
                widget.style().polish(widget)
        self._refresh_status()
        if last:
            self._refresh_summary()

    def _elide(self, label, text):
        """Corta pelo meio, não pelo fim: a extensão do arquivo é justamente a
        parte que o usuário usa para reconhecê-lo."""
        metrics = label.fontMetrics()
        width = max(label.width(), 176)
        label.setText(metrics.elidedText(
            text, qt_enum("TextElideMode", "ElideMiddle"), width))
        label.setToolTip(text)

    def _refresh_status(self):
        """Mantém o painel da lateral em dia com o que já foi escolhido."""
        dem = self.dem_file.text()
        self._elide(self.status_rows["status_dem"],
                    os.path.basename(dem) if dem else self.t("status_no_dem"))
        count = 2 + sum(card.isChecked() for card in
                        (self.want_zones, self.want_transit,
                         self.want_streams, self.want_route))
        self.status_rows["status_outputs"].setText(
            self.t("status_outputs_n").format(n=count))
        out = self.output_edit.text().strip()
        self._elide(self.status_rows["status_output_file"],
                    os.path.basename(out) if out else self.t("status_no_output"))

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
