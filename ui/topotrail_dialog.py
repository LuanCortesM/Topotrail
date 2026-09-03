import json
import os
import tempfile
import traceback
from datetime import datetime

from qgis.PyQt import uic
from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QColor, QFont, QPalette, QPixmap
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QCheckBox,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QApplication,
)
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsColorRampShader,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsProcessingFeedback,
    QgsProject,
    QgsRasterShader,
    QgsRasterLayer,
    QgsRasterTransparency,
    QgsSingleBandPseudoColorRenderer,
    QgsVectorLayer,
)
from qgis.gui import QgsMapToolEmitPoint, QgsProjectionSelectionDialog, QgsProjectionSelectionWidget
import qgis.processing as processing


FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), "topotrail_dialog.ui"))


def qt_enum(enum_group, value):
    """Return Qt enum values in a way that works with both Qt5 and Qt6."""
    group = getattr(Qt, enum_group, Qt)
    return getattr(group, value)


def size_policy(value):
    """Return QSizePolicy values in a way that works with Qt5 and Qt6."""
    group = getattr(QSizePolicy, "Policy", QSizePolicy)
    return getattr(group, value)


def class_enum(cls, enum_group, value):
    """Return class-scoped enum values in a way that works with Qt5 and Qt6."""
    group = getattr(cls, enum_group, cls)
    return getattr(group, value)


ALIGN_RIGHT = qt_enum("AlignmentFlag", "AlignRight")
ALIGN_LEFT = qt_enum("AlignmentFlag", "AlignLeft")
ALIGN_TOP = qt_enum("AlignmentFlag", "AlignTop")
ALIGN_CENTER = qt_enum("AlignmentFlag", "AlignCenter")
ALIGN_VCENTER = qt_enum("AlignmentFlag", "AlignVCenter")
KEEP_ASPECT_RATIO = qt_enum("AspectRatioMode", "KeepAspectRatio")
SMOOTH_TRANSFORMATION = qt_enum("TransformationMode", "SmoothTransformation")
RICH_TEXT = qt_enum("TextFormat", "RichText")
SCROLLBAR_ALWAYS_OFF = qt_enum("ScrollBarPolicy", "ScrollBarAlwaysOff")
SCROLLBAR_AS_NEEDED = qt_enum("ScrollBarPolicy", "ScrollBarAsNeeded")
ELIDE_RIGHT = qt_enum("TextElideMode", "ElideRight")
POLICY_FIXED = size_policy("Fixed")
POLICY_MINIMUM = size_policy("Minimum")
POLICY_MINIMUM_EXPANDING = size_policy("MinimumExpanding")
POLICY_EXPANDING = size_policy("Expanding")
FORM_GROW_ALL_NON_FIXED = class_enum(
    QFormLayout,
    "FieldGrowthPolicy",
    "AllNonFixedFieldsGrow",
)
FRAME_NO_FRAME = class_enum(QFrame, "Shape", "NoFrame")
FONT_BOLD = class_enum(QFont, "Weight", "Bold")
PAL_WINDOW = class_enum(QPalette, "ColorRole", "Window")
PAL_WINDOW_TEXT = class_enum(QPalette, "ColorRole", "WindowText")
PAL_BASE = class_enum(QPalette, "ColorRole", "Base")
PAL_TEXT = class_enum(QPalette, "ColorRole", "Text")
PAL_BUTTON = class_enum(QPalette, "ColorRole", "Button")
PAL_BUTTON_TEXT = class_enum(QPalette, "ColorRole", "ButtonText")
PAL_HIGHLIGHT = class_enum(QPalette, "ColorRole", "Highlight")
PAL_HIGHLIGHTED_TEXT = class_enum(QPalette, "ColorRole", "HighlightedText")
PAL_MID = class_enum(QPalette, "ColorRole", "Mid")
PAL_MIDLIGHT = class_enum(QPalette, "ColorRole", "Midlight")

try:
    MESSAGE_YES = QMessageBox.StandardButton.Yes
    MESSAGE_NO = QMessageBox.StandardButton.No
except AttributeError:
    MESSAGE_YES = getattr(QMessageBox, "Yes")
    MESSAGE_NO = getattr(QMessageBox, "No")


