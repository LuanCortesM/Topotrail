"""A janela do plugin, usada como o usuario usa, no QGIS de verdade.

Carrega o plugin por classFactory/initGui, preenche os quatro passos, clica em
Executar e espera a QgsProcessingAlgRunnerTask terminar. Foi assim que
apareceram dois defeitos que nenhum teste do algoritmo via: o log da janela era
escrito da thread da tarefa (proibido no Qt) e cancelar terminava numa caixa de
erro.
"""
import importlib
import os
import time

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def iface_simulado():
    """QgisInterface de mentira, sem efeito colateral.

    Nao e qgis.testing.mocked.get_iface(): ela chama start_app(), que com um
    QGIS ja aberto cria um segundo QgsApplication e registra um exitQgis que
    derruba o processo na saida.
    """
    from unittest import mock

    iface = mock.MagicMock()
    iface.mainWindow.return_value = None
    return iface
EXEMPLO = os.path.join(RAIZ, "exemplo")
LIMITE_S = 300


@pytest.fixture()
def janela(qgis_app, processing_qgis, plugin, monkeypatch):
    from qgis.PyQt.QtWidgets import QMessageBox
    from qgis.core import QgsProject

    caixas = []
    for tipo in ("information", "warning", "critical"):
        monkeypatch.setattr(
            QMessageBox, tipo,
            staticmethod(lambda *a, _t=tipo, **k: caixas.append((_t, a[2] if len(a) > 2 else ""))))

    pacote = __import__(os.path.basename(RAIZ))
    extensao = pacote.classFactory(iface_simulado())
    extensao.initGui()
    modulo = importlib.import_module(os.path.basename(RAIZ) + ".ui.topotrail_dialog")
    dialogo = modulo.TopotrailDialog(extensao.iface)
    dialogo.resize(940, 720)
    dialogo.show()
    qgis_app.processEvents()
    yield dialogo, caixas
    dialogo.shutdown()
    dialogo.deleteLater()
    extensao.unload()
    qgis_app.processEvents()
    QgsProject.instance().removeAllMapLayers()


def _preencher(dialogo, saida):
    dialogo.dem_file.set_path(os.path.join(EXEMPLO, "mde.tif"))
    dialogo.want_route.setChecked(True)
    dialogo.start_file.setText(os.path.join(EXEMPLO, "origem.geojson"))
    dialogo.end_file.setText(os.path.join(EXEMPLO, "destino.geojson"))
    dialogo.output_edit.setText(saida)


def _esperar(app, condicao):
    inicio = time.time()
    while not condicao() and time.time() - inicio < LIMITE_S:
        app.processEvents()
        time.sleep(0.02)
    assert condicao(), "a tarefa nao terminou em {} s".format(LIMITE_S)


def test_a_janela_roda_e_carrega_as_camadas(janela, qgis_app, tmp_path):
    from qgis.PyQt.QtCore import QThread
    from qgis.core import QgsProject

    dialogo, caixas = janela
    _preencher(dialogo, str(tmp_path / "janela.gpkg"))
    threads = []
    original = dialogo._log_line
    dialogo._log_line = lambda texto: (threads.append(
        QThread.currentThread() == qgis_app.thread()), original(texto))
    for _ in range(3):
        dialogo.next_button.click()
        qgis_app.processEvents()
    assert dialogo.stack.currentIndex() == 3, caixas
    dialogo.next_button.click()
    _esperar(qgis_app, lambda: dialogo._task is None and caixas)

    assert caixas[-1][0] == "information", caixas
    nomes = [camada.name() for camada in QgsProject.instance().mapLayers().values()]
    assert len(nomes) >= 5, nomes
    assert threads and all(threads), "o log da janela foi escrito fora da thread da interface"
    assert (tmp_path / "janela_rota.gpkg").is_file()


def test_cancelar_nao_termina_em_erro(janela, qgis_app, tmp_path):
    dialogo, caixas = janela
    _preencher(dialogo, str(tmp_path / "cancelada.gpkg"))
    for _ in range(3):
        dialogo.next_button.click()
        qgis_app.processEvents()
    dialogo.next_button.click()          # Executar
    dialogo.next_button.click()          # Cancelar
    # Ou a tarefa ainda corre e o botao esta desligado, ou ela ja foi encerrada
    # (uma tarefa que nao comecou termina dentro de cancel()) e o botao voltou.
    assert dialogo._task is None or not dialogo.next_button.isEnabled()
    _esperar(qgis_app, lambda: dialogo._task is None)
    assert not [c for c in caixas if c[0] == "critical"], caixas
    assert dialogo.next_button.isEnabled()


def test_nenhum_texto_fica_cortado_em_nenhum_idioma(janela, qgis_app):
    """O defeito ja voltou varias vezes: largura medida com o texto de outro
    idioma, com o peso normal da fonte, ou com a fonte padrao em vez da da
    folha de estilo ("Produtos" cortado no Qt5 do Windows)."""
    from qgis.PyQt.QtWidgets import QComboBox, QLabel, QPushButton

    dialogo, _ = janela
    problemas = []
    for codigo in ("pt", "en", "es", "fr", "zh", "ja"):
        dialogo.language_box.setCurrentIndex(dialogo.language_box.findData(codigo))
        dialogo.want_route.setChecked(True)
        qgis_app.processEvents()
        for passo in range(4):
            dialogo.stack.setCurrentIndex(passo)
            qgis_app.processEvents()
            for widget in dialogo.findChildren(QLabel) + dialogo.findChildren(QPushButton):
                if not widget.text() or not widget.isVisible():
                    continue
                if isinstance(widget, QLabel) and widget.wordWrap():
                    continue
                if widget.width() < widget.sizeHint().width() - 1:
                    problemas.append("{} passo {}: '{}'".format(codigo, passo + 1, widget.text()[:30]))
            for caixa in dialogo.findChildren(QComboBox):
                if caixa.isVisible() and caixa.count() and caixa.width() < caixa.sizeHint().width() - 1:
                    problemas.append("{} passo {}: opcao '{}'".format(
                        codigo, passo + 1, caixa.currentText()[:30]))
    assert not problemas, problemas
