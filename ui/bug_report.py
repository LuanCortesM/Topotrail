"""Texto e enderecos do relato de problema, sem Qt.

Quem usa o plugin em campo raramente sabe dizer a versao do QGIS, do GDAL ou
onde fica o registro tecnico -- e sem isso um relato de erro quase nunca leva
a causa. Aqui esses dados sao juntados sozinhos, ao lado do que a pessoa
escreveu, e saem em tres formas: e-mail para o autor, texto para copiar e o
formulario de bug do GitHub ja preenchido.

O e-mail usa mailto:, que abre o programa de e-mail do sistema. Quem usa webmail
nao tem programa nenhum associado, entao a janela copia o texto antes de tentar
abrir e diz para onde mandar. Anexo nao vai por mailto em nenhum programa
comum; o caminho do registro tecnico vai escrito no corpo.
"""

import configparser
import os
import re
from urllib.parse import quote

# Corpo maximo do mailto, ja codificado. Alguns programas de e-mail do Windows
# cortam o endereco perto de 2 mil caracteres; o texto inteiro vai copiado.
MAILTO_LIMIT = 1800
# A URL do GitHub aceita bem mais, mas acima de ~8 mil o servidor recusa.
ISSUE_LIMIT = 7000
LOG_LINES = 20


def read_metadata(plugin_dir):
    """A secao [general] do metadata.txt, ou {} se nao der para ler."""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(os.path.join(plugin_dir, "metadata.txt"), encoding="utf-8")
        return dict(parser["general"])
    except (configparser.Error, KeyError, OSError):
        return {}


def anonymize(text, home=None):
    """Troca a pasta pessoal por ~ -- o nome de usuario do sistema nao precisa
    ir num relato, e no Windows ele costuma ser o nome da pessoa."""
    home = home if home is not None else os.path.expanduser("~")
    if not text or not home or home in ("~", "/"):
        return text or ""
    variantes = {home, home.replace("\\", "/"), home.replace("/", "\\")}
    for variante in sorted(variantes, key=len, reverse=True):
        text = re.sub(re.escape(variante), "~", text, flags=re.IGNORECASE)
    return text


def log_tail(text, lines=LOG_LINES):
    linhas = [linha for linha in (text or "").splitlines() if linha.strip()]
    return "\n".join(linhas[-lines:])


def technical_lines(info):
    """Uma linha por item, na ordem em que se le um relato."""
    ordem = (("TopoTrail", "plugin"), ("QGIS", "qgis"), ("Qt", "qt"),
             ("Python", "python"), ("GDAL", "gdal"), ("NumPy", "numpy"),
             ("SciPy", "scipy"), ("OS", "os"), ("Language", "language"))
    return ["{}: {}".format(rotulo, info.get(chave) or "-") for rotulo, chave in ordem]


def technical_block(info, error="", log_path="", log=""):
    """O que vai junto sem a pessoa precisar saber o que e.

    Cabecalhos em ingles, como os rotulos das versoes: a janela mostra este
    bloco em qualquer um dos seis idiomas, e o formulario do GitHub e em ingles.
    Em portugues ele aparecia igual para quem escolheu japones.
    """
    partes = ["--- technical details ---"] + technical_lines(info)
    if error:
        partes += ["", "--- last error ---", anonymize(error.strip())]
    if log_path:
        partes += ["", "--- diagnostic log ---", anonymize(log_path)]
    if log:
        partes += ["", "--- last lines of the progress log ---", anonymize(log_tail(log))]
    return "\n".join(partes)


def compose(description, info, error="", log_path="", log=""):
    """O relato completo, como vai para a area de transferencia."""
    return "{}\n\n{}".format((description or "").strip() or "(no description)",
                             technical_block(info, error, log_path, log))


def mailto_url(address, subject, body, limit=MAILTO_LIMIT):
    """mailto: com assunto e corpo, cortando o corpo para caber no limite.

    Corta pelo fim e avisa que o texto completo foi copiado: o comeco -- a
    descricao e as versoes -- e o que mais importa.
    """
    aviso = "\n\n[...] full text copied to the clipboard"
    corpo = body
    while len(quote(corpo, safe="")) > limit and corpo:
        corpo = corpo[:int(len(corpo) * 0.9)]
    if corpo != body:
        corpo = corpo.rstrip() + aviso
    return "mailto:{}?subject={}&body={}".format(
        address, quote(subject, safe=""), quote(corpo, safe=""))


def issue_url(repository, title, description, info, error="", log=""):
    """Formulario de bug do GitHub com os campos de .github/ISSUE_TEMPLATE/bug_report.yml.

    O GitHub preenche um campo de formulario pelo id dele passado na URL.
    """
    base = (repository or "").rstrip("/")
    if not base.startswith("https://github.com/"):
        return ""
    registro = "\n".join(filter(None, [anonymize(error.strip()) if error else "",
                                       anonymize(log_tail(log))]))
    campos = [("template", "bug_report.yml"), ("title", title),
              ("what-happened", (description or "").strip()),
              ("qgis", info.get("qgis") or ""), ("os", info.get("os") or ""),
              ("version", info.get("plugin") or ""), ("log", registro)]
    while True:
        url = base + "/issues/new?" + "&".join(
            "{}={}".format(chave, quote(valor, safe="")) for chave, valor in campos if valor)
        if len(url) <= ISSUE_LIMIT or not registro:
            return url
        # descarta o comeco do registro: as ultimas linhas sao as do erro
        registro = registro[max(len(registro) // 4, 1):]
        campos[-1] = ("log", registro)