def topotrail_log_path(output_path):
    base_path, _ = os.path.splitext(output_path or "")
    if not base_path:
        logs_dir = os.path.join(tempfile.gettempdir(), "topotrail_logs")
        os.makedirs(logs_dir, exist_ok=True)
        base_path = os.path.join(logs_dir, f"topotrail_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    return f"{base_path}_diagnostico_topotrail.log"


def serialize_processing_params(params):
    if not params:
        return {}
    serialized = {}
    for key, value in params.items():
        if hasattr(value, "source"):
            serialized[key] = {
                "source": value.source(),
                "name": value.name(),
                "valid": value.isValid(),
                "crs": value.crs().authid() if value.crs().isValid() else "",
            }
        else:
            serialized[key] = value
    return serialized


def append_gui_diagnostic_log(output_path, event, **data):
    log_path = topotrail_log_path(output_path)
    output_dir = os.path.dirname(log_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "event": event,
    }
    payload.update(data)
    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    return log_path


class TopotrailDialog(QDialog, FORM_CLASS):
    def __init__(self, iface=None, parent=None):
        super(TopotrailDialog, self).__init__(parent)
        self.iface = iface
        self.language = "pt_BR"
        self._map_tool = None
        self._previous_map_tool = None
        self._temp_point_files = []
        self.setupUi(self)
        self.add_language_switch()

        self.demBrowseButton.clicked.connect(lambda: self.browse_file("demFileEdit", "Raster (*.tif *.tiff)"))
        self.slopeBrowseButton.clicked.connect(lambda: self.browse_file("slopeFileEdit", "Raster (*.tif *.tiff)"))
        self.curvHBrowseButton.clicked.connect(lambda: self.browse_file("curvHFileEdit", "Raster (*.tif *.tiff)"))
        self.curvVBrowseButton.clicked.connect(lambda: self.browse_file("curvVFileEdit", "Raster (*.tif *.tiff)"))
        self.outputBrowseButton.clicked.connect(self.browse_output)

        self.generateButton.clicked.connect(self.generate_trails)
        self.generateButton.setText("Gerar resultados TopoTrail")

        self.altMinSpin.setValue(0)
        self.altMaxSpin.setValue(2600)
        self.altMinSpin.setToolTip("Limite usado nas zonas potenciais. A rota pode partir de altitudes mais baixas.")
        self.altMaxSpin.setToolTip("Limite usado nas zonas potenciais. A rota pode chegar a pontos mais altos se o destino estiver no MDE.")
        self.maxSlopeSpin.setMaximum(200)
        self.maxSlopeSpin.setValue(55)
        self.maxSlopeSpin.setToolTip("Limite rÃ­gido para Ã¡reas caminhÃ¡veis e rota. 55% exclui encostas muito Ã­ngremes; aumente se uma rota de montanha ficar bloqueada.")
        self.slopeScoreMaxSpin = QDoubleSpinBox()
        self.slopeScoreMaxSpin.setMinimum(1.0)
        self.slopeScoreMaxSpin.setMaximum(200.0)
        self.slopeScoreMaxSpin.setDecimals(1)
        self.slopeScoreMaxSpin.setSingleStep(5.0)
        self.slopeScoreMaxSpin.setValue(50.0)
        self.slopeScoreMaxSpin.setToolTip("Valor usado para reduzir a nota da declividade. Nao exclui a celula; apenas aumenta o custo.")
        self.paramsGroup.layout().insertRow(3, "Declividade de custo maximo (%):", self.slopeScoreMaxSpin)
        self.thresholdLabel.setText("Threshold (0 = percentil auto):")
        self.thresholdSpin.setValue(0.0)
        self.thresholdSpin.setToolTip("Use 0 para selecionar automaticamente o percentil configurado dos pixels viaveis.")
        self.autoPercentileSpin = QDoubleSpinBox()
        self.autoPercentileSpin.setMinimum(1.0)
        self.autoPercentileSpin.setMaximum(99.0)
        self.autoPercentileSpin.setDecimals(1)
        self.autoPercentileSpin.setSingleStep(5.0)
        self.autoPercentileSpin.setValue(75.0)
        self.autoPercentileSpin.setToolTip("Percentil usado quando o threshold esta em 0. P75 tende a mapear alta adequabilidade; P90 e mais restritivo.")
        self.paramsGroup.layout().insertRow(5, "Percentil automatico:", self.autoPercentileSpin)
        self.altitudeBandThresholdCheck = QCheckBox("Equilibrar zonas por altitude")
        self.altitudeBandThresholdCheck.setChecked(True)
        self.altitudeBandThresholdCheck.setToolTip(
            "Quando o threshold esta em 0, seleciona as melhores celulas dentro de cada faixa altimetrica. "
            "Isso evita que as zonas fiquem concentradas apenas nas baixas altitudes."
        )
        self.altitudeBandSizeSpin = QDoubleSpinBox()
        self.altitudeBandSizeSpin.setMinimum(50.0)
        self.altitudeBandSizeSpin.setMaximum(1000.0)
        self.altitudeBandSizeSpin.setDecimals(0)
        self.altitudeBandSizeSpin.setSingleStep(50.0)
        self.altitudeBandSizeSpin.setValue(200.0)
        self.altitudeBandSizeSpin.setToolTip("Tamanho das faixas usadas para equilibrar as zonas por altitude.")
        self.paramsGroup.layout().insertRow(6, "", self.altitudeBandThresholdCheck)
        self.paramsGroup.layout().insertRow(7, "Faixa altimetrica (m):", self.altitudeBandSizeSpin)
        self.walkabilityZonesCheck = QCheckBox("Zonas = Ã¡rea caminhÃ¡vel contÃ­nua")
        self.walkabilityZonesCheck.setChecked(True)
        self.walkabilityZonesCheck.setToolTip(
            "Quando ativo, as zonas mostram tudo que Ã© caminhÃ¡vel segundo altitude e declividade, "
            "em vez de selecionar apenas as cÃ©lulas com maior pontuaÃ§Ã£o."
        )
        self.paramsGroup.layout().insertRow(8, "", self.walkabilityZonesCheck)
        self.minPatchAreaSpin = QDoubleSpinBox()
        self.minPatchAreaSpin.setMinimum(0.0)
        self.minPatchAreaSpin.setMaximum(100000.0)
        self.minPatchAreaSpin.setDecimals(2)
        self.minPatchAreaSpin.setSingleStep(0.5)
        self.minPatchAreaSpin.setValue(50.0)
        self.minPatchAreaSpin.setToolTip("Remove fragmentos menores antes de gerar o vetor final. Valores maiores reduzem Ã¡reas picotadas no mapa.")
        self.paramsGroup.layout().insertRow(9, "Area minima do fragmento (ha):", self.minPatchAreaSpin)
        self.weightAltSpin.setValue(0.0)
        self.weightSlopeSpin.setValue(1.0)
        self.weightCurvHSpin.setValue(1.0)
        self.weightCurvVSpin.setValue(1.0)
        self.formatComboBox.setCurrentIndex(1)

        self.outputCrsSelector = QgsProjectionSelectionWidget()
        self.outputCrsSelector.setCrs(QgsProject.instance().crs())
        self.outputGroup.layout().addRow("CRS de saida:", self.outputCrsSelector)
        self.add_route_section()
        self.add_about_section()
        self.make_layout_more_horizontal()
        self.apply_visual_theme()

        self.demCrsButton.clicked.connect(lambda: self.select_crs("demFileEdit", "demCrsLabel"))
        self.slopeCrsButton.clicked.connect(lambda: self.select_crs("slopeFileEdit", "slopeCrsLabel"))
        self.curvHCrsButton.clicked.connect(lambda: self.select_crs("curvHFileEdit", "curvHCrsLabel"))
        self.curvVCrsButton.clicked.connect(lambda: self.select_crs("curvVFileEdit", "curvVCrsLabel"))

        self.demFileEdit.textChanged.connect(lambda: self.update_crs_label("demFileEdit", "demCrsLabel"))
        self.slopeFileEdit.textChanged.connect(lambda: self.update_crs_label("slopeFileEdit", "slopeCrsLabel"))
        self.curvHFileEdit.textChanged.connect(lambda: self.update_crs_label("curvHFileEdit", "curvHCrsLabel"))
        self.curvVFileEdit.textChanged.connect(lambda: self.update_crs_label("curvVFileEdit", "curvVCrsLabel"))

        self.update_crs_label("demFileEdit", "demCrsLabel")
        self.update_crs_label("slopeFileEdit", "slopeCrsLabel")
        self.update_crs_label("curvHFileEdit", "curvHCrsLabel")
        self.update_crs_label("curvVFileEdit", "curvVCrsLabel")
        self.apply_test_defaults()
        self.apply_language()

    def add_language_switch(self):
        self.languageButton = QPushButton("PT-BR | ENG")
        self.languageButton.setObjectName("languageButton")
        self.languageButton.setCheckable(True)
        self.languageButton.setChecked(False)
        self.languageButton.setSizePolicy(POLICY_MINIMUM, POLICY_FIXED)
        self.languageButton.setToolTip("Alternar idioma da interface / Switch interface language")
        self.languageButton.clicked.connect(self.toggle_language)
        self.horizontalLayout.addStretch(1)
        self.horizontalLayout.addWidget(self.languageButton, 0, ALIGN_RIGHT | ALIGN_TOP)

    def toggle_language(self):
        self.language = "en" if self.language == "pt_BR" else "pt_BR"
        self.languageButton.setChecked(self.language == "en")
        self.apply_language()

    def ui_texts(self):
        return {
            "pt_BR": {
                "window_title": "TopoTrail - Planejamento de trilhas e acessos",
                "title": "TopoTrail\nPlanejamento de trilhas e acessos",
                "input_group": "Dados de entrada",
                "params_group": "Parametros",
                "route_group": "Planejamento de acesso (opcional)",
                "output_group": "Saida",
                "about_group": "Sobre o TopoTrail",
                "dem": "Modelo Digital de Elevacao (MDE):",
                "slope": "Declividade:",
                "curvh": "Curvatura horizontal:",
                "curvv": "Curvatura vertical:",
                "alt_min": "Altitude minima (m):",
                "alt_max": "Altitude maxima (m):",
                "max_slope": "Declividade maxima (%):",
                "slope_cost": "Declividade de custo maximo (%):",
                "threshold": "Threshold (0 = percentil auto):",
                "auto_percentile": "Percentil automatico:",
                "altitude_band": "Equilibrar zonas por altitude",
                "altitude_band_size": "Faixa altimetrica (m):",
                "walkability_zones": "Zonas = area caminhavel continua",
                "min_patch_area": "Area minima do fragmento (ha):",
                "weight_alt": "Peso altitude:",
                "weight_slope": "Peso declividade:",
                "weight_curvh": "Peso curvatura H:",
                "weight_curvv": "Peso curvatura V:",
                "start_file": "Ponto inicial (arquivo):",
                "end_file": "Ponto final (arquivo):",
                "start_coord": "Origem (coordenada):",
                "end_coord": "Destino (coordenada):",
                "route_buffer": "Corredor (m):",
                "route_margin": "Margem de busca (m):",
                "generate_zones": "Gerar zonas vetoriais",
                "format": "Formato:",
                "output_file": "Arquivo de saida:",
                "output_crs": "CRS de saida:",
                "pick_start": "Marcar origem no mapa",
                "pick_end": "Marcar destino no mapa",
                "generate": "Gerar resultados TopoTrail",
                "start_placeholder": "Camada de ponto da origem",
                "end_placeholder": "Camada de ponto do destino",
                "start_coord_placeholder": "X, Y no CRS do projeto",
                "end_coord_placeholder": "X, Y no CRS do projeto",
                "output_placeholder": "Escolha onde salvar os resultados",
                "about_html": (
                    "<b>TopoTrail</b><br>"
                    "Ferramenta para apoiar o planejamento de trilhas, acessos e deslocamentos de campo "
                    "em areas naturais e unidades de conservacao, integrando altitude, declividade e "
                    "curvaturas do relevo por analise multicriterio em SIG.<br><br>"
                    "<b>Desenvolvedor:</b> Luan da Silva Cortes Maciel (MACIEL, L. S.)<br>"
                    "<b>Orientador:</b> Leandro Freitas<br>"
                    "<b>Contexto:</b> desenvolvido como produto da pesquisa de mestrado em Biodiversidade em "
                    "Unidades de Conservacao, Escola Nacional de Botanica Tropical / Jardim Botanico "
                    "do Rio de Janeiro.<br>"
                    "<b>Projeto associado:</b> Herpeto Mantiqueira."
                ),
                "select_file": "Selecionar arquivo",
                "save_file": "Salvar arquivo",
                "map_unavailable_title": "Mapa indisponivel",
                "map_unavailable_text": "A captura no mapa so funciona dentro do QGIS.",
                "pick_point_title": "Marcar ponto",
                "pick_point_text": "Clique no mapa para definir a {label}. A coordenada sera registrada no CRS atual do projeto.",
                "start": "origem",
                "end": "destino",
                "required_title": "Campos obrigatorios",
                "required_text": "Por favor, preencha todos os campos obrigatorios.",
                "file_not_found_title": "Arquivo nao encontrado",
                "file_not_found_text": "O arquivo {path} nao existe.",
                "invalid_format_title": "Formato invalido",
                "invalid_format_text": "Use rasters GeoTIFF com extensao .tif ou .tiff.",
                "invalid_weights_title": "Pesos invalidos",
                "invalid_weights_sum": "Defina pelo menos um peso maior que zero. A soma dos pesos nao pode ser igual a zero.",
                "invalid_weights_negative": "Os pesos nao podem ser negativos.",
                "invalid_altitude_title": "Altitude invalida",
                "invalid_altitude_text": "A altitude minima deve ser menor que a altitude maxima.",
                "invalid_slope_title": "Declividade invalida",
                "invalid_slope_text": "Os limites de declividade devem ser maiores que zero.",
                "invalid_area_title": "Area invalida",
                "invalid_area_text": "A area minima nao pode ser negativa.",
                "invalid_percentile_title": "Percentil invalido",
                "invalid_percentile_text": "O percentil automatico deve estar entre 0 e 100.",
                "invalid_route_title": "Rota invalida",
                "invalid_route_text": "A largura do corredor e a margem de busca devem ser maiores que zero.",
                "incomplete_points_title": "Pontos incompletos",
                "incomplete_points_text": "Para gerar rota, informe origem e destino. Para nao gerar rota, deixe ambos vazios.",
                "undefined_crs_title": "CRS indefinido",
                "undefined_crs_text": "O arquivo {path} esta sem CRS definido!",
                "load_error_title": "Erro",
                "load_error_text": "Um ou mais rasters nao puderam ser carregados. Verifique se os arquivos sao validos.",
                "generate_zones_question_title": "Gerar zonas vetoriais?",
                "generate_zones_question_text": (
                    "A geracao de zonas vetoriais pode demorar varios minutos e deixar o QGIS temporariamente sem resposta. "
                    "Para planejar acesso, normalmente basta gerar raster, rota e corredor. Deseja continuar com as zonas?"
                ),
                "large_layer_title": "Camada vetorial grande",
                "large_layer_text": "As zonas potenciais geraram {count} feicoes. Carregar tudo agora pode deixar o mapa lento. Deseja carregar a camada mesmo assim?",
                "success_title": "Sucesso",
                "success_vector_text": "Processamento concluido. {count} camada(s) vetorial(is) carregada(s).",
                "success_raster_text": "Raster continuo de adequabilidade gerado. Para gerar poligonos de zonas potenciais, marque a opcao 'Gerar zonas vetoriais' antes de processar.",
                "warning_title": "Aviso",
                "warning_no_features": "Processamento concluido, mas nenhuma feicao foi gerada.",
                "error_title": "Erro",
                "error_text": "Erro ao gerar trilhas: {error}\n\nLog diagnostico salvo em:\n{log_path}",
                "crs_output_title": "CRS de saida definido",
                "crs_output_text": "O CRS de saida foi ajustado para {crs}. Os rasters de entrada nao foram alterados.",
                "coordinate_format_error": "Use o formato X Y, X; Y ou X, Y para coordenadas.",
                "start_input_conflict": "Escolha arquivo ou coordenada para a origem, nao os dois.",
                "end_input_conflict": "Escolha arquivo ou coordenada para o destino, nao os dois.",
                "route_pair_required": "Para gerar rota, informe origem e destino por arquivo ou por coordenada.",
            },
            "en": {
                "window_title": "TopoTrail - Trail and access planning",
                "title": "TopoTrail\nTrail and access planning",
                "input_group": "Input data",
                "params_group": "Parameters",
                "route_group": "Access planning (optional)",
                "output_group": "Output",
                "about_group": "About TopoTrail",
                "dem": "Digital Elevation Model (DEM):",
                "slope": "Slope:",
                "curvh": "Horizontal curvature:",
                "curvv": "Vertical curvature:",
                "alt_min": "Minimum altitude (m):",
                "alt_max": "Maximum altitude (m):",
                "max_slope": "Maximum slope (%):",
                "slope_cost": "Maximum cost slope (%):",
                "threshold": "Threshold (0 = automatic percentile):",
                "auto_percentile": "Automatic percentile:",
                "altitude_band": "Balance zones by altitude",
                "altitude_band_size": "Altitude band (m):",
                "walkability_zones": "Zones = continuous walkable area",
                "min_patch_area": "Minimum patch area (ha):",
                "weight_alt": "Altitude weight:",
                "weight_slope": "Slope weight:",
                "weight_curvh": "Horizontal curvature weight:",
                "weight_curvv": "Vertical curvature weight:",
                "start_file": "Start point (file):",
                "end_file": "End point (file):",
                "start_coord": "Origin (coordinate):",
                "end_coord": "Destination (coordinate):",
                "route_buffer": "Corridor (m):",
                "route_margin": "Search margin (m):",
                "generate_zones": "Generate vector zones",
                "format": "Format:",
                "output_file": "Output file:",
                "output_crs": "Output CRS:",
                "pick_start": "Pick origin on map",
                "pick_end": "Pick destination on map",
                "generate": "Generate TopoTrail results",
                "start_placeholder": "Origin point layer",
                "end_placeholder": "Destination point layer",
                "start_coord_placeholder": "X, Y in project CRS",
                "end_coord_placeholder": "X, Y in project CRS",
                "output_placeholder": "Choose where to save the results",
                "about_html": (
                    "<b>TopoTrail</b><br>"
                    "Tool for preliminary planning of trails, access routes and field movement in natural "
                    "areas and protected areas, integrating elevation, slope and terrain curvatures through "
                    "multicriteria GIS analysis.<br><br>"
                    "<b>Developer:</b> Luan da Silva Cortes Maciel (MACIEL, L. S.)<br>"
                    "<b>Advisor:</b> Leandro Freitas<br>"
                    "<b>Context:</b> developed as a product of the author's master's research in Biodiversity "
                    "in Protected Areas, Escola Nacional de Botanica Tropical / Jardim Botanico do Rio de Janeiro.<br>"
                    "<b>Associated project:</b> Herpeto Mantiqueira."
                ),
                "select_file": "Select file",
                "save_file": "Save file",
                "map_unavailable_title": "Map unavailable",
                "map_unavailable_text": "Map capture only works inside QGIS.",
                "pick_point_title": "Pick point",
                "pick_point_text": "Click the map to define the {label}. The coordinate will be registered in the current project CRS.",
                "start": "origin",
                "end": "destination",
                "required_title": "Required fields",
                "required_text": "Please fill in all required fields.",
                "file_not_found_title": "File not found",
                "file_not_found_text": "The file {path} does not exist.",
                "invalid_format_title": "Invalid format",
                "invalid_format_text": "Use GeoTIFF rasters with .tif or .tiff extension.",
                "invalid_weights_title": "Invalid weights",
                "invalid_weights_sum": "Set at least one weight greater than zero. The weight sum cannot be zero.",
                "invalid_weights_negative": "Weights cannot be negative.",
                "invalid_altitude_title": "Invalid altitude",
                "invalid_altitude_text": "Minimum altitude must be lower than maximum altitude.",
                "invalid_slope_title": "Invalid slope",
                "invalid_slope_text": "Slope limits must be greater than zero.",
                "invalid_area_title": "Invalid area",
                "invalid_area_text": "Minimum area cannot be negative.",
                "invalid_percentile_title": "Invalid percentile",
                "invalid_percentile_text": "Automatic percentile must be between 0 and 100.",
                "invalid_route_title": "Invalid route",
                "invalid_route_text": "Corridor width and search margin must be greater than zero.",
                "incomplete_points_title": "Incomplete points",
                "incomplete_points_text": "To generate a route, provide both origin and destination. To skip route generation, leave both empty.",
                "undefined_crs_title": "Undefined CRS",
                "undefined_crs_text": "The file {path} has no defined CRS!",
                "load_error_title": "Error",
                "load_error_text": "One or more rasters could not be loaded. Check whether the files are valid.",
                "generate_zones_question_title": "Generate vector zones?",
                "generate_zones_question_text": (
                    "Vector-zone generation may take several minutes and temporarily make QGIS unresponsive. "
                    "For access planning, the raster, route and corridor are usually enough. Continue with zones?"
                ),
                "large_layer_title": "Large vector layer",
                "large_layer_text": "Potential zones generated {count} features. Loading them now may slow the map. Load the layer anyway?",
                "success_title": "Success",
                "success_vector_text": "Processing completed. {count} vector layer(s) loaded.",
                "success_raster_text": "Continuous suitability raster generated. To generate potential-zone polygons, enable 'Generate vector zones' before processing.",
                "warning_title": "Warning",
                "warning_no_features": "Processing completed, but no features were generated.",
                "error_title": "Error",
                "error_text": "Error generating trails: {error}\n\nDiagnostic log saved at:\n{log_path}",
                "crs_output_title": "Output CRS defined",
                "crs_output_text": "The output CRS was set to {crs}. Input rasters were not modified.",
                "coordinate_format_error": "Use X Y, X; Y or X, Y as the coordinate format.",
                "start_input_conflict": "Choose either a file or a coordinate for the origin, not both.",
                "end_input_conflict": "Choose either a file or a coordinate for the destination, not both.",
                "route_pair_required": "To generate a route, provide both origin and destination by file or coordinate.",
            },
        }

    def text_for(self, key):
        return self.ui_texts()[self.language][key]

    def set_form_label(self, field, text):
        for form in self.findChildren(QFormLayout):
            label = form.labelForField(field)
            if label:
                label.setText(text)
                return

    def apply_language(self):
        t = self.text_for
        self.setWindowTitle(t("window_title"))
        self.titleLabel.setText(t("title"))
        self.languageButton.setChecked(self.language == "en")
        self.languageButton.setText("PT-BR | ENG")

        self.inputGroup.setTitle(t("input_group"))
        self.paramsGroup.setTitle(t("params_group"))
        self.routeGroup.setTitle(t("route_group"))
        self.outputGroup.setTitle(t("output_group"))
        self.aboutGroup.setTitle(t("about_group"))

        for key, label in getattr(self, "inputRowLabels", {}).items():
            label.setText(t(key))

        self.set_form_label(self.altMinSpin, t("alt_min"))
        self.set_form_label(self.altMaxSpin, t("alt_max"))
        self.set_form_label(self.maxSlopeSpin, t("max_slope"))
        self.set_form_label(self.slopeScoreMaxSpin, t("slope_cost"))
        self.thresholdLabel.setText(t("threshold"))
        self.set_form_label(self.thresholdSpin, t("threshold"))
        self.set_form_label(self.autoPercentileSpin, t("auto_percentile"))
        self.altitudeBandThresholdCheck.setText(t("altitude_band"))
        self.set_form_label(self.altitudeBandSizeSpin, t("altitude_band_size"))
        self.walkabilityZonesCheck.setText(t("walkability_zones"))
        self.set_form_label(self.minPatchAreaSpin, t("min_patch_area"))
        self.set_form_label(self.weightAltSpin, t("weight_alt"))
        self.set_form_label(self.weightSlopeSpin, t("weight_slope"))
        self.set_form_label(self.weightCurvHSpin, t("weight_curvh"))
        self.set_form_label(self.weightCurvVSpin, t("weight_curvv"))

        for key, label in getattr(self, "routeRowLabels", {}).items():
            label.setText(t(key))
        self.set_form_label(self.routeBufferSpin, t("route_buffer"))
        self.set_form_label(self.routeMarginSpin, t("route_margin"))
        self.generateZonesCheck.setText(t("generate_zones"))

        self.set_form_label(self.formatComboBox, t("format"))
        self.set_form_label(self.outputFileEdit, t("output_file"))
        self.set_form_label(self.outputCrsSelector, t("output_crs"))

        self.pickStartButton.setText(t("pick_start"))
        self.pickEndButton.setText(t("pick_end"))
        self.generateButton.setText(t("generate"))
        self.startPointEdit.setPlaceholderText(t("start_placeholder"))
        self.endPointEdit.setPlaceholderText(t("end_placeholder"))
        self.startCoordEdit.setPlaceholderText(t("start_coord_placeholder"))
        self.endCoordEdit.setPlaceholderText(t("end_coord_placeholder"))
        self.outputFileEdit.setPlaceholderText(t("output_placeholder"))
        self.aboutTextLabel.setText(t("about_html"))
        if hasattr(self, "_scrollArea"):
            self._apply_responsive_hud()

    def add_route_section(self):
        route_group = QGroupBox("Planejamento de acesso (opcional)")
        self.routeGroup = route_group
        layout = QFormLayout()

        self.startPointEdit = QLineEdit()
        self.startPointEdit.setReadOnly(True)
        self.startPointBrowseButton = QToolButton()
        self.startPointBrowseButton.setText("...")
        self.startPointBrowseButton.setToolTip("Selecionar arquivo da origem")
        self.startPointBrowseButton.setSizePolicy(POLICY_FIXED, POLICY_FIXED)
        start_row = QHBoxLayout()
        start_row.setContentsMargins(0, 0, 0, 0)
        start_row.addWidget(self.startPointEdit)
        start_row.addWidget(self.startPointBrowseButton)

        self.endPointEdit = QLineEdit()
        self.endPointEdit.setReadOnly(True)
        self.endPointBrowseButton = QToolButton()
        self.endPointBrowseButton.setText("...")
        self.endPointBrowseButton.setToolTip("Selecionar arquivo do destino")
        self.endPointBrowseButton.setSizePolicy(POLICY_FIXED, POLICY_FIXED)
        end_row = QHBoxLayout()
        end_row.setContentsMargins(0, 0, 0, 0)
        end_row.addWidget(self.endPointEdit)
        end_row.addWidget(self.endPointBrowseButton)

        self.routeBufferSpin = QDoubleSpinBox()
        self.routeBufferSpin.setMinimum(1.0)
        self.routeBufferSpin.setMaximum(5000.0)
        self.routeBufferSpin.setDecimals(0)
        self.routeBufferSpin.setSingleStep(25.0)
        self.routeBufferSpin.setValue(100.0)
        self.routeBufferSpin.setToolTip("Largura do corredor lateral ao redor da rota sugerida.")

        self.routeMarginSpin = QDoubleSpinBox()
        self.routeMarginSpin.setMinimum(100.0)
        self.routeMarginSpin.setMaximum(50000.0)
        self.routeMarginSpin.setDecimals(0)
        self.routeMarginSpin.setSingleStep(500.0)
        self.routeMarginSpin.setValue(5000.0)
        self.routeMarginSpin.setToolTip("Quanto o algoritmo pode procurar lateralmente fora do retangulo entre origem e destino.")

        self.startCoordEdit = QLineEdit()
        self.startCoordEdit.setPlaceholderText("X, Y no CRS do projeto")
        self.endCoordEdit = QLineEdit()
        self.endCoordEdit.setPlaceholderText("X, Y no CRS do projeto")
        self.pickStartButton = QPushButton("Marcar origem no mapa")
        self.pickEndButton = QPushButton("Marcar destino no mapa")
        self.pickStartButton.setEnabled(bool(self.iface))
        self.pickEndButton.setEnabled(bool(self.iface))
        self.pickStartButton.setSizePolicy(POLICY_MINIMUM, POLICY_FIXED)
        self.pickEndButton.setSizePolicy(POLICY_MINIMUM, POLICY_FIXED)

        start_coord_row = QHBoxLayout()
        start_coord_row.setContentsMargins(0, 0, 0, 0)
        start_coord_row.addWidget(self.startCoordEdit)
        start_coord_row.addWidget(self.pickStartButton)
        end_coord_row = QHBoxLayout()
        end_coord_row.setContentsMargins(0, 0, 0, 0)
        end_coord_row.addWidget(self.endCoordEdit)
        end_coord_row.addWidget(self.pickEndButton)

        self.generateZonesCheck = QCheckBox("Gerar zonas vetoriais")
        self.generateZonesCheck.setChecked(True)
        self.generateZonesCheck.setToolTip(
            "Ative apenas quando precisar do poligono de zonas. Essa etapa pode demorar e gerar muitas feicoes."
        )

        self.routeRowLabels = {
            "start_file": QLabel("Ponto inicial (arquivo):"),
            "end_file": QLabel("Ponto final (arquivo):"),
            "start_coord": QLabel("Origem (coordenada):"),
            "end_coord": QLabel("Destino (coordenada):"),
        }
        layout.addRow(self.routeRowLabels["start_file"], start_row)
        layout.addRow(self.routeRowLabels["end_file"], end_row)
        layout.addRow(self.routeRowLabels["start_coord"], start_coord_row)
        layout.addRow(self.routeRowLabels["end_coord"], end_coord_row)
        layout.addRow("Corredor (m):", self.routeBufferSpin)
        layout.addRow("Margem de busca (m):", self.routeMarginSpin)
        layout.addRow("", self.generateZonesCheck)
        route_group.setLayout(layout)

        self.startPointBrowseButton.clicked.connect(
            lambda: self.browse_file("startPointEdit", "Vetores (*.gpkg *.shp *.kml *.geojson)")
        )
        self.endPointBrowseButton.clicked.connect(
            lambda: self.browse_file("endPointEdit", "Vetores (*.gpkg *.shp *.kml *.geojson)")
        )
        self.pickStartButton.clicked.connect(lambda: self.start_map_pick("start"))
        self.pickEndButton.clicked.connect(lambda: self.start_map_pick("end"))

        self.layout().insertWidget(self.layout().count() - 2, route_group)

    def next_test_output_path(self, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        index = 1
        while True:
            candidate = os.path.join(output_dir, f"topotrail_teste_{index:02d}.gpkg")
            if not os.path.exists(candidate):
                return candidate
            index += 1

    def apply_test_defaults(self):
        """Keep the release UI free from developer-machine file paths."""
        return

    def add_about_section(self):
        about_group = QGroupBox("Sobre o TopoTrail")
        self.aboutGroup = about_group
        layout = QVBoxLayout()

        logo_row = QHBoxLayout()
        logo_row.setAlignment(ALIGN_CENTER)
        self.aboutLogoLabels = []
        for filename in [
            "logo_herpeto_mantiqueira.png",
            "logo_enbt.jpg",
            "logo_jbrj.jpg",
        ]:
            label = QLabel()
            label.setAlignment(ALIGN_CENTER)
            label.setSizePolicy(POLICY_EXPANDING, POLICY_FIXED)
            label._topotrail_pixmap = QPixmap(os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", filename))
            label._topotrail_aspect = 150.0 / 86.0
            self.aboutLogoLabels.append(label)
            logo_row.addWidget(label)
        layout.addLayout(logo_row)

        text = QLabel(
            "<b>TopoTrail</b><br>"
            "Ferramenta para apoiar o planejamento de trilhas, acessos e deslocamentos de campo "
            "em Ã¡reas naturais e unidades de conservaÃ§Ã£o, integrando altitude, declividade e "
            "curvaturas do relevo por anÃ¡lise multicritÃ©rio em SIG.<br><br>"
            "<b>Desenvolvedor:</b> Luan da Silva Cortes Maciel (MACIEL, L. S.)<br>"
            "<b>Orientador:</b> Leandro Freitas<br>"
            "<b>Contexto:</b> desenvolvido como produto da pesquisa de mestrado em Biodiversidade em "
            "Unidades de ConservaÃ§Ã£o, Escola Nacional de BotÃ¢nica Tropical / Jardim BotÃ¢nico "
            "do Rio de Janeiro.<br>"
            "<b>Projeto associado:</b> Herpeto Mantiqueira."
        )
        text.setWordWrap(True)
        text.setTextFormat(RICH_TEXT)
        text.setSizePolicy(POLICY_EXPANDING, POLICY_MINIMUM)
        self.aboutTextLabel = text
        layout.addWidget(text)

        about_group.setLayout(layout)
        self.layout().insertWidget(self.layout().count() - 2, about_group)

    def _dpi_ratio(self):
        """DPI scaling: derive logical sizes from Qt screen scaling."""
        window = self.windowHandle()
        screen = window.screen() if window else QApplication.primaryScreen()
        if not screen:
            return 1.0
        return max(0.85, min(2.25, screen.logicalDotsPerInch() / 96.0))

    def _scaled(self, value):
        return max(1, int(round(value * self._dpi_ratio())))

    def _scaled_size(self, width, height):
        return QSize(self._scaled(width), self._scaled(height))

    def _palette_hex(self, role):
        return self.palette().color(role).name()

    def _contrast_text_hex(self, background_hex, preferred_hex):
        color = QColor(background_hex)
        preferred = QColor(preferred_hex)
        if not color.isValid() or not preferred.isValid():
            return preferred_hex

        def luminance(qcolor):
            channels = [qcolor.redF(), qcolor.greenF(), qcolor.blueF()]
            linear = []
            for channel in channels:
                linear.append(channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4)
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        bg_lum = luminance(color)
        fg_lum = luminance(preferred)
        ratio = (max(bg_lum, fg_lum) + 0.05) / (min(bg_lum, fg_lum) + 0.05)
        if ratio >= 4.5:
            return preferred_hex
        return "#000000" if bg_lum > 0.45 else "#ffffff"

    def _hud_mode(self):
        """Responsive breakpoints: compact, normal and wide HUD modes."""
        available_width = max(self.width(), self.minimumSizeHint().width())
        if available_width < self._scaled(820):
            return "compact"
        if available_width >= self._scaled(1320):
            return "wide"
        return "normal"

    def _clear_layout_items(self, layout):
        while layout.count():
            layout.takeAt(0)

    def _set_point_button_texts(self, compact):
        start_text = self.text_for("pick_start")
        end_text = self.text_for("pick_end")
        self.pickStartButton.setText("Mapa" if compact else start_text)
        self.pickEndButton.setText("Mapa" if compact else end_text)
        self.pickStartButton.setToolTip(start_text)
        self.pickEndButton.setToolTip(end_text)

    def _update_adaptive_logos(self, mode):
        logo_size = self._scaled(46 if mode == "compact" else 58 if mode == "normal" else 66)
        self.logoLabel.setMinimumSize(logo_size, logo_size)
        self.logoLabel.setMaximumSize(logo_size, logo_size)

        max_logo_height = self._scaled(48 if mode == "compact" else 66 if mode == "normal" else 82)
        for label in getattr(self, "aboutLogoLabels", []):
            label.setMinimumSize(0, 0)
            label.setMaximumHeight(max_logo_height)
            label.setMinimumHeight(max_logo_height)
            pixmap = getattr(label, "_topotrail_pixmap", QPixmap())
            if not pixmap.isNull():
                width = max(self._scaled(72), int(max_logo_height * getattr(label, "_topotrail_aspect", 1.6)))
                label.setPixmap(pixmap.scaled(width, max_logo_height, KEEP_ASPECT_RATIO, SMOOTH_TRANSFORMATION))

    def _apply_text_overflow_guards(self):
        for label in list(getattr(self, "inputRowLabels", {}).values()) + list(getattr(self, "routeRowLabels", {}).values()):
            original = label.text() if not label.text().endswith("...") else (label.toolTip() or label.text())
            label.setToolTip(original)
            width = max(label.width(), self._scaled(80))
            label.setText(label.fontMetrics().elidedText(original, ELIDE_RIGHT, width))

        for button in [
            self.pickStartButton,
            self.pickEndButton,
            self.generateButton,
            self.languageButton,
        ]:
            if not button.toolTip():
                button.setToolTip(button.text())

    def _relayout_content_columns(self, mode):
        layout = getattr(self, "_contentLayout", None)
        if layout is None:
            return

        self._clear_layout_items(layout)
        if mode == "compact":
            layout.addLayout(self._leftColumn, 0, 0)
            layout.addLayout(self._rightColumn, 1, 0)
            layout.setColumnStretch(0, 1)
            layout.setColumnStretch(1, 0)
        else:
            layout.addLayout(self._leftColumn, 0, 0)
            layout.addLayout(self._rightColumn, 0, 1)
            layout.setColumnStretch(0, 3 if mode == "normal" else 4)
            layout.setColumnStretch(1, 2 if mode == "normal" else 3)

    def _apply_responsive_hud(self):
        """Central HUD adaptation for monitor size, DPI and QGIS theme."""
        mode = self._hud_mode()
        if getattr(self, "_currentHudMode", None) != mode:
            self._currentHudMode = mode
            self._relayout_content_columns(mode)

        compact = mode == "compact"
        margin = self._scaled(8 if compact else 12 if mode == "normal" else 16)
        spacing = self._scaled(6 if compact else 8 if mode == "normal" else 10)
        self.layout().setContentsMargins(margin, margin, margin, margin)
        self.layout().setSpacing(spacing)
        self._set_point_button_texts(compact)
        self._update_adaptive_logos(mode)

        base_font = QFont(self.font())
        base_font.setPointSizeF(max(8.5, min(11.5, 9.5 * self._dpi_ratio())))
        self.setFont(base_font)
        self.titleLabel.setFont(QFont(base_font.family(), max(12, int(base_font.pointSizeF() + (4 if compact else 8))), FONT_BOLD))

        for spin in self.findChildren(QDoubleSpinBox):
            spin.setMinimumWidth(self._scaled(88 if compact else 104))
            spin.setSizePolicy(POLICY_MINIMUM_EXPANDING, POLICY_FIXED)
        for line_edit in self.findChildren(QLineEdit):
            line_edit.setMinimumWidth(0)
            line_edit.setSizePolicy(POLICY_EXPANDING, POLICY_FIXED)
        for group in [self.inputGroup, self.paramsGroup, self.routeGroup, self.outputGroup, self.aboutGroup]:
            group.layout().setContentsMargins(margin, margin + spacing, margin, margin)
            group.layout().setSpacing(spacing)

        # Horizontal scrolling: keep a stable content floor so narrow plugin
        # windows can be dragged sideways instead of clipping fields/buttons.
        content_width = self._scaled(760 if compact else 980 if mode == "normal" else 1180)
        self._contentWidget.setMinimumWidth(content_width)
        self._scrollArea.setHorizontalScrollBarPolicy(SCROLLBAR_AS_NEEDED)
        self._apply_text_overflow_guards()

    def resizeEvent(self, event):
        super(TopotrailDialog, self).resizeEvent(event)
        if hasattr(self, "_scrollArea"):
            self._apply_responsive_hud()

    def _dialog_exec(self, dialog):
        exec_method = getattr(dialog, "exec", None) or getattr(dialog, "exec_", None)
        return exec_method()

    def make_layout_more_horizontal(self):
        self.setWindowTitle("TopoTrail - Planejamento de trilhas e acessos")
        # Responsiveness: start from size hints and let Qt/DPI scaling choose
        # the actual pixel size instead of forcing a rigid desktop dimension.
        self.setMinimumSize(0, 0)
        self.resize(self._scaled_size(1040, 680))
        self.setSizeGripEnabled(True)

        main_layout = self.layout()
        margin = self._scaled(12)
        main_layout.setContentsMargins(margin, margin, margin, margin)
        main_layout.setSpacing(self._scaled(8))

        self.logoLabel.setSizePolicy(POLICY_FIXED, POLICY_FIXED)
        self.titleLabel.setText("TopoTrail\nPlanejamento de trilhas e acessos")
        self.titleLabel.setWordWrap(True)
        self.titleLabel.setSizePolicy(POLICY_EXPANDING, POLICY_MINIMUM)
        self.rebuild_input_group()

        for edit in [
            self.demFileEdit,
            self.slopeFileEdit,
            self.curvHFileEdit,
            self.curvVFileEdit,
            self.outputFileEdit,
        ]:
            edit.setMinimumWidth(0)
            edit.setSizePolicy(POLICY_EXPANDING, POLICY_FIXED)

        for button in [
            self.demBrowseButton,
            self.slopeBrowseButton,
            self.curvHBrowseButton,
            self.curvVBrowseButton,
            self.outputBrowseButton,
        ]:
            button.setSizePolicy(POLICY_FIXED, POLICY_FIXED)
            button.setToolTip(button.toolTip() or "Selecionar arquivo")

        for button in [
            self.demCrsButton,
            self.slopeCrsButton,
            self.curvHCrsButton,
            self.curvVCrsButton,
        ]:
            button.hide()

        self.paramsGroup = self._split_parameter_panel()

        groups = [
            getattr(self, "_oldInputGroup", None),
            self.inputGroup,
            getattr(self, "_oldParamsGroup", None),
            self.paramsGroup,
            self.outputGroup,
            self.routeGroup,
            self.aboutGroup,
        ]
        for group in groups:
            if group is not None:
                self._take_widget(main_layout, group)

        content_widget = QWidget(self)
        content_layout = QGridLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(self._scaled(10))

        left_column = QVBoxLayout()
        left_column.setSpacing(self._scaled(10))
        left_column.addWidget(self.inputGroup)
        left_column.addWidget(self.routeGroup)
        left_column.addWidget(self.outputGroup)
        left_column.addStretch(1)

        right_column = QVBoxLayout()
        right_column.setSpacing(self._scaled(10))
        right_column.addWidget(self.paramsGroup)
        right_column.addWidget(self.aboutGroup)
        right_column.addStretch(1)

        self._contentLayout = content_layout
        self._contentWidget = content_widget
        self._leftColumn = left_column
        self._rightColumn = right_column

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(FRAME_NO_FRAME)
        scroll_area.setHorizontalScrollBarPolicy(SCROLLBAR_AS_NEEDED)
        scroll_area.setWidget(content_widget)
        scroll_area.setSizePolicy(POLICY_EXPANDING, POLICY_EXPANDING)
        self._scrollArea = scroll_area

        main_layout.insertWidget(1, scroll_area, 1)
        self._apply_responsive_hud()

    def rebuild_input_group(self):
        old_group = self.inputGroup
        old_layout = old_group.layout()
        if old_layout is not None:
            while old_layout.count():
                old_layout.takeAt(0)

        old_group.hide()
        self._oldInputGroup = old_group
        new_group = QGroupBox(old_group.title(), self)
        layout = QGridLayout()
        layout.setColumnStretch(0, 0)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 0)
        layout.setColumnStretch(3, 0)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)

        rows = [
            ("dem", "Modelo Digital de Elevacao (MDE):", self.demFileEdit, self.demBrowseButton, self.demCrsLabel),
            ("slope", "Declividade:", self.slopeFileEdit, self.slopeBrowseButton, self.slopeCrsLabel),
            ("curvh", "Curvatura Horizontal:", self.curvHFileEdit, self.curvHBrowseButton, self.curvHCrsLabel),
            ("curvv", "Curvatura Vertical:", self.curvVFileEdit, self.curvVBrowseButton, self.curvVCrsLabel),
        ]

        self.inputRowLabels = {}
        for row, (key, label_text, edit, browse_button, crs_label) in enumerate(rows):
            label = QLabel(label_text)
            label.setAlignment(ALIGN_RIGHT | ALIGN_VCENTER)
            self.inputRowLabels[key] = label
            layout.addWidget(label, row, 0)
            layout.addWidget(edit, row, 1)
            layout.addWidget(browse_button, row, 2)
            crs_label.setMinimumWidth(self._scaled(72))
            crs_label.setAlignment(ALIGN_LEFT | ALIGN_VCENTER)
            layout.addWidget(crs_label, row, 3)

        new_group.setLayout(layout)
        self.inputGroup = new_group

    def apply_visual_theme(self):
        window = self._palette_hex(PAL_WINDOW)
        window_text = self._palette_hex(PAL_WINDOW_TEXT)
        base = self._palette_hex(PAL_BASE)
        text = self._palette_hex(PAL_TEXT)
        button = self._palette_hex(PAL_BUTTON)
        button_text = self._palette_hex(PAL_BUTTON_TEXT)
        highlight = self._palette_hex(PAL_HIGHLIGHT)
        highlighted_text = self._contrast_text_hex(highlight, self._palette_hex(PAL_HIGHLIGHTED_TEXT))
        mid = self._palette_hex(PAL_MID)
        midlight = self._palette_hex(PAL_MIDLIGHT)

        # Theme contrast: all colors are derived from the active QGIS/Qt
        # palette, avoiding fixed light-theme assumptions in dark mode.
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {window};
                color: {window_text};
                font-family: "Segoe UI", "Arial";
                font-size: 9.5pt;
            }}
            QLabel {{
                color: {window_text};
            }}
            QLabel#titleLabel {{
                color: {window_text};
                font-size: 24px;
                font-weight: bold;
                padding-left: 6px;
            }}
            QLabel#logoLabel {{
                background-color: {base};
                border: 1px solid {mid};
                border-radius: 8px;
                padding: 4px;
            }}
            QGroupBox {{
                color: {window_text};
                background-color: {base};
                border: 1px solid {mid};
                border-radius: 8px;
                margin-top: 20px;
                padding: 16px 12px 12px 12px;
                font-weight: bold;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 14px;
                padding: 0px 8px;
                color: {window_text};
                background-color: {base};
            }}
            QLineEdit, QDoubleSpinBox, QComboBox {{
                color: {text};
                background-color: {base};
                border: 1px solid {mid};
                border-radius: 6px;
                min-height: 28px;
                padding: 3px 7px;
            }}
            QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus {{
                border: 1px solid {highlight};
                background-color: {base};
            }}
            QPushButton, QToolButton {{
                color: {button_text};
                background-color: {button};
                border: 1px solid {mid};
                border-radius: 6px;
                min-height: 28px;
                padding: 4px 10px;
                font-weight: 600;
            }}
            QPushButton:hover, QToolButton:hover {{
                border-color: {highlight};
            }}
            QPushButton:pressed, QToolButton:pressed {{
                background-color: {midlight};
            }}
            QPushButton#generateButton {{
                background-color: {highlight};
                color: {highlighted_text};
                border: 1px solid {highlight};
                min-height: 36px;
                font-size: 10.5pt;
                font-weight: 700;
            }}
            QPushButton#generateButton:hover {{
                border-color: {text};
            }}
            QPushButton#languageButton {{
                color: {text};
                background-color: {base};
                border: 1px solid {mid};
                font-size: 8.5pt;
                min-height: 24px;
                padding: 2px 8px;
            }}
            QPushButton#languageButton:checked {{
                background-color: {highlight};
                color: {highlighted_text};
            }}
            QProgressBar {{
                color: {text};
                background-color: {base};
                border: 1px solid {mid};
                border-radius: 6px;
                min-height: 18px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {highlight};
                border-radius: 5px;
            }}
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            QScrollBar:horizontal, QScrollBar:vertical {{
                background: {base};
                border: 1px solid {mid};
            }}
            QScrollBar::handle:horizontal, QScrollBar::handle:vertical {{
                background: {midlight};
                border: 1px solid {mid};
                min-width: 32px;
                min-height: 32px;
            }}
        """)

        for group in [
            self.inputGroup,
            self.paramsGroup,
            self.routeGroup,
            self.outputGroup,
            self.aboutGroup,
        ]:
            group.layout().setContentsMargins(14, 16, 14, 12)
            group.layout().setSpacing(8)

        for form in self.findChildren(QFormLayout):
            form.setHorizontalSpacing(10)
            form.setVerticalSpacing(8)
            form.setLabelAlignment(ALIGN_RIGHT | ALIGN_VCENTER)
            form.setFormAlignment(ALIGN_TOP)

        for spin in self.findChildren(QDoubleSpinBox):
            spin.setMinimumWidth(self._scaled(104))

        for line_edit in self.findChildren(QLineEdit):
            line_edit.setMinimumWidth(0)

        self.startPointEdit.setPlaceholderText("Camada de ponto da origem")
        self.endPointEdit.setPlaceholderText("Camada de ponto do destino")
        self.outputFileEdit.setPlaceholderText("Escolha onde salvar os resultados")
        self.progressBar.setTextVisible(False)

    def start_map_pick(self, target):
        if not self.iface:
            QMessageBox.warning(self, self.text_for("map_unavailable_title"), self.text_for("map_unavailable_text"))
            return

        canvas = self.iface.mapCanvas()
        self._previous_map_tool = canvas.mapTool()
        self._map_tool = QgsMapToolEmitPoint(canvas)
        self._map_tool.canvasClicked.connect(lambda point, button: self.finish_map_pick(target, point))
        canvas.setMapTool(self._map_tool)
        label = self.text_for("start") if target == "start" else self.text_for("end")
        QMessageBox.information(
            self,
            self.text_for("pick_point_title"),
            self.text_for("pick_point_text").format(label=label),
        )

    def finish_map_pick(self, target, point):
        text = f"{point.x():.8f}, {point.y():.8f}"
        if target == "start":
            self.startCoordEdit.setText(text)
            self.startPointEdit.clear()
        else:
            self.endCoordEdit.setText(text)
            self.endPointEdit.clear()

        if self.iface and self._previous_map_tool:
            self.iface.mapCanvas().setMapTool(self._previous_map_tool)
        self._map_tool = None

    def parse_coordinate_text(self, text):
        raw = text.strip()
        if not raw:
            return None
        if ";" in raw:
            parts = raw.split(";")
        elif "," in raw and raw.count(",") == 1:
            parts = raw.split(",")
        else:
            parts = raw.split()
        parts = [part.strip().strip(",") for part in parts if part.strip().strip(",")]
        if len(parts) != 2:
            raise ValueError(self.text_for("coordinate_format_error"))
        return float(parts[0].replace(",", ".")), float(parts[1].replace(",", "."))

    def create_point_file_from_coordinate(self, coordinate, prefix):
        project_crs = QgsProject.instance().crs()
        if not project_crs.isValid():
            project_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        target_crs = QgsCoordinateReferenceSystem("EPSG:4326")

        if project_crs != target_crs:
            transform = QgsCoordinateTransform(project_crs, target_crs, QgsProject.instance())
            transformed_point = transform.transform(coordinate[0], coordinate[1])
            x, y = transformed_point.x(), transformed_point.y()
        else:
            x, y = coordinate

        temp_file = tempfile.NamedTemporaryFile(
            prefix=f"topotrail_{prefix}_",
            suffix=".geojson",
            delete=False,
            mode="w",
            encoding="utf-8",
        )
        payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {"type": "Point", "coordinates": [x, y]},
                }
            ],
        }
        json.dump(payload, temp_file)
        temp_file.close()
        self._temp_point_files.append(temp_file.name)
        return temp_file.name

    def resolve_route_points(self):
        start_file = self.startPointEdit.text().strip()
        end_file = self.endPointEdit.text().strip()
        start_coord_text = self.startCoordEdit.text().strip()
        end_coord_text = self.endCoordEdit.text().strip()

        if start_file and start_coord_text:
            raise ValueError(self.text_for("start_input_conflict"))
        if end_file and end_coord_text:
            raise ValueError(self.text_for("end_input_conflict"))

        if start_coord_text:
            start_file = self.create_point_file_from_coordinate(self.parse_coordinate_text(start_coord_text), "origem")
        if end_coord_text:
            end_file = self.create_point_file_from_coordinate(self.parse_coordinate_text(end_coord_text), "destino")

        if bool(start_file) != bool(end_file):
            raise ValueError(self.text_for("route_pair_required"))
        return start_file, end_file

    def style_score_layer(self, layer):
        provider = layer.dataProvider()
        shader = QgsRasterShader()
        ramp = QgsColorRampShader()
        ramp.setColorRampType(QgsColorRampShader.Interpolated)
        ramp.setColorRampItemList([
            QgsColorRampShader.ColorRampItem(0.00, QColor(244, 241, 222, 0), "Baixa"),
            QgsColorRampShader.ColorRampItem(0.62, QColor(255, 245, 210, 0), "Moderada baixa"),
            QgsColorRampShader.ColorRampItem(0.74, QColor(255, 215, 96, 45), "Moderada"),
            QgsColorRampShader.ColorRampItem(0.84, QColor(255, 154, 46, 95), "Alta"),
            QgsColorRampShader.ColorRampItem(0.92, QColor(232, 74, 39, 150), "Muito alta"),
            QgsColorRampShader.ColorRampItem(1.00, QColor(180, 29, 75, 210), "Maxima"),
        ])
        shader.setRasterShaderFunction(ramp)
        renderer = QgsSingleBandPseudoColorRenderer(provider, 1, shader)
        transparency = QgsRasterTransparency()
        transparent_ranges = []
        for low, high, percent in [
            (0.00, 0.70, 100.0),
            (0.70, 0.78, 85.0),
            (0.78, 0.86, 60.0),
            (0.86, 0.93, 35.0),
            (0.93, 1.00, 10.0),
        ]:
            pixel = QgsRasterTransparency.TransparentSingleValuePixel()
            pixel.min = low
            pixel.max = high
            pixel.percentTransparent = percent
            pixel.includeMinimum = True
            pixel.includeMaximum = True
            transparent_ranges.append(pixel)
        transparency.setTransparentSingleValuePixelList(transparent_ranges)
        renderer.setRasterTransparency(transparency)
        renderer.setOpacity(0.85)
        layer.setRenderer(renderer)
        layer.triggerRepaint()

    def style_risk_layer(self, layer):
        provider = layer.dataProvider()
        shader = QgsRasterShader()
        ramp = QgsColorRampShader()
        ramp.setColorRampType(QgsColorRampShader.Interpolated)
        ramp.setColorRampItemList([
            QgsColorRampShader.ColorRampItem(0.00, QColor(255, 255, 255, 0), "Baixo"),
            QgsColorRampShader.ColorRampItem(0.35, QColor(255, 250, 220, 0), "Moderado baixo"),
            QgsColorRampShader.ColorRampItem(0.55, QColor(255, 196, 79, 65), "Moderado"),
            QgsColorRampShader.ColorRampItem(0.72, QColor(255, 112, 67, 135), "Alto"),
            QgsColorRampShader.ColorRampItem(0.86, QColor(211, 47, 47, 190), "Muito alto"),
            QgsColorRampShader.ColorRampItem(1.00, QColor(96, 28, 128, 230), "Critico"),
        ])
        shader.setRasterShaderFunction(ramp)
        renderer = QgsSingleBandPseudoColorRenderer(provider, 1, shader)
        transparency = QgsRasterTransparency()
        transparent_ranges = []
        for low, high, percent in [
            (0.00, 0.45, 100.0),
            (0.45, 0.60, 70.0),
            (0.60, 0.75, 40.0),
            (0.75, 1.00, 8.0),
        ]:
            pixel = QgsRasterTransparency.TransparentSingleValuePixel()
            pixel.min = low
            pixel.max = high
            pixel.percentTransparent = percent
            pixel.includeMinimum = True
            pixel.includeMaximum = True
            transparent_ranges.append(pixel)
        transparency.setTransparentSingleValuePixelList(transparent_ranges)
        renderer.setRasterTransparency(transparency)
        renderer.setOpacity(0.88)
        layer.setRenderer(renderer)
        layer.triggerRepaint()

    def style_zone_layer(self, layer):
        symbol = QgsFillSymbol.createSimple({
            "color": "255, 176, 46, 70",
            "outline_color": "120, 45, 18, 240",
            "outline_width": "0.30",
        })
        layer.renderer().setSymbol(symbol)
        layer.setOpacity(1.0)
        layer.triggerRepaint()

    def style_route_layer(self, layer):
        symbol = QgsLineSymbol.createSimple({
            "color": "236, 28, 132, 255",
            "width": "1.10",
            "capstyle": "round",
            "joinstyle": "round",
        })
        layer.renderer().setSymbol(symbol)
        layer.triggerRepaint()

    def style_corridor_layer(self, layer):
        symbol = QgsFillSymbol.createSimple({
            "color": "0, 178, 214, 55",
            "outline_color": "0, 83, 120, 210",
            "outline_width": "0.28",
        })
        layer.renderer().setSymbol(symbol)
        layer.setOpacity(0.70)
        layer.triggerRepaint()

    def cleanup_temp_point_files(self):
        for path in self._temp_point_files:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        self._temp_point_files = []

    def _take_widget(self, layout, widget):
        for index in range(layout.count() - 1, -1, -1):
            item = layout.itemAt(index)
            if item and item.widget() is widget:
                layout.takeAt(index)
                return

    def _split_parameter_panel(self):
        old_group = self.paramsGroup
        old_layout = self.paramsGroup.layout()
        if old_layout is None:
            return old_group

        rows = []
        while old_layout.count():
            label_item = old_layout.takeAt(0)
            field_item = old_layout.takeAt(0) if old_layout.count() else None
            label = label_item.widget() if label_item else None
            field = field_item.widget() if field_item else None
            if label and field:
                rows.append((label, field))

        old_group.hide()
        self._oldParamsGroup = old_group
        new_group = QGroupBox(old_group.title(), self)
        wrapper = QHBoxLayout()
        wrapper.setSpacing(12)

        terrain_form = QFormLayout()
        terrain_form.setLabelAlignment(ALIGN_RIGHT)
        terrain_form.setFieldGrowthPolicy(FORM_GROW_ALL_NON_FIXED)

        weights_form = QFormLayout()
        weights_form.setLabelAlignment(ALIGN_RIGHT)
        weights_form.setFieldGrowthPolicy(FORM_GROW_ALL_NON_FIXED)

        weight_names = {
            "weightAltSpin",
            "weightSlopeSpin",
            "weightCurvHSpin",
            "weightCurvVSpin",
        }
        for label, field in rows:
            target = weights_form if field.objectName() in weight_names else terrain_form
            target.addRow(label, field)

        wrapper.addLayout(terrain_form, 1)
        wrapper.addLayout(weights_form, 1)
        new_group.setLayout(wrapper)
        return new_group

    def browse_file(self, line_edit_name, file_filter):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.text_for("select_file"),
            "",
            file_filter
        )
        if file_path:
            getattr(self, line_edit_name).setText(file_path)

    def browse_output(self):
        format_map = {
            "Shapefile": "*.shp",
            "GeoPackage": "*.gpkg",
            "KML": "*.kml",
        }

        selected_format = self.formatComboBox.currentText()
        file_filter = f"{selected_format} ({format_map[selected_format]})"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.text_for("save_file"),
            "",
            file_filter
        )
        if file_path:
            extension = format_map[selected_format].replace("*", "")
            if not file_path.lower().endswith(extension):
                file_path = f"{file_path}{extension}"
            self.outputFileEdit.setText(file_path)

    def update_crs_label(self, line_edit_name, label_name):
        path = getattr(self, line_edit_name).text()
        label = getattr(self, label_name)
        if not path or not os.path.exists(path):
            label.setText("CRS: -")
            label.setToolTip("CRS ainda nao detectado.")
            label.setStyleSheet("")
            return

        layer = QgsRasterLayer(path, "tmp")
        if not layer.isValid() or not layer.crs().isValid():
            label.setText("CRS: Indefinido!")
            label.setToolTip("Defina um CRS valido antes de processar.")
            label.setStyleSheet("")
        else:
            label.setText(f"CRS: {layer.crs().authid()}")
            label.setToolTip(f"CRS detectado: {layer.crs().authid()}")
            label.setStyleSheet("")

    def select_crs(self, line_edit_name, label_name):
        dlg = QgsProjectionSelectionDialog()
        if self._dialog_exec(dlg):
            crs = dlg.crs()
            self.outputCrsSelector.setCrs(crs)
            self.update_crs_label(line_edit_name, label_name)
            QMessageBox.information(
                self,
                self.text_for("crs_output_title"),
                self.text_for("crs_output_text").format(crs=crs.authid()),
            )

    def generate_trails(self):
        params = None
        feedback = None
        result = None
        if not all([
            self.demFileEdit.text(),
            self.slopeFileEdit.text(),
            self.curvHFileEdit.text(),
            self.curvVFileEdit.text(),
            self.outputFileEdit.text(),
        ]):
            QMessageBox.warning(
                self,
                self.text_for("required_title"),
                self.text_for("required_text"),
            )
            return

        required_rasters = [
            self.demFileEdit.text().strip(),
            self.slopeFileEdit.text().strip(),
            self.curvHFileEdit.text().strip(),
            self.curvVFileEdit.text().strip(),
        ]
        for path in required_rasters:
            if not os.path.exists(path):
                QMessageBox.critical(
                    self,
                    self.text_for("file_not_found_title"),
                    self.text_for("file_not_found_text").format(path=path),
                )
                return
            if not path.lower().endswith((".tif", ".tiff")):
                QMessageBox.warning(
                    self,
                    self.text_for("invalid_format_title"),
                    self.text_for("invalid_format_text"),
                )
                return

        altitude_weight_is_zero = self.weightAltSpin.value() == 0
        slope_weight_is_zero = self.weightSlopeSpin.value() == 0
        curv_h_weight_is_zero = self.weightCurvHSpin.value() == 0
        curv_v_weight_is_zero = self.weightCurvVSpin.value() == 0
        terrain_weights_are_zero = altitude_weight_is_zero and slope_weight_is_zero
        curvature_weights_are_zero = curv_h_weight_is_zero and curv_v_weight_is_zero
        all_weights_are_zero = terrain_weights_are_zero and curvature_weights_are_zero

        if all_weights_are_zero:
            QMessageBox.warning(
                self,
                self.text_for("invalid_weights_title"),
                self.text_for("invalid_weights_sum"),
            )
            return
        if any(spin.value() < 0 for spin in [self.weightAltSpin, self.weightSlopeSpin, self.weightCurvHSpin, self.weightCurvVSpin]):
            QMessageBox.warning(
                self,
                self.text_for("invalid_weights_title"),
                self.text_for("invalid_weights_negative"),
            )
            return
        if self.altMinSpin.value() >= self.altMaxSpin.value():
            QMessageBox.warning(
                self,
                self.text_for("invalid_altitude_title"),
                self.text_for("invalid_altitude_text"),
            )
            return
        if self.maxSlopeSpin.value() <= 0 or self.slopeScoreMaxSpin.value() <= 0:
            QMessageBox.warning(
                self,
                self.text_for("invalid_slope_title"),
                self.text_for("invalid_slope_text"),
            )
            return
        if self.minPatchAreaSpin.value() < 0:
            QMessageBox.warning(self, self.text_for("invalid_area_title"), self.text_for("invalid_area_text"))
            return
        if not (0 < self.autoPercentileSpin.value() < 100):
            QMessageBox.warning(
                self,
                self.text_for("invalid_percentile_title"),
                self.text_for("invalid_percentile_text"),
            )
            return
        if self.routeBufferSpin.value() <= 0 or self.routeMarginSpin.value() <= 0:
            QMessageBox.warning(self, self.text_for("invalid_route_title"), self.text_for("invalid_route_text"))
            return

        has_start = bool(self.startPointEdit.text().strip() or self.startCoordEdit.text().strip())
        has_end = bool(self.endPointEdit.text().strip() or self.endCoordEdit.text().strip())
        if has_start != has_end:
            QMessageBox.warning(
                self,
                self.text_for("incomplete_points_title"),
                self.text_for("incomplete_points_text"),
            )
            return

        try:
            for edit in [
                self.demFileEdit,
                self.slopeFileEdit,
                self.curvHFileEdit,
                self.curvVFileEdit,
            ]:
                path = edit.text()
                layer = QgsRasterLayer(path, "tmp")
                if not layer.isValid() or not layer.crs().isValid():
                    QMessageBox.critical(
                        self,
                        self.text_for("undefined_crs_title"),
                        self.text_for("undefined_crs_text").format(path=path),
                    )
                    return

            try:
                start_point_file, end_point_file = self.resolve_route_points()
            except ValueError as point_error:
                QMessageBox.warning(
                    self,
                    self.text_for("incomplete_points_title"),
                    str(point_error),
                )
                return

            for point_path in [start_point_file, end_point_file]:
                if point_path and not os.path.exists(point_path):
                    QMessageBox.critical(
                        self,
                        self.text_for("file_not_found_title"),
                        self.text_for("file_not_found_text").format(path=point_path),
                    )
                    return

            if self.generateZonesCheck.isChecked():
                answer = QMessageBox.question(
                    self,
                    self.text_for("generate_zones_question_title"),
                    self.text_for("generate_zones_question_text"),
                    MESSAGE_YES | MESSAGE_NO,
                    MESSAGE_NO,
                )
                if answer != MESSAGE_YES:
                    return

            dem_layer = QgsRasterLayer(self.demFileEdit.text(), "DEM")
            slope_layer = QgsRasterLayer(self.slopeFileEdit.text(), "Declividade")
            curvh_layer = QgsRasterLayer(self.curvHFileEdit.text(), "Curvatura horizontal")
            curvv_layer = QgsRasterLayer(self.curvVFileEdit.text(), "Curvatura vertical")

            if not all([dem_layer.isValid(), slope_layer.isValid(), curvh_layer.isValid(), curvv_layer.isValid()]):
                QMessageBox.critical(
                    self,
                    self.text_for("load_error_title"),
                    self.text_for("load_error_text"),
                )
                return

            params = {
                "INPUT_DEM": dem_layer,
                "INPUT_SLOPE": slope_layer,
                "INPUT_CURVH": curvh_layer,
                "INPUT_CURVV": curvv_layer,
                "ALT_MIN": self.altMinSpin.value(),
                "ALT_MAX": self.altMaxSpin.value(),
                "SLOPE_MAX": self.maxSlopeSpin.value(),
                "SLOPE_SCORE_MAX": self.slopeScoreMaxSpin.value(),
                "THRESHOLD": self.thresholdSpin.value(),
                "AUTO_PERCENTILE": self.autoPercentileSpin.value(),
                "ALTITUDE_BAND_THRESHOLD": self.altitudeBandThresholdCheck.isChecked(),
                "ALTITUDE_BAND_SIZE_M": self.altitudeBandSizeSpin.value(),
                "WALKABILITY_ZONES": self.walkabilityZonesCheck.isChecked(),
                "MIN_PATCH_AREA_HA": self.minPatchAreaSpin.value(),
                "WEIGHT_ALT": self.weightAltSpin.value(),
                "WEIGHT_SLOPE": self.weightSlopeSpin.value(),
                "WEIGHT_CURVH": self.weightCurvHSpin.value(),
                "WEIGHT_CURVV": self.weightCurvVSpin.value(),
                "START_POINT_FILE": start_point_file,
                "END_POINT_FILE": end_point_file,
                "ROUTE_BUFFER_M": self.routeBufferSpin.value(),
                "ROUTE_MARGIN_M": self.routeMarginSpin.value(),
                "GENERATE_ZONES": self.generateZonesCheck.isChecked(),
                "OUTPUT_FILE": self.outputFileEdit.text(),
                "OUTPUT_FORMAT": self.formatComboBox.currentIndex(),
                "OUTPUT_CRS": self.outputCrsSelector.crs().authid(),
            }

            self.generateButton.setEnabled(False)
            self.progressBar.setRange(0, 0)
            QApplication.processEvents()

            feedback = QgsProcessingFeedback()
            append_gui_diagnostic_log(
                self.outputFileEdit.text(),
                "interface_processamento_enviado",
                parametros=serialize_processing_params(params),
            )
            result = processing.run("topotrail:topotrail", params, feedback=feedback)
            append_gui_diagnostic_log(
                self.outputFileEdit.text(),
                "interface_processamento_recebido",
                resultado=result,
            )

            loaded_layers = []
            has_vector_output = bool(
                result.get("OUTPUT_VECTOR") or result.get("OUTPUT_ROUTE") or result.get("OUTPUT_CORRIDOR")
            )
            if result.get("OUTPUT_RISK_RASTER"):
                risk_layer = QgsRasterLayer(result["OUTPUT_RISK_RASTER"], "Risco topografico TopoTrail")
                if risk_layer.isValid():
                    self.style_risk_layer(risk_layer)
                    QgsProject.instance().addMapLayer(risk_layer)

            if result.get("OUTPUT_SCORE_RASTER") and not has_vector_output:
                score_layer = QgsRasterLayer(result["OUTPUT_SCORE_RASTER"], "Adequabilidade TopoTrail")
                if score_layer.isValid():
                    self.style_score_layer(score_layer)
                    QgsProject.instance().addMapLayer(score_layer)

            if result.get("OUTPUT_VECTOR"):
                vector_layer = QgsVectorLayer(result["OUTPUT_VECTOR"], "Zonas potenciais TopoTrail", "ogr")
                if vector_layer.isValid():
                    self.style_zone_layer(vector_layer)
                    should_load = True
                    feature_count = vector_layer.featureCount()
                    if feature_count > 5000:
                        answer = QMessageBox.question(
                            self,
                            self.text_for("large_layer_title"),
                            self.text_for("large_layer_text").format(count=feature_count),
                            MESSAGE_YES | MESSAGE_NO,
                            MESSAGE_NO,
                        )
                        should_load = answer == MESSAGE_YES
                    if should_load:
                        QgsProject.instance().addMapLayer(vector_layer)
                        loaded_layers.append(vector_layer)

            if result.get("OUTPUT_CORRIDOR"):
                corridor_layer = QgsVectorLayer(result["OUTPUT_CORRIDOR"], "Corredor de acesso TopoTrail", "ogr")
                if corridor_layer.isValid():
                    self.style_corridor_layer(corridor_layer)
                    QgsProject.instance().addMapLayer(corridor_layer)
                    loaded_layers.append(corridor_layer)

            if result.get("OUTPUT_ROUTE"):
                route_layer = QgsVectorLayer(result["OUTPUT_ROUTE"], "Rota sugerida TopoTrail", "ogr")
                if route_layer.isValid():
                    self.style_route_layer(route_layer)
                    QgsProject.instance().addMapLayer(route_layer)
                    loaded_layers.append(route_layer)

            if loaded_layers:
                if self.iface:
                    self.iface.mapCanvas().setExtent(loaded_layers[0].extent())
                QMessageBox.information(
                    self,
                    self.text_for("success_title"),
                    self.text_for("success_vector_text").format(count=len(loaded_layers)),
                )
            elif result.get("OUTPUT_SCORE_RASTER"):
                QMessageBox.information(
                    self,
                    self.text_for("success_title"),
                    self.text_for("success_raster_text"),
                )
            else:
                QMessageBox.warning(
                    self,
                    self.text_for("warning_title"),
                    self.text_for("warning_no_features"),
                )

        except Exception as e:
            log_path = append_gui_diagnostic_log(
                self.outputFileEdit.text(),
                "interface_erro",
                erro=str(e),
                traceback=traceback.format_exc(),
                parametros=serialize_processing_params(params),
                resultado=result,
            )
            QMessageBox.critical(
                self,
                self.text_for("error_title"),
                self.text_for("error_text").format(error=str(e), log_path=log_path),
            )
        finally:
            self.progressBar.setRange(0, 100)
            self.progressBar.setValue(0)
            self.generateButton.setEnabled(True)
            self.cleanup_temp_point_files()
