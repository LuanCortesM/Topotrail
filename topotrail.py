import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication, QgsProcessingProvider

from .processing.algorithm import TopotrailAlgorithm
from .ui.topotrail_dialog import TopotrailDialog


class TopotrailProvider(QgsProcessingProvider):
    def loadAlgorithms(self, *args, **kwargs):
        self.addAlgorithm(TopotrailAlgorithm())

    def id(self):
        return "topotrail"

    def name(self):
        return "TopoTrail"

    def longName(self):
        return "TopoTrail - Trilhas e Acessos em Unidades de Conservacao"


class TopotrailPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dlg = None
        self.provider = None
        self.action = None

    def initGui(self):
        """Inicializa a interface grafica do plugin."""
        icon_path = os.path.join(os.path.dirname(__file__), "logo.png")
        self.action = QAction(
            QIcon(icon_path),
            "TopoTrail - Planejamento de Trilhas e Acessos",
            self.iface.mainWindow(),
        )
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("TopoTrail", self.action)
        self.iface.addToolBarIcon(self.action)

        self.provider = TopotrailProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        """Remove o plugin da interface do QGIS."""

        if self.action:
            self.iface.removePluginMenu("TopoTrail", self.action)
            self.iface.removeToolBarIcon(self.action)

        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)

    def run(self):
        """Executa a interface principal do plugin."""
        if not self.dlg:
            self.dlg = TopotrailDialog(self.iface)
        self.dlg.show()
