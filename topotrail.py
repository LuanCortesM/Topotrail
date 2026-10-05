import os

from qgis.PyQt.QtGui import QIcon

try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication, QgsProcessingProvider

from .processing.algorithm import TopotrailAlgorithm, _algorithm_language


class TopotrailProvider(QgsProcessingProvider):
    def loadAlgorithms(self, *args, **kwargs):
        self.addAlgorithm(TopotrailAlgorithm())

    def id(self):
        return "topotrail"

    def name(self):
        return "TopoTrail"

    def longName(self):
        return "TopoTrail - Trails and access routes in natural and protected areas"


class TopotrailPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dlg = None
        self.provider = None
        self.action = None

    def initProcessing(self):
        """Registra o provider de Processing.

        O QGIS chama isto tambem sem interface -- qgis_process e QGIS Server --,
        para plugins que declaram hasProcessingProvider. Sem este metodo o
        algoritmo nao existia na linha de comando.
        """
        if self.provider is None:
            self.provider = TopotrailProvider()
            QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        """Inicializa a interface grafica do plugin."""
        self.initProcessing()
        try:
            from .ui import i18n
            texto = i18n.text(_algorithm_language(), "menu_action")
        except Exception:
            texto = "TopoTrail"
        icon_path = os.path.join(os.path.dirname(__file__), "logo.png")
        self.action = QAction(QIcon(icon_path), texto, self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("TopoTrail", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        """Remove o plugin do QGIS: janela, menu, botao e provider.

        A janela e destruida aqui, e nao deixada para o fim do processo: um
        QDialog que sobrevive ao plugin derrubava o Python ao sair (0xC0000005)
        e, numa recarga, ficava aberto apontando para modulos ja descarregados.
        """
        if self.dlg is not None:
            self.dlg.shutdown()
            self.dlg.deleteLater()
            self.dlg = None
        if self.action is not None:
            self.iface.removePluginMenu("TopoTrail", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

    def run(self):
        """Executa a interface principal do plugin."""
        if self.dlg is None:
            # Importada so aqui: qgis_process e o QGIS Server carregam o
            # plugin apenas pelo Processing e nao precisam da janela.
            from .ui.topotrail_dialog import TopotrailDialog
            self.dlg = TopotrailDialog(self.iface)
        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()
