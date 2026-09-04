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
    """Enum do QGIS viaja como indice, nao como texto. Com as listas em ordens
    diferentes, escolher GeoPackage gravava um Shapefile sem aviso nenhum."""
    algorithm_options = re.search(
        r"self\.OUTPUT_FORMAT,.*?options=\[([^\]]+)\]", ALGORITHM, re.S)
    dialog_options = re.search(
        r"fill\(self\.output_format, \[([^\]]+)\]", DIALOG, re.S)
    assert algorithm_options and dialog_options
    clean = lambda text: [part.strip().strip('"\'') for part in text.split(",")]
    assert clean(algorithm_options.group(1)) == clean(dialog_options.group(1))


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


def test_both_languages_define_the_same_keys():
    """Uma chave presente so em portugues aparece em ingles como o proprio nome
    da chave -- 'o_transit_help' no meio da tela."""
    import ast
    tree = ast.parse(DIALOG)
    texts = next(node for node in tree.body
                 if isinstance(node, ast.Assign)
                 and getattr(node.targets[0], "id", None) == "TEXTS")
    languages = {key.value: {k.value for k in value.keys}
                 for key, value in zip(texts.value.keys, texts.value.values)}
    assert languages["pt"] == languages["en"], (
        "faltando em ingles: {}; faltando em portugues: {}".format(
            sorted(languages["pt"] - languages["en"]),
            sorted(languages["en"] - languages["pt"])))


# --------------------------------------------------------------------------
# O plugin e usado no mundo todo, e o credito do projeto tem de aparecer
# --------------------------------------------------------------------------

REGIONAL_EXAMPLES = [
    "marins", "marinzinho", "itaguaré", "itaguare", "mantiqueira",
    "caatinga", "cruzeiro", "serra do mar",
]


def test_the_interface_texts_name_no_particular_place():
    """Os textos de ajuda nao podem usar exemplo de um lugar so.

    A primeira versao do assistente explicava os destinos intermediarios com
    "desenhe Marins, Marinzinho e Itaguaré nessa sequência". Funciona para quem
    conhece a Serra da Mantiqueira e nao diz nada para o resto do mundo -- e o
    TopoTrail e publicado no repositorio oficial do QGIS, para qualquer regiao.
    A explicacao tem de valer em qualquer lugar: "um cume, depois outro".
    """
    import ast
    tree = ast.parse(DIALOG)
    texts = next(node for node in tree.body
                 if isinstance(node, ast.Assign)
                 and getattr(node.targets[0], "id", None) == "TEXTS")
    strings = [node.value.lower() for node in ast.walk(texts)
               if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    # os creditos podem nomear o projeto e a instituicao; a ajuda dos controles nao
    body = " ".join(value for value in strings if "herpeto mantiqueira" not in value)
    offenders = [name for name in REGIONAL_EXAMPLES if name in body]
    assert not offenders, (
        f"exemplo preso a uma regiao no texto da interface: {offenders}")


def test_the_institutional_logos_are_shipped_and_displayed():
    """As logos sao credito de projeto e de instituicao, nao decoracao.

    Uma reescrita da janela ja as removeu por descuido uma vez.
    """
    for filename in ("logo_herpeto_mantiqueira.png", "logo_enbt.jpg", "logo_jbrj.jpg"):
        assert (ROOT / "assets" / filename).exists(), f"falta o arquivo {filename}"
        assert filename in DIALOG, f"{filename} existe mas a janela nao o exibe"
    assert "logo.png" in DIALOG


def test_the_credits_name_author_supervisor_project_and_institution():
    for fragment in ("Luan da Silva Cortes Maciel", "Leandro Freitas",
                     "Herpeto Mantiqueira", "Botânica Tropical"):
        assert fragment in DIALOG, f"credito ausente: {fragment}"
