"""QGIS sem janela, a partir de qualquer instalacao: Windows, Linux ou macOS.

Usado pelo exemplo (`exemplo/executar.py`), pela validacao
(`validation/entorno.py`) e pela suite de integracao. Resolve as tres coisas que
um script fora do QGIS precisa e que mudam de sistema para sistema:

* o prefixo da instalacao: QGIS_PREFIX_PATH, ou deduzido do proprio Python
  (OSGeo4W e instalador do Windows, QGIS.app no macOS, /usr no Linux);
* a pasta de plugins do QGIS, onde mora o modulo `processing`: perguntada ao
  proprio QGIS (`pkgDataPath`), e nao escrita como caminho de Linux;
* a colisao de nomes: o plugin tem um subpacote `processing`, e com a raiz do
  repositorio no sys.path `import processing` acharia o dele.

Importa so a biblioteca padrao no topo; o QGIS entra dentro das funcoes.
"""

import os
import sys
import tempfile


def prefixo():
    """Prefixo da instalacao do QGIS em uso."""
    definido = os.environ.get("QGIS_PREFIX_PATH")
    if definido:
        return definido
    if sys.platform == "win32":
        apps = os.path.dirname(sys.prefix)        # <raiz>/apps/Python3xx
        for nome in ("qgis", "qgis-ltr", "qgis-qt6", "qgis-dev"):
            if os.path.isdir(os.path.join(apps, nome, "python", "qgis")):
                return os.path.join(apps, nome)
    if sys.platform == "darwin":
        # QGIS.app/Contents/MacOS/bin/python3 -> QGIS.app/Contents/MacOS
        macos = os.path.dirname(os.path.dirname(os.path.realpath(sys.executable)))
        if os.path.isdir(os.path.join(os.path.dirname(macos), "Resources", "python")):
            return macos
    return "/usr"


def iniciar(gui=False):
    """QgsApplication pronto (ou o que ja existir no processo)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if sys.platform.startswith("linux") and not os.environ.get("XDG_RUNTIME_DIR"):
        # Sem isto o Qt reclama em toda execucao sem sessao grafica; o
        # diretorio precisa ser so do usuario (0700) para o aviso sumir.
        runtime = os.path.join(tempfile.gettempdir(),
                               "topotrail-runtime-{}".format(os.getuid()))
        try:
            os.makedirs(runtime, mode=0o700, exist_ok=True)
            os.chmod(runtime, 0o700)
            os.environ["XDG_RUNTIME_DIR"] = runtime
        except OSError:
            pass
    from qgis.core import QgsApplication

    aplicacao = QgsApplication.instance()
    if aplicacao is None:
        aplicacao = QgsApplication([], gui)
        QgsApplication.setPrefixPath(prefixo(), True)
        aplicacao.initQgis()
    return aplicacao


def pasta_de_plugins():
    """A pasta python/plugins do QGIS, a que contem `processing`."""
    from qgis.core import QgsApplication

    base = prefixo()
    candidatos = (
        os.path.join(QgsApplication.pkgDataPath(), "python", "plugins"),
        os.path.join(base, "python", "plugins"),
        os.path.join(base, "share", "qgis", "python", "plugins"),
        "/usr/share/qgis/python/plugins",
    )
    for candidato in candidatos:
        if os.path.isfile(os.path.join(candidato, "processing", "__init__.py")):
            return os.path.normpath(candidato)
    return None


def processing_do_qgis():
    """Importa e inicializa o Processing do QGIS -- e nao o subpacote do plugin."""
    pasta = pasta_de_plugins()
    if pasta is None:
        raise ImportError(
            "Nao encontrei a pasta de plugins do QGIS (a que contem 'processing'). "
            "Defina QGIS_PREFIX_PATH com o prefixo da instalacao.")
    if pasta in sys.path:
        sys.path.remove(pasta)
    sys.path.insert(0, pasta)
    atual = sys.modules.get("processing")
    arquivo = os.path.abspath(getattr(atual, "__file__", None) or "")
    if atual is not None and not arquivo.startswith(pasta + os.sep):
        for nome in [n for n in list(sys.modules)
                     if n == "processing" or n.startswith("processing.")]:
            del sys.modules[nome]
    import processing
    from processing.core.Processing import Processing

    Processing.initialize()
    return processing


def registrar_topotrail(raiz):
    """Registra o provider do TopoTrail a partir de um checkout, sem instalar.

    O pacote e importado pelo nome da pasta, como o QGIS faz com um plugin.
    """
    from qgis.core import QgsApplication

    pai = os.path.dirname(os.path.abspath(raiz))
    if pai not in sys.path:
        sys.path.insert(0, pai)
    pacote = __import__("{}.topotrail".format(os.path.basename(os.path.abspath(raiz))),
                        fromlist=["topotrail"])
    registro = QgsApplication.processingRegistry()
    if registro.providerById("topotrail") is None:
        provider = pacote.TopotrailProvider()
        registro.addProvider(provider)
        # O registro guarda uma referencia fraca: sem esta, o provider e
        # coletado e o algoritmo some.
        registrar_topotrail.provider = provider
    return registro.algorithmById("topotrail:topotrail")
