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
import atexit
import importlib.util
import os
import shutil
import sys
import tempfile

RAIZ_DO_REPOSITORIO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def iniciar_qgis(prefixo=None):
    """Sobe um QGIS headless com o TopoTrail registrado como provider.

    O prefixo vem de `prefixo`, de QGIS_PREFIX_PATH ou e deduzido do proprio
    Python (tools/qgis_headless.py), em Windows, Linux ou macOS.
    """
    if prefixo:
        os.environ["QGIS_PREFIX_PATH"] = prefixo
    try:
        from qgis.core import QgsApplication  # noqa: F401
    except ImportError as erro:
        raise SystemExit(
            "Este script precisa do Python do QGIS. Rode com o interpretador que "
            "tem qgis.core importavel (Linux: normalmente /usr/bin/python3; "
            "Windows: python-qgis.bat; macOS: o Python do QGIS.app).\n"
            "  detalhe: {}".format(erro))
    headless = _ferramenta("qgis_headless")
    aplicacao = headless.iniciar()
    try:
        processing = headless.processing_do_qgis()
    except ImportError as erro:
        raise SystemExit(
            "Nao encontrei o plugin Processing do QGIS.\n  detalhe: {}".format(erro))
    headless.registrar_topotrail(RAIZ_DO_REPOSITORIO)
    return aplicacao, processing


def _ferramenta(nome):
    caminho = os.path.join(RAIZ_DO_REPOSITORIO, "tools")
    if caminho not in sys.path:
        sys.path.insert(0, caminho)
    return __import__(nome)


def nucleo():
    """(algorithm, carregar) do plugin deste checkout, sem precisar de QGIS.

    `carregar("terrain")` devolve processing/terrain.py. O QGIS e o GDAL sao
    substituidos so durante o import do algoritmo (tests/nucleo_sem_qgis.py);
    o GDAL de verdade que o script usar continua intacto.
    """
    spec = importlib.util.spec_from_file_location(
        "tt_nucleo_sem_qgis",
        os.path.join(RAIZ_DO_REPOSITORIO, "tests", "nucleo_sem_qgis.py"))
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo.algoritmo(), modulo.carregar


# MDEs reprojetados usados pelos scripts de validacao (ver docs/VALIDACAO.md).
MDES = {
    "caatinga": "caatinga_utm24s.tif",
    "mantiqueira": "mantiqueira_utm23s.tif",
}


def campo(*mdes, trilhas=True):
    """(pasta de trilhas, {regiao: caminho do MDE}, pasta temporaria).

    Para com instrucao, antes de qualquer processamento, se faltar algo.
    """
    dados = Dados()
    base = dados.raiz(
        "trilhas", "TOPOTRAIL_TRILHAS",
        "Trajetos de GPS de campo (KML/GPX).") if trilhas else None
    pasta = dados.raiz(
        "mdes", "TOPOTRAIL_MDES",
        "MDEs reprojetados em UTM.",
        tuple(MDES[regiao] for regiao in mdes)) if mdes else None
    dados.exigir("Este script precisa dos dados de campo, que nao vao no repositorio.")
    caminhos = {regiao: os.path.join(pasta, MDES[regiao]) for regiao in mdes}
    temporaria = tempfile.mkdtemp(prefix="topotrail_validacao_")
    atexit.register(shutil.rmtree, temporaria, True)
    return base, caminhos, temporaria


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
