"""Apoio da interface: estilos de camada, coleta de pontos no mapa e log.

Separado do dialogo porque nada disso depende de como a janela e organizada.
O assistente novo reaproveita este modulo inteiro; o unico motivo de ele existir
como arquivo proprio e que o dialogo foi reescrito e estas partes nao tinham por
que ser reescritas junto.
"""

import json
import os
import tempfile
import traceback
from datetime import datetime

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
    QgsMarkerSymbol,
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



class TopotrailSupportMixin:
    """Estilos das camadas de saida e coleta de coordenadas no mapa."""

    # O dialogo fornece os widgets; o mixin nao conhece os nomes deles. A versao
    # anterior acessava self.startPointEdit diretamente, o que amarrava este
    # codigo a um layout especifico e quebrou assim que a janela foi reescrita.
    def route_widgets(self, target):
        """Devolve (campo_de_arquivo, campo_de_coordenada) para 'start'/'end'."""
        raise NotImplementedError

    def start_map_pick(self, target):
        if not self.iface:
            QMessageBox.warning(self, self.t("err_title"), self.t("err_no_canvas"))
            return

        canvas = self.iface.mapCanvas()
        self._previous_map_tool = canvas.mapTool()
        self._map_tool = QgsMapToolEmitPoint(canvas)
        self._map_tool.canvasClicked.connect(lambda point, button: self.finish_map_pick(target, point))
        canvas.setMapTool(self._map_tool)
        label = self.t("start") if target == "start" else self.t("end")
        QMessageBox.information(
            self, label,
            self.t("pick_prompt").format(label=label))

    def finish_map_pick(self, target, point):
        file_row, coord_edit = self.route_widgets(target)
        coord_edit.setText(f"{point.x():.8f}, {point.y():.8f}")
        file_row.setText("")

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
            raise ValueError(
                "Coordenada precisa ter dois numeros: X, Y."
                if getattr(self, "lang", "pt") == "pt"
                else "A coordinate needs two numbers: X, Y.")
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
        """Caminho dos arquivos de origem e destino.

        Aceita as duas formas: arquivo escolhido pelo usuario, ou coordenada
        digitada / marcada no mapa, que vira um GeoJSON temporario.
        """
        paths = []
        for target in ("start", "end"):
            file_row, coord_edit = self.route_widgets(target)
            path = file_row.text().strip()
            if path:
                paths.append(path)
                continue
            coordinate = self.parse_coordinate_text(coord_edit.text())
            if coordinate is None:
                paths.append(None)
                continue
            paths.append(self.create_point_file_from_coordinate(coordinate, target))
        return paths[0], paths[1]

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

    def style_crossings_layer(self, layer):
        """Travessias de cursos d'agua: triangulo de atencao, rotulado com o numero."""
        symbol = QgsMarkerSymbol.createSimple({
            "name": "triangle",
            "color": "255, 196, 0, 255",
            "outline_color": "120, 60, 0, 255",
            "outline_width": "0.4",
            "size": "4.2",
        })
        layer.renderer().setSymbol(symbol)
        try:
            from qgis.core import QgsPalLayerSettings, QgsVectorLayerSimpleLabeling, QgsTextFormat
            settings = QgsPalLayerSettings()
            settings.fieldName = "n"
            settings.enabled = True
            fmt = QgsTextFormat(); fmt.setSize(9)
            settings.setFormat(fmt)
            layer.setLabelsEnabled(True)
            layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
        except Exception:
            pass
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

