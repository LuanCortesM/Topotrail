"""A interface e o motor precisam falar a mesma lingua.

Este arquivo existe por causa de um defeito real e recorrente: a janela ficou
para tras do algoritmo. Dezesseis parametros acrescentados a partir da versao
0.6 -- derivar do MDE, drenagem, tempo de Tobler, limites de transitabilidade,
destinos intermediarios -- eram inalcancaveis pela interface, e o mapa de
transitabilidade nunca era carregado no projeto porque a janela procurava uma
saida com nome que nunca existiu.

Sao erros que nao aparecem em teste de unidade do calculo nem quebram a
importacao: o plugin roda, so nao faz o que a tela promete. A verificacao e
feita no codigo-fonte, sem Qt, para poder rodar na integracao continua onde nao
ha QGIS instalado.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
ALGORITHM = (ROOT / "processing" / "algorithm.py").read_text(encoding="utf-8")
DIALOG = (ROOT / "ui" / "topotrail_dialog.py").read_text(encoding="utf-8")


def _language(code):
    import json
    return json.loads((ROOT / "i18n" / f"{code}.json").read_text(encoding="utf-8"))


def _all_text(code):
    """Todo o texto visível de um idioma, num só bloco."""
    parts = []
    for value in _language(code).values():
        parts.extend(value if isinstance(value, list) else [value])
    return " ".join(parts)


def _declared_parameters():
    """Nomes que o algoritmo aceita.

    Duas formas de declaracao convivem no arquivo: a chamada direta, e a lista
    de tuplas (self.NOME, rotulo, padrao) percorrida num laco para os pesos.
    Ler so a primeira faria este teste acusar falta de WEIGHT_ROUGHNESS quando
    ele existe -- um falso positivo e tao ruim quanto nao ter o teste.
    """
    direct = set(re.findall(
        r"self\.add(?:Advanced)?Parameter\(\s*\n?\s*Qgs\w+\(\s*\n?\s*self\.([A-Z0-9_]+)",
        ALGORITHM))
    looped = set(re.findall(r"\(\s*self\.([A-Z0-9_]+)\s*,\s*\"", ALGORITHM))
    known = set(re.findall(r"^\s{4}([A-Z][A-Z0-9_]+)\s*=\s*\"\1\"", ALGORITHM, re.M))
    return (direct | looped) & known


def _declared_outputs():
    return set(re.findall(r"self\.addOutput\(\s*Qgs\w+\(\s*self\.([A-Z0-9_]+)", ALGORITHM))


def _collect_body():
    start = DIALOG.index("    def _collect(self):")
    end = DIALOG.index("    def _run(self):")
    return DIALOG[start:end]


def _load_body():
    start = DIALOG.index("    def _load_results(self, results):")
    return DIALOG[start:]


def test_every_parameter_the_interface_sends_is_understood_by_the_algorithm():
    """O QGIS ignora chave desconhecida em silencio, entao um nome errado aqui
    vira uma opcao que a pessoa marca e que nao surte efeito nenhum."""
    sent = set(re.findall(r'"([A-Z][A-Z0-9_]{2,})"\s*:', _collect_body()))
    unknown = sent - _declared_parameters()
    assert not unknown, f"a interface envia parametros que o algoritmo nao declara: {sorted(unknown)}"


def test_every_output_the_interface_loads_is_produced_by_the_algorithm():
    """Foi exatamente esta a falha: a janela procurava OUTPUT_ZONES e
    OUTPUT_STREAMS. As zonas saem em OUTPUT_VECTOR e a drenagem nao e
    exportada, entao as zonas nunca chegavam ao projeto."""
    requested = set(re.findall(r'\("(OUTPUT_[A-Z0-9_]+)",', _load_body()))
    unknown = requested - _declared_outputs()
    assert not unknown, f"a interface tenta carregar saidas inexistentes: {sorted(unknown)}"


def test_the_output_format_options_are_in_the_same_order_in_both():
    """Enum do QGIS viaja como índice, não como texto. Com as listas em ordens
    diferentes, escolher GeoPackage gravava um Shapefile sem aviso nenhum.

    Agora a janela monta a lista a partir de chaves de tradução, então o que se
    compara são as chaves -- e a comparação vale para os seis idiomas de uma vez,
    porque todos usam as mesmas chaves.
    """
    algorithm_options = re.search(
        r"self\.OUTPUT_FORMAT,.*?options=\[([^\]]+)\]", ALGORITHM, re.S)
    dialog_keys = re.search(
        r'fill\(self\.output_format, \[([^\]]+)\]', DIALOG, re.S)
    assert algorithm_options and dialog_keys
    clean = lambda text: [part.strip().strip('"\'') for part in text.split(",")]
    esperado = clean(algorithm_options.group(1))
    chaves = clean(dialog_keys.group(1))
    assert len(esperado) == len(chaves), "quantidade de formatos diferente"
    ingles = _language("en")
    assert [ingles[k] for k in chaves] == esperado


@pytest.mark.parametrize("parameter", [
    "DERIVE_FROM_DEM", "STREAMS_FROM_DEM", "ROUTE_COST_MODEL",
    "TRANSITABILITY_BREAKS", "VIA_POINTS_FILE", "OPTIMISE_ORDER",
    "WEIGHT_WETNESS", "WEIGHT_ROUGHNESS", "VERTICAL_UNIT", "SLOPE_UNIT",
    "EXTRA_CRITERION_LAYER", "CONSTRAINT_LAYER",
])
def test_the_features_added_since_0_6_are_reachable_from_the_interface(parameter):
    """Cada um destes existia no motor e nao tinha como ser acionado pela
    janela. Um recurso que a interface nao alcanca nao existe para quem nao
    escreve Python."""
    assert parameter in _declared_parameters()
    assert parameter in _collect_body(), (
        f"{parameter} existe no algoritmo mas a interface nunca o envia")


def test_the_transitability_map_reaches_the_project():
    """Existe desde a 0.6.2 e a janela anterior nunca o carregava: o usuario
    tinha de achar o arquivo no disco e abrir a mao."""
    assert "OUTPUT_TRANSITABILITY" in _load_body()


def test_the_texts_live_in_data_files_not_in_the_module():
    """Os textos saíram de um dicionário dentro do Python para i18n/*.json.

    O motivo é prático: uma tradução errada precisa poder ser corrigida por quem
    fala a língua, e essa pessoa não é necessariamente programadora.
    """
    assert "TEXTS = {" not in DIALOG, "o dicionário embutido não deve voltar"
    assert "i18n.text(" in DIALOG



# --------------------------------------------------------------------------
# O plugin e usado no mundo todo, e o credito do projeto tem de aparecer
# --------------------------------------------------------------------------

REGIONAL_EXAMPLES = [
    "marins", "marinzinho", "itaguaré", "itaguare", "mantiqueira",
    "caatinga", "cruzeiro", "serra do mar",
]


def test_the_interface_texts_name_no_particular_place():
    """Nenhum idioma pode ilustrar um recurso com o topônimo de um lugar só.

    A primeira versão do assistente explicava os destinos intermediários com
    "desenhe Marins, Marinzinho e Itaguaré nessa sequência". Funciona para quem
    conhece a Serra da Mantiqueira e não diz nada para o resto do mundo -- e o
    TopoTrail está no repositório oficial do QGIS, hoje em seis idiomas.
    """
    for code in ("pt", "en", "es", "fr", "zh", "ja"):
        texto = _all_text(code).lower()
        # os créditos podem nomear o projeto; a ajuda dos controles não
        texto = texto.replace("herpeto mantiqueira", "")
        offenders = [name for name in REGIONAL_EXAMPLES if name in texto]
        assert not offenders, f"{code}: exemplo preso a uma região: {offenders}"


def test_the_institutional_logos_are_shipped_and_displayed():
    """As logos sao credito de projeto e de instituicao, nao decoracao.

    Uma reescrita da janela ja as removeu por descuido uma vez.
    """
    for filename in ("logo_herpeto_mantiqueira.png", "logo_enbt.jpg", "logo_jbrj.jpg"):
        assert (ROOT / "assets" / filename).exists(), f"falta o arquivo {filename}"
        assert filename in DIALOG, f"{filename} existe mas a janela nao o exibe"
    assert "logo.png" in DIALOG


def test_the_credits_name_author_supervisor_project_and_institution():
    """O crédito precisa sobreviver em todos os idiomas, não só no original."""
    for code in ("pt", "en", "es", "fr", "zh", "ja"):
        texto = _all_text(code)
        for fragmento in ("Luan da Silva Cortes Maciel", "Leandro Freitas",
                          "Herpeto Mantiqueira"):
            assert fragmento in texto, f"{code}: crédito ausente — {fragmento}"


# --------------------------------------------------------------------------
# Sistema visual
# --------------------------------------------------------------------------

def test_every_icon_name_used_by_the_interface_exists():
    """Um nome de glifo errado nao levanta excecao: pixmap() devolve um quadrado
    transparente e o icone simplesmente some da tela, sem aviso nenhum."""
    import ast
    icons_source = (ROOT / "ui" / "icons.py").read_text(encoding="utf-8")
    tree = ast.parse(icons_source)
    glyphs = next(node for node in tree.body
                  if isinstance(node, ast.Assign)
                  and getattr(node.targets[0], "id", None) == "GLYPHS")
    available = {key.value for key in glyphs.value.keys}

    used = set(re.findall(r'_icon\(\s*"([a-z-]+)"', DIALOG))
    used |= set(re.findall(r'_card\([^,]+,\s*"([a-z-]+)"\)', DIALOG))
    used |= set(re.findall(r'_page_head\(layout,\s*"([a-z-]+)"', DIALOG))
    used |= set(re.findall(r'self\._option\(\s*"([a-z-]+)"', DIALOG))
    used |= set(re.findall(r'icons\.pixmap\(\s*"([a-z-]+)"', DIALOG))
    missing = used - available
    assert not missing, f"glifos usados que nao existem em icons.py: {sorted(missing)}"
    assert used, "nenhum icone detectado: a extracao do teste deve ter quebrado"


def test_icons_render_without_a_display():
    """Os glifos sao tracados com QPainter, entao um erro de geometria so
    aparece ao desenhar. Sem QGIS instalado o teste e pulado."""
    pytest.importorskip("qgis.PyQt.QtGui")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from qgis.PyQt.QtWidgets import QApplication
    from ui import icons

    application = QApplication.instance() or QApplication([])
    assert application is not None
    for name in icons.GLYPHS:
        for size in (18, 24, 44):
            image = icons.pixmap(name, size, "#0d452c")
            assert not image.isNull(), f"o glifo {name} nao desenhou em {size} px"


def test_the_version_shown_in_the_interface_comes_from_metadata():
    """A versão era lida por import relativo e voltava vazia sempre que o módulo
    não era carregado como parte do pacote do plugin -- sem erro, só um espaço
    em branco na tela. Agora vem do metadata.txt, que é a fonte de verdade.

    Verificado no código-fonte, e não importando o diálogo: importá-lo puxa todo
    o Qt e faz este teste depender de qual outro teste rodou antes.
    """
    version = None
    for line in (ROOT / "metadata.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("version="):
            version = line.split("=", 1)[1].strip()
    assert version, "metadata.txt não declara version="
    assert f'PLUGIN_VERSION = "{version}"' in ALGORITHM, \
        "metadata.txt e algorithm.py discordam da versão"
    assert "metadata.txt" in DIALOG, \
        "a interface deve ler a versão do metadata.txt"
    assert "from ..processing.algorithm import PLUGIN_VERSION" not in DIALOG, \
        "o import relativo falha em silêncio e não deve voltar"


def test_the_interface_offers_both_themes():
    """O QGIS tem tema próprio e o usuário escolhe qual usar. Fixar a janela num
    dos dois garante que ela vai destoar da metade dos QGIS instalados -- e no
    escuro apagaria as logos institucionais, que têm fundo branco."""
    assert "LIGHT = {" in DIALOG and "DARK = {" in DIALOG
    for token in ("ink", "muted", "accent", "canvas", "surface", "line"):
        assert DIALOG.count(f'"{token}":') >= 2, (
            f"o token {token} precisa existir nos dois temas")
    assert "_is_dark_theme" in DIALOG, "o tema padrão deve seguir o do QGIS"


def test_no_colour_is_hardcoded_outside_the_theme_tables():
    """Uma cor escrita direto numa regra escapa da troca de tema e vira uma
    mancha clara no escuro. As poucas exceções são deliberadas e estão listadas.
    """
    allowed = {
        "#ffffff", "#0f1a15", "#0d452c", "#22302a", "#0a3a25", "#86a89a",
        "#cfe3d8", "#7d9a8d", "#83a696", "#b9d5c7", "#26200c", "#24483b",
        "#cfe6da", "#14614a", "#0b1310",
    }
    body = DIALOG[DIALOG.index("def _apply_theme"):]
    found = set(re.findall(r"#[0-9a-fA-F]{6}", body))
    unexpected = {colour for colour in found if colour.lower() not in allowed}
    assert not unexpected, (
        f"cores fixas fora das tabelas de tema: {sorted(unexpected)}")
