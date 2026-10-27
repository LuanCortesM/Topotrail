"""Mensagens do calculo ao usuario, no idioma escolhido.

O andamento, os avisos e os erros do algoritmo ficam nos mesmos arquivos de
idioma da janela (`i18n/<codigo>.json`), com chaves `msg_*`. Ate a 1.5.4 eram
cerca de 170 frases em portugues sem acento, qualquer que fosse o idioma
escolhido: quem usava o plugin em ingles ou em japones lia o andamento, os
avisos e os erros em portugues.

Este modulo nao importa Qt nem QGIS, porque terrain, hydrology e
transitability, que so usam NumPy, tambem falam por ele. O idioma e definido
uma vez por execucao, no inicio do algoritmo (`definir_idioma`).

Os numeros saem no formato da lingua: 1.234,5 em portugues e espanhol,
1 234,5 em frances, 1,234.5 em ingles, chines e japones. So valores numericos
passam por isso; textos (caminhos, CRS, coordenadas ja formatadas) ficam como
vieram.
"""

import json
import numbers
import os
import string

I18N_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "i18n")
IDIOMAS = ("pt", "en", "es", "fr", "zh", "ja")
RESERVA = ("en", "pt")

# (separador decimal, separador de milhar) onde nao sao os do Python.
_SEPARADORES = {"pt": (",", "."), "es": (",", "."), "fr": (",", " ")}

_cache = {}
_idioma = "en"


def definir_idioma(codigo):
    """Idioma das mensagens desta execucao; um codigo desconhecido vira ingles."""
    global _idioma
    _idioma = codigo if codigo in IDIOMAS else "en"


def idioma():
    return _idioma


def _carregar(codigo):
    if codigo not in _cache:
        try:
            with open(os.path.join(I18N_DIR, f"{codigo}.json"), encoding="utf-8") as arquivo:
                _cache[codigo] = json.load(arquivo)
        except (OSError, ValueError):
            _cache[codigo] = {}
    return _cache[codigo]


def texto(chave, codigo=None):
    """O texto da chave no idioma pedido, recorrendo ao ingles e ao portugues."""
    for candidato in (codigo or _idioma,) + RESERVA:
        valor = _carregar(candidato).get(chave)
        if valor:
            return valor
    return chave


class _Formatador(string.Formatter):
    def __init__(self, codigo):
        super().__init__()
        self.codigo = codigo

    def format_field(self, valor, spec):
        saida = super().format_field(valor, spec)
        separadores = _SEPARADORES.get(self.codigo)
        if separadores and isinstance(valor, numbers.Number) and not isinstance(valor, bool):
            decimal, milhar = separadores
            saida = saida.translate(str.maketrans({".": decimal, ",": milhar}))
        return saida


def t(chave, **valores):
    """A mensagem `chave` no idioma da execucao, com os valores no lugar.

    Uma traducao com marcador errado nao pode derrubar o calculo: nesse caso a
    frase sai em ingles, que e a referencia conferida pelos testes.
    """
    try:
        return _Formatador(_idioma).vformat(texto(chave), (), valores)
    except (KeyError, IndexError, ValueError):
        return _Formatador("en").vformat(texto(chave, "en"), (), valores)
