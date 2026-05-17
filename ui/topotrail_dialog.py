import json
import os
import tempfile
import traceback
from datetime import datetime

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QPixmap
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
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
        **data,
    }
    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    return log_path


class TopotrailDialog(QDialog, FORM_CLASS):
    def __init__(self, iface=None, parent=None):
        super(TopotrailDialog, self).__init__(parent)
        self.iface = iface
        self._map_tool = None
        self._previous_map_tool = None
        self._temp_point_files = []
        self.setupUi(self)

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
        self.maxSlopeSpin.setToolTip("Limite rígido para áreas caminháveis e rota. 55% exclui encostas muito íngremes; aumente se uma rota de montanha ficar bloqueada.")
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
        self.walkabilityZonesCheck = QCheckBox("Zonas = área caminhável contínua")
        self.walkabilityZonesCheck.setChecked(True)
        self.walkabilityZonesCheck.setToolTip(
            "Quando ativo, as zonas mostram tudo que é caminhável segundo altitude e declividade, "
            "em vez de selecionar apenas as células com maior pontuação."
        )
        self.paramsGroup.layout().insertRow(8, "", self.walkabilityZonesCheck)
        self.minPatchAreaSpin = QDoubleSpinBox()
        self.minPatchAreaSpin.setMinimum(0.0)
        self.minPatchAreaSpin.setMaximum(100000.0)
        self.minPatchAreaSpin.setDecimals(2)
        self.minPatchAreaSpin.setSingleStep(0.5)
        self.minPatchAreaSpin.setValue(50.0)
        self.minPatchAreaSpin.setToolTip("Remove fragmentos menores antes de gerar o vetor final. Valores maiores reduzem áreas picotadas no mapa.")
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

    def add_route_section(self):
        route_group = QGroupBox("Planejamento de acesso (opcional)")
        self.routeGroup = route_group
        layout = QFormLayout()

        self.startPointEdit = QLineEdit()
        self.startPointEdit.setReadOnly(True)
        self.startPointBrowseButton = QPushButton("...")
        self.startPointBrowseButton.setFixedWidth(34)
        start_row = QHBoxLayout()
        start_row.addWidget(self.startPointEdit)
        start_row.addWidget(self.startPointBrowseButton)

        self.endPointEdit = QLineEdit()
        self.endPointEdit.setReadOnly(True)
        self.endPointBrowseButton = QPushButton("...")
        self.endPointBrowseButton.setFixedWidth(34)
        end_row = QHBoxLayout()
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

        start_coord_row = QHBoxLayout()
        start_coord_row.addWidget(self.startCoordEdit)
        start_coord_row.addWidget(self.pickStartButton)
        end_coord_row = QHBoxLayout()
        end_coord_row.addWidget(self.endCoordEdit)
        end_coord_row.addWidget(self.pickEndButton)

        self.generateZonesCheck = QCheckBox("Gerar zonas vetoriais")
        self.generateZonesCheck.setChecked(False)
        self.generateZonesCheck.setToolTip(
            "Ative apenas quando precisar do poligono de zonas. Essa etapa pode demorar e gerar muitas feicoes."
        )

        layout.addRow("Ponto inicial (arquivo):", start_row)
        layout.addRow("Ponto final (arquivo):", end_row)
        layout.addRow("Origem (coordenada):", start_coord_row)
        layout.addRow("Destino (coordenada):", end_coord_row)
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
        logo_row.setAlignment(Qt.AlignCenter)
        for filename in [
            "logo_herpeto_mantiqueira.png",
            "logo_enbt.jpg",
            "logo_jbrj.jpg",
        ]:
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumSize(92, 74)
            label.setMaximumSize(150, 86)
            pixmap = QPixmap(os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", filename))
            if not pixmap.isNull():
                label.setPixmap(pixmap.scaled(140, 82, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            logo_row.addWidget(label)
        layout.addLayout(logo_row)

        text = QLabel(
            "<b>TopoTrail</b><br>"
            "Ferramenta para apoiar o planejamento de trilhas, acessos e deslocamentos de campo "
            "em áreas naturais e unidades de conservação, integrando altitude, declividade e "
            "curvaturas do relevo por análise multicritério em SIG.<br><br>"
            "<b>Desenvolvedor:</b> Luan da Silva Cortes Maciel (MACIEL, L. S.)<br>"
            "<b>Orientador:</b> Leandro Freitas<br>"
            "<b>Contexto:</b> desenvolvido como produto da pesquisa de mestrado em Biodiversidade em "
            "Unidades de Conservação, Escola Nacional de Botânica Tropical / Jardim Botânico "
            "do Rio de Janeiro.<br>"
            "<b>Projeto associado:</b> Herpeto Mantiqueira."
        )
        text.setWordWrap(True)
        text.setTextFormat(Qt.RichText)
        layout.addWidget(text)

        about_group.setLayout(layout)
        self.layout().insertWidget(self.layout().count() - 2, about_group)

    def make_layout_more_horizontal(self):
        self.setWindowTitle("TopoTrail - Planejamento de trilhas e acessos")
        self.resize(1120, 700)
        self.setMinimumSize(940, 590)
        self.setSizeGripEnabled(True)

        main_layout = self.layout()
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(10)

        self.logoLabel.setMinimumSize(64, 64)
        self.logoLabel.setMaximumSize(64, 64)
        self.titleLabel.setText("TopoTrail\nPlanejamento de trilhas e acessos")
        self.titleLabel.setWordWrap(True)
        self.rebuild_input_group()

        for edit in [
            self.demFileEdit,
            self.slopeFileEdit,
            self.curvHFileEdit,
            self.curvVFileEdit,
            self.outputFileEdit,
        ]:
            edit.setMinimumWidth(280)
            edit.setMinimumHeight(30)

        for button in [
            self.demBrowseButton,
            self.slopeBrowseButton,
            self.curvHBrowseButton,
            self.curvVBrowseButton,
            self.outputBrowseButton,
        ]:
            button.setFixedWidth(34)
            button.setMinimumHeight(30)

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
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        left_column = QVBoxLayout()
        left_column.setSpacing(10)
        left_column.addWidget(self.inputGroup)
        left_column.addWidget(self.routeGroup)
        left_column.addWidget(self.outputGroup)
        left_column.addStretch(1)

        right_column = QVBoxLayout()
        right_column.setSpacing(10)
        right_column.addWidget(self.paramsGroup)
        right_column.addWidget(self.aboutGroup)
        right_column.addStretch(1)

        content_layout.addLayout(left_column, 3)
        content_layout.addLayout(right_column, 2)

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setWidget(content_widget)
        scroll_area.setMinimumHeight(360)
        scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        main_layout.insertWidget(1, scroll_area, 1)

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
            ("Modelo Digital de Elevacao (MDE):", self.demFileEdit, self.demBrowseButton, self.demCrsLabel),
            ("Declividade:", self.slopeFileEdit, self.slopeBrowseButton, self.slopeCrsLabel),
            ("Curvatura Horizontal:", self.curvHFileEdit, self.curvHBrowseButton, self.curvHCrsLabel),
            ("Curvatura Vertical:", self.curvVFileEdit, self.curvVBrowseButton, self.curvVCrsLabel),
        ]

        for row, (label_text, edit, browse_button, crs_label) in enumerate(rows):
            label = QLabel(label_text)
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            layout.addWidget(label, row, 0)
            layout.addWidget(edit, row, 1)
            layout.addWidget(browse_button, row, 2)
            crs_label.setMinimumWidth(92)
            crs_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            layout.addWidget(crs_label, row, 3)

        new_group.setLayout(layout)
        self.inputGroup = new_group

    def apply_visual_theme(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #eef4e8;
                color: #263526;
                font-family: "Segoe UI", "Arial";
                font-size: 9.5pt;
            }
            QLabel {
                color: #263526;
            }
            QLabel#titleLabel {
                color: #24452d;
                font-size: 24px;
                font-weight: bold;
                padding-left: 6px;
            }
            QLabel#logoLabel {
                background-color: #fbf8ef;
                border: 1px solid #c8d7c3;
                border-radius: 8px;
                padding: 4px;
            }
            QGroupBox {
                background-color: #fbf8ef;
                border: 1px solid #c8d7c3;
                border-radius: 8px;
                margin-top: 20px;
                padding: 16px 12px 12px 12px;
                font-weight: bold;
                color: #2f5334;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 14px;
                padding: 0px 8px;
                background-color: #fbf8ef;
                color: #2f5334;
            }
            QLineEdit, QDoubleSpinBox, QComboBox {
                background-color: #fffdf6;
                border: 1px solid #b9cbb3;
                border-radius: 6px;
                min-height: 28px;
                padding: 3px 7px;
                color: #263526;
            }
            QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus {
                border: 1px solid #6f8f5f;
                background-color: #ffffff;
            }
            QPushButton {
                background-color: #dfead7;
                border: 1px solid #a9bea1;
                border-radius: 6px;
                min-height: 28px;
                padding: 4px 10px;
                color: #2e4a32;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #d2e2ca;
                border-color: #7f9d73;
            }
            QPushButton:pressed {
                background-color: #c3d6ba;
            }
            QPushButton#generateButton {
                background-color: #6f8f5f;
                color: #fffdf6;
                border: 1px solid #55734a;
                min-height: 36px;
                font-size: 10.5pt;
                font-weight: 700;
            }
            QPushButton#generateButton:hover {
                background-color: #628252;
            }
            QProgressBar {
                background-color: #fffdf6;
                border: 1px solid #c8d7c3;
                border-radius: 6px;
                min-height: 18px;
                color: #2f5334;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #b8875a;
                border-radius: 5px;
            }
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QWidget {
                selection-background-color: #b8875a;
            }
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
            form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
            form.setFormAlignment(Qt.AlignTop)

        for spin in self.findChildren(QDoubleSpinBox):
            spin.setMinimumWidth(112)
            spin.setMinimumHeight(30)

        for line_edit in self.findChildren(QLineEdit):
            line_edit.setMinimumHeight(30)

        self.startPointEdit.setPlaceholderText("Camada de ponto da origem")
        self.endPointEdit.setPlaceholderText("Camada de ponto do destino")
        self.outputFileEdit.setPlaceholderText("Escolha onde salvar os resultados")
        self.progressBar.setTextVisible(False)

    def start_map_pick(self, target):
        if not self.iface:
            QMessageBox.warning(self, "Mapa indisponivel", "A captura no mapa so funciona dentro do QGIS.")
            return

        canvas = self.iface.mapCanvas()
        self._previous_map_tool = canvas.mapTool()
        self._map_tool = QgsMapToolEmitPoint(canvas)
        self._map_tool.canvasClicked.connect(lambda point, button: self.finish_map_pick(target, point))
        canvas.setMapTool(self._map_tool)
        label = "origem" if target == "start" else "destino"
        QMessageBox.information(
            self,
            "Marcar ponto",
            f"Clique no mapa para definir a {label}. A coordenada sera registrada no CRS atual do projeto.",
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
            raise ValueError("Use o formato X Y, X; Y ou X, Y para coordenadas.")
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
            raise ValueError("Escolha arquivo ou coordenada para a origem, nao os dois.")
        if end_file and end_coord_text:
            raise ValueError("Escolha arquivo ou coordenada para o destino, nao os dois.")

        if start_coord_text:
            start_file = self.create_point_file_from_coordinate(self.parse_coordinate_text(start_coord_text), "origem")
        if end_coord_text:
            end_file = self.create_point_file_from_coordinate(self.parse_coordinate_text(end_coord_text), "destino")

        if bool(start_file) != bool(end_file):
            raise ValueError("Para gerar rota, informe origem e destino por arquivo ou por coordenada.")
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
        terrain_form.setLabelAlignment(Qt.AlignRight)
        terrain_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        weights_form = QFormLayout()
        weights_form.setLabelAlignment(Qt.AlignRight)
        weights_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

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
            "Selecionar arquivo",
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
            "Salvar arquivo",
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
            label.setStyleSheet("color: #888;")
            return

        layer = QgsRasterLayer(path, "tmp")
        if not layer.isValid() or not layer.crs().isValid():
            label.setText("CRS: Indefinido!")
            label.setStyleSheet("color: red;")
        else:
            label.setText(f"CRS: {layer.crs().authid()}")
            label.setStyleSheet("color: #16402a;")

    def select_crs(self, line_edit_name, label_name):
        dlg = QgsProjectionSelectionDialog()
        if dlg.exec_():
            crs = dlg.crs()
            self.outputCrsSelector.setCrs(crs)
            self.update_crs_label(line_edit_name, label_name)
            QMessageBox.information(
                self,
                "CRS de saida definido",
                f"O CRS de saida foi ajustado para {crs.authid()}. Os rasters de entrada nao foram alterados.",
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
                "Campos obrigatorios",
                "Por favor, preencha todos os campos obrigatorios.",
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
                QMessageBox.critical(self, "Arquivo nao encontrado", f"O arquivo {path} nao existe.")
                return
            if not path.lower().endswith((".tif", ".tiff")):
                QMessageBox.warning(self, "Formato invalido", "Use rasters GeoTIFF com extensao .tif ou .tiff.")
                return

        if (
            self.weightAltSpin.value() == 0
            and self.weightSlopeSpin.value() == 0
            and self.weightCurvHSpin.value() == 0
            and self.weightCurvVSpin.value() == 0
        ):
            QMessageBox.warning(
                self,
                "Pesos invalidos",
                "Defina pelo menos um peso maior que zero. A soma dos pesos nao pode ser igual a zero.",
            )
            return
        if any(spin.value() < 0 for spin in [self.weightAltSpin, self.weightSlopeSpin, self.weightCurvHSpin, self.weightCurvVSpin]):
            QMessageBox.warning(self, "Pesos invalidos", "Os pesos nao podem ser negativos.")
            return
        if self.altMinSpin.value() >= self.altMaxSpin.value():
            QMessageBox.warning(self, "Altitude invalida", "A altitude minima deve ser menor que a altitude maxima.")
            return
        if self.maxSlopeSpin.value() <= 0 or self.slopeScoreMaxSpin.value() <= 0:
            QMessageBox.warning(self, "Declividade invalida", "Os limites de declividade devem ser maiores que zero.")
            return
        if self.minPatchAreaSpin.value() < 0:
            QMessageBox.warning(self, "Area invalida", "A area minima nao pode ser negativa.")
            return
        if not (0 < self.autoPercentileSpin.value() < 100):
            QMessageBox.warning(self, "Percentil invalido", "O percentil automatico deve estar entre 0 e 100.")
            return
        if self.routeBufferSpin.value() <= 0 or self.routeMarginSpin.value() <= 0:
            QMessageBox.warning(self, "Rota invalida", "A largura do corredor e a margem de busca devem ser maiores que zero.")
            return

        has_start = bool(self.startPointEdit.text().strip() or self.startCoordEdit.text().strip())
        has_end = bool(self.endPointEdit.text().strip() or self.endCoordEdit.text().strip())
        if has_start != has_end:
            QMessageBox.warning(
                self,
                "Pontos incompletos",
                "Para gerar rota, informe origem e destino. Para nao gerar rota, deixe ambos vazios.",
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
                    QMessageBox.critical(self, "CRS indefinido", f"O arquivo {path} esta sem CRS definido!")
                    return

            try:
                start_point_file, end_point_file = self.resolve_route_points()
            except ValueError as point_error:
                QMessageBox.warning(
                    self,
                    "Pontos incompletos",
                    str(point_error),
                )
                return

            for point_path in [start_point_file, end_point_file]:
                if point_path and not os.path.exists(point_path):
                    QMessageBox.critical(self, "Arquivo nao encontrado", f"O arquivo {point_path} nao existe.")
                    return

            if self.generateZonesCheck.isChecked():
                answer = QMessageBox.question(
                    self,
                    "Gerar zonas vetoriais?",
                    "A geracao de zonas vetoriais pode demorar varios minutos e deixar o QGIS temporariamente sem resposta. "
                    "Para planejar acesso, normalmente basta gerar raster, rota e corredor. Deseja continuar com as zonas?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    return

            dem_layer = QgsRasterLayer(self.demFileEdit.text(), "DEM")
            slope_layer = QgsRasterLayer(self.slopeFileEdit.text(), "Declividade")
            curvh_layer = QgsRasterLayer(self.curvHFileEdit.text(), "Curvatura horizontal")
            curvv_layer = QgsRasterLayer(self.curvVFileEdit.text(), "Curvatura vertical")

            if not all([dem_layer.isValid(), slope_layer.isValid(), curvh_layer.isValid(), curvv_layer.isValid()]):
                QMessageBox.critical(
                    self,
                    "Erro",
                    "Um ou mais rasters nao puderam ser carregados. Verifique se os arquivos sao validos.",
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
                            "Camada vetorial grande",
                            f"As zonas potenciais geraram {feature_count} feicoes. Carregar tudo agora pode deixar o mapa lento. "
                            "Deseja carregar a camada mesmo assim?",
                            QMessageBox.Yes | QMessageBox.No,
                            QMessageBox.No,
                        )
                        should_load = answer == QMessageBox.Yes
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
                    "Sucesso",
                    f"Processamento concluido. {len(loaded_layers)} camada(s) vetorial(is) carregada(s).",
                )
            elif result.get("OUTPUT_SCORE_RASTER"):
                QMessageBox.information(
                    self,
                    "Sucesso",
                    "Raster continuo de adequabilidade gerado. Para gerar poligonos de zonas potenciais, marque a opcao "
                    "'Gerar zonas vetoriais' antes de processar.",
                )
            else:
                QMessageBox.warning(
                    self,
                    "Aviso",
                    "Processamento concluido, mas nenhuma feicao foi gerada.",
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
                "Erro",
                f"Erro ao gerar trilhas: {str(e)}\n\nLog diagnostico salvo em:\n{log_path}",
            )
        finally:
            self.progressBar.setRange(0, 100)
            self.progressBar.setValue(0)
            self.generateButton.setEnabled(True)
            self.cleanup_temp_point_files()
