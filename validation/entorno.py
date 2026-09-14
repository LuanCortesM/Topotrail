"""Entorno de execucao dos scripts de validacao, sem caminho de ninguem dentro.

Existe por dois defeitos apontados na auditoria:

* os scripts de `validation/` traziam caminhos absolutos da maquina de
  desenvolvimento (`/home/claude/work/exp`, `/mnt/user-data/uploads/...`), de
  modo que nao rodavam em maquina nenhuma alem daquela;
* `bateria_regioes.py` importava `qgis_env`, um modulo que nunca existiu no
  repositorio -- nem o `import` resolvia para quem clonasse o projeto.

Aqui o QGIS sobe embutido, a partir do proprio repositorio, e todo caminho de
dado vem de argumento de linha de comando ou de variavel de ambiente, com uma
mensagem que diz exatamente o que falta e como informar.
"""
import os
import sys

RAIZ_DO_REPOSITORIO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def iniciar_qgis(prefixo=None):
    """Sobe um QGIS headless com o TopoTrail registrado como provider.

    Substitui o `import qgis_env` que apontava para um modulo ausente. O
    prefixo do QGIS vem de --qgis-prefix / QGIS_PREFIX_PATH e cai em /usr, que
    e onde a instalacao de pacote costuma ficar no Linux.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    runtime = os.environ.setdefault("XDG_RUNTIME_DIR", "/tmp/xdg")
    try:
        os.makedirs(runtime, exist_ok=True)
    except OSError:
        pass

    try:
        from qgis.core import QgsApplication
    except ImportError as erro:
        raise SystemExit(
            "Este script precisa do Python do QGIS. Rode com o interpretador que "
            "tem qgis.core importavel (no Linux, normalmente /usr/bin/python3; no "
            "Windows, o do OSGeo4W).\n  detalhe: {}".format(erro))

    aplicacao = QgsApplication.instance()
    if aplicacao is None:
        aplicacao = QgsApplication([], False)
        QgsApplication.setPrefixPath(
            prefixo or os.environ.get("QGIS_PREFIX_PATH", "/usr"), True)
        aplicacao.initQgis()

    for candidato in ("/usr/share/qgis/python/plugins",
                      os.path.join(os.environ.get("QGIS_PREFIX_PATH", "/usr"),
                                   "share", "qgis", "python", "plugins")):
        if os.path.isdir(candidato) and candidato not in sys.path:
            sys.path.append(candidato)
    try:
        from processing.core.Processing import Processing
        import processing
    except ImportError as erro:
        raise SystemExit(
            "Nao encontrei o plugin Processing do QGIS. Informe o prefixo da "
            "instalacao em QGIS_PREFIX_PATH (padrao /usr).\n  detalhe: {}"
            .format(erro))
    Processing.initialize()

    # O plugin e carregado do proprio repositorio: o pai da raiz entra no
    # sys.path e o pacote e importado pelo nome da pasta, sem copia em
    # /tmp/plugins nem instalacao previa.
    pai = os.path.dirname(RAIZ_DO_REPOSITORIO)
    if pai not in sys.path:
        sys.path.insert(0, pai)
    pacote = __import__(
        "{}.topotrail".format(os.path.basename(RAIZ_DO_REPOSITORIO)),
        fromlist=["topotrail"])
    provedor = pacote.TopotrailProvider()
    QgsApplication.processingRegistry().addProvider(provedor)
    # O provedor precisa sobreviver a saida desta funcao: sem uma referencia
    # viva, o Python o coleta e a Caixa de Ferramentas fica sem o algoritmo.
    iniciar_qgis.provedor = provedor
    return aplicacao, processing


class Dados:
    """Resolve os diretorios de dado por argumento ou variavel de ambiente.

    Cada raiz e declarada uma vez com o que se espera encontrar dentro. Nada e
    adivinhado: o que faltar sai numa lista unica no fim, com o nome do
    argumento, o nome da variavel e os arquivos procurados.
    """

    def __init__(self):
        self._faltando = []

    @staticmethod
    def _valor(nome_do_argumento, variavel, argv=None):
        argv = sys.argv[1:] if argv is None else argv
        prefixo = "--{}=".format(nome_do_argumento)
        for item in argv:
            if item.startswith(prefixo):
                return item[len(prefixo):]
        return os.environ.get(variavel)

    def raiz(self, nome_do_argumento, variavel, descricao, exigidos=()):
        """Devolve o diretorio pedido, ou None registrando o que falta."""
        caminho = self._valor(nome_do_argumento, variavel)
        if not caminho:
            self._faltando.append((nome_do_argumento, variavel, descricao,
                                   "nao informado", exigidos))
            return None
        caminho = os.path.abspath(os.path.expanduser(caminho))
        if not os.path.isdir(caminho):
            self._faltando.append((nome_do_argumento, variavel, descricao,
                                   "nao e um diretorio: " + caminho, exigidos))
            return None
        ausentes = [nome for nome in exigidos
                    if not os.path.exists(os.path.join(caminho, nome))]
        if ausentes:
            self._faltando.append((nome_do_argumento, variavel, descricao,
                                   "faltam em " + caminho, ausentes))
            return None
        return caminho

    def saida(self, nome_do_argumento, variavel, padrao):
        caminho = self._valor(nome_do_argumento, variavel) or padrao
        caminho = os.path.abspath(os.path.expanduser(caminho))
        os.makedirs(caminho, exist_ok=True)
        return caminho

    def exigir(self, titulo="Este script precisa de dados que nao estao aqui."):
        """Para com uma mensagem unica quando faltar qualquer raiz."""
        if not self._faltando:
            return
        linhas = [titulo, ""]
        for argumento, variavel, descricao, motivo, arquivos in self._faltando:
            linhas.append("  --{}=<caminho>   (ou {}={})".format(
                argumento, variavel, "<caminho>"))
            linhas.append("      {}".format(descricao))
            linhas.append("      {}".format(motivo))
            if arquivos:
                linhas.append("      esperado dentro: {}".format(
                    ", ".join(arquivos)))
            linhas.append("")
        linhas.append(
            "Os dados de campo nao vao no repositorio (MDEs e trilhas de GPS "
            "de terceiros). Ver docs/VALIDACAO.md para a origem de cada um.")
        raise SystemExit("\n".join(linhas))
