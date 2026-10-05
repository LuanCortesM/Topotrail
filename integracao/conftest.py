"""Suite de integracao: GDAL e QGIS de verdade, sem nenhum substituto.

A suite de `tests/` e hermetica de proposito -- substitui `osgeo` e `qgis` por
modulos falsos para rodar em qualquer maquina em cinco segundos. O preco e que
ela nao ve nada que dependa do comportamento real do GDAL, e foi exatamente ai
que passou o pior defeito que a auditoria da 1.2.0 encontrou: gravar a saida num
GeoPackage existente apagava as camadas do usuario. Nenhum teste unitario podia
ter pego isso, porque no substituto `GetDriverByName` devolve None.

Esta suite roda o pacote com as bibliotecas de verdade e e pulada inteira onde
elas nao existirem. Roda junto com tests/ (`pytest`) ou sozinha
(`pytest integracao`), com o Python do QGIS.
"""
import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


RECADO_SUBSTITUTO = (
    "ha um duble de osgeo/qgis em sys.modules: algum codigo instalou o substituto "
    "de tests/nucleo_sem_qgis.py fora do import do algoritmo"
)


def _real(nome):
    """Importa de verdade, recusando qualquer substituto deixado por outra suite.

    Testar contra um duble aqui seria pior que nao testar: foi exatamente num
    modulo substituido que passou o pior defeito da 1.2.0 -- gravar a saida num
    GeoPackage existente apagava as camadas do usuario, e no duble
    GetDriverByName devolve None.
    """
    modulo = sys.modules.get(nome)
    if modulo is not None and getattr(modulo, "__topotrail_stub__", False):
        pytest.skip("{}: {}".format(nome, RECADO_SUBSTITUTO), allow_module_level=False)
    try:
        return __import__(nome, fromlist=["*"])
    except Exception:
        return None


@pytest.fixture(scope="session")
def ogr():
    modulo = _real("osgeo.ogr")
    if modulo is None or modulo.GetDriverByName("GPKG") is None:
        pytest.skip("GDAL com driver GPKG nao disponivel")
    modulo.UseExceptions()
    return modulo


@pytest.fixture(scope="session")
def osr():
    modulo = _real("osgeo.osr")
    if modulo is None:
        pytest.skip("GDAL/OSR nao disponivel")
    return modulo


@pytest.fixture(autouse=True)
def idioma_limpo():
    """Devolve o idioma do algoritmo ao padrao entre um teste e outro.

    O idioma vive em QgsSettings, que e estado global do processo: um teste que
    roda em chines deixava o seguinte lendo a legenda em chines, e a falha
    aparecia no teste errado, so quando a suite rodava inteira e nessa ordem.
    """
    try:
        from qgis.core import QgsSettings
    except Exception:
        yield
        return
    chave = "TopoTrail/language"
    anterior = QgsSettings().value(chave, "")
    QgsSettings().setValue(chave, "pt")
    try:
        yield
    finally:
        QgsSettings().setValue(chave, anterior)


@pytest.fixture(scope="session")
def plugin():
    """O pacote do plugin como ele e importado dentro do QGIS."""
    pai = os.path.dirname(RAIZ)
    if pai not in sys.path:
        sys.path.insert(0, pai)
    try:
        modulo = __import__(
            "{}.processing.algorithm".format(os.path.basename(RAIZ)),
            fromlist=["algorithm"])
    except Exception as erro:      # pragma: no cover - depende do ambiente
        pytest.skip("plugin nao importavel fora do QGIS: {}".format(erro))
    return modulo


def _headless():
    caminho = os.path.join(RAIZ, "tools")
    if caminho not in sys.path:
        sys.path.insert(0, caminho)
    import qgis_headless
    return qgis_headless


@pytest.fixture(scope="session")
def qgis_app():
    """QGIS headless de verdade, para rodar o algoritmo e a janela de ponta a ponta.

    Sobe um QgsApplication com interface (plataforma offscreen) no proprio
    processo do pytest. Prefixo e pasta de plugins vem de tools/qgis_headless.py,
    que resolve os dois em Windows, Linux e macOS.
    """
    nucleo = _real("qgis.core")
    if nucleo is None:
        pytest.skip("QGIS nao disponivel")
    return _headless().iniciar(gui=True)


@pytest.fixture(scope="session")
def processing_qgis(qgis_app):
    """O Processing do QGIS inicializado (a janela do plugin importa qgis.processing)."""
    try:
        return _headless().processing_do_qgis()
    except ImportError as erro:
        pytest.skip("Processing do QGIS nao encontrado: {}".format(erro))


@pytest.fixture(scope="session")
def executar(qgis_app, plugin):
    """Roda o algoritmo completo e devolve (resultado, feedback, excecao)."""
    nucleo = _real("qgis.core")

    class _Feedback(nucleo.QgsProcessingFeedback):
        def __init__(self):
            super().__init__()
            self.linhas = []

        def pushInfo(self, mensagem):
            self.linhas.append(mensagem)

        def pushWarning(self, mensagem):
            self.linhas.append("AVISO: " + mensagem)

        def reportError(self, mensagem, fatal=False):
            self.linhas.append("ERRO: " + mensagem)

        def procurar(self, *chaves):
            return [linha for linha in self.linhas
                    if any(chave in linha for chave in chaves)]

    def _executar(parametros):
        # Chama processAlgorithm direto, e nao QgsProcessingAlgorithm.run():
        # run() converte qualquer excecao em (None, False) e o tipo do erro --
        # que e justamente o que a correcao das excecoes nuas fixa -- se perde.
        algoritmo = plugin.TopotrailAlgorithm()
        algoritmo.initAlgorithm()
        contexto = nucleo.QgsProcessingContext()
        feedback = _Feedback()
        try:
            resultado = algoritmo.processAlgorithm(parametros, contexto, feedback)
        except Exception as erro:
            return None, feedback, erro
        return resultado, feedback, None

    return _executar
