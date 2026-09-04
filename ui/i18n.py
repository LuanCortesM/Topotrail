"""Textos da interface, um arquivo JSON por idioma.

Por que JSON e não um dicionário dentro do Python: uma tradução errada precisa
poder ser corrigida por quem fala a língua, e essa pessoa não é necessariamente
programadora. Com os textos em `i18n/<código>.json`, corrigir o espanhol é
editar um arquivo de texto e abrir um pull request -- não mexer num módulo de
1.700 linhas e arriscar quebrar a janela.

Por que não .ts/.qm, que é o mecanismo padrão do Qt: o .qm é um binário
compilado com `lrelease`. Isso obriga a um passo de build antes de empacotar o
plugin, e um arquivo binário no repositório não é revisável num pull request.
Para um plugin de uma pessoa só, o custo não se paga.

Cadeia de recurso: idioma pedido -> inglês -> português. Uma chave que falte numa
tradução aparece no idioma seguinte em vez de aparecer como o próprio nome da
chave no meio da tela.
"""

import json
import os

I18N_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "i18n")

# Ordem de exibição no seletor. O nome de cada idioma vem escrito nele mesmo:
# quem precisa trocar para japonês normalmente não lê a palavra "japonês".
LANGUAGES = [
    ("pt", "Português"),
    ("en", "English"),
    ("es", "Español"),
    ("fr", "Français"),
    ("zh", "中文"),
    ("ja", "日本語"),
]

LANGUAGE_CODES = [code for code, _name in LANGUAGES]
FALLBACK_CHAIN = ("en", "pt")

# Traduções conferidas por um falante nativo. As demais são de partida: úteis,
# mas é honesto marcar quais ainda não passaram por revisão humana, e a interface
# diz isso a quem as usa.
REVIEWED = {"pt", "en"}

_cache = {}


def available():
    """Idiomas com arquivo presente, na ordem de LANGUAGES."""
    return [(code, name) for code, name in LANGUAGES
            if os.path.exists(os.path.join(I18N_DIR, f"{code}.json"))]


def load(code):
    if code in _cache:
        return _cache[code]
    path = os.path.join(I18N_DIR, f"{code}.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = {}
    _cache[code] = data
    return data


def text(code, key):
    """O texto da chave, recorrendo às línguas de reserva se faltar."""
    for candidate in (code,) + FALLBACK_CHAIN:
        value = load(candidate).get(key)
        if value:
            return value
    return key


def detect():
    """Idioma do QGIS, se for um dos que o plugin fala.

    Lido da configuração do próprio QGIS e, na falta dela, do locale do sistema.
    Abrir já no idioma do usuário importa mais aqui do que em quase qualquer
    outro plugin: metade dos downloads vem de países onde o português não ajuda
    ninguém, e quem não acha o seletor conclui que a ferramenta é só em
    português.
    """
    candidates = []
    try:
        from qgis.core import QgsSettings
        settings = QgsSettings()
        if settings.value("locale/overrideFlag", False, type=bool):
            candidates.append(settings.value("locale/userLocale", "") or "")
        candidates.append(settings.value("locale/globalLocale", "") or "")
    except Exception:
        pass
    try:
        # getlocale() e nao getdefaultlocale(): a segunda esta depreciada e sai
        # no Python 3.15, e um plugin de QGIS costuma sobreviver a mais de uma
        # versao do interpretador.
        import locale
        candidates.append((locale.getlocale()[0] or ""))
    except Exception:
        pass
    candidates.append(os.environ.get("LANG", ""))

    for raw in candidates:
        if not raw:
            continue
        primary = str(raw).replace("-", "_").split("_")[0].lower()
        if primary in LANGUAGE_CODES:
            return primary
    return "en"
