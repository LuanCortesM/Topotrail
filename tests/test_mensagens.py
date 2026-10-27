"""As mensagens do calculo: todas no catalogo, nos seis idiomas, com os mesmos marcadores.

Ate a 1.5.4 o andamento, os avisos e os erros do algoritmo -- cerca de 170
frases -- saiam em portugues sem acento, qualquer que fosse o idioma escolhido.
Agora sao chaves `msg_*` nos arquivos de idioma, e estes testes barram os dois
jeitos de voltar ao estado anterior: uma frase escrita direto no codigo, e uma
chave que exista num idioma e falte noutro (ou perca um marcador e estoure no
format() so naquele idioma).
"""

import ast
import importlib.util
import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
I18N = ROOT / "i18n"
PROCESSING = ROOT / "processing"
IDIOMAS = ["pt", "en", "es", "fr", "ja", "zh"]
CHAMADAS_AO_USUARIO = {"pushInfo", "pushWarning", "reportError", "setProgressText", "_erro", "_cancelado",
                       "QgsProcessingException"}
# Erros de programacao, que so aparecem com defeito no codigo: ficam em ingles neutro.
ERROS_DE_PROGRAMACAO = ("FeatureSet: ", "The anisotropic model needs", "connectivity must be")


def _load(code):
    return json.loads((I18N / f"{code}.json").read_text(encoding="utf-8"))


def _mensagens():
    if "_topotrail_mensagens" not in sys.modules:
        spec = importlib.util.spec_from_file_location("_topotrail_mensagens", PROCESSING / "mensagens.py")
        sys.modules["_topotrail_mensagens"] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sys.modules["_topotrail_mensagens"])
    return sys.modules["_topotrail_mensagens"]


def _marcadores(texto):
    return sorted(re.findall(r"\{[^}]*\}", texto))


def _mensagens_do_catalogo(code):
    return {k: v for k, v in _load(code).items() if k.startswith("msg_")}


def _chaves_usadas():
    usadas = set()
    for arquivo in PROCESSING.glob("*.py"):
        usadas |= set(re.findall(r"""["'](msg_\w+)["']""", arquivo.read_text(encoding="utf-8")))
    return usadas


def _tem_letras(texto):
    return bool(re.search(r"[^\W\d_]", texto))


def _literais(no):
    """Os pedacos de texto escritos direto numa expressao (constante, f-string, concatenacao)."""
    if isinstance(no, ast.Constant) and isinstance(no.value, str):
        return [no.value]
    if isinstance(no, ast.JoinedStr):
        return [v.value for v in no.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    if isinstance(no, ast.BinOp):
        return _literais(no.left) + _literais(no.right)
    if isinstance(no, ast.IfExp):
        return _literais(no.body) + _literais(no.orelse)
    if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute) and no.func.attr == "format":
        return _literais(no.func.value)
    return []


def test_toda_chave_usada_existe_nos_seis_idiomas():
    usadas = _chaves_usadas()
    assert len(usadas) > 250
    for code in IDIOMAS:
        faltam = sorted(usadas - set(_load(code)))
        assert not faltam, f"{code}: faltam {len(faltam)} mensagens, ex.: {faltam[:5]}"


def test_nenhuma_mensagem_sobra_no_catalogo():
    sobram = sorted(set(_mensagens_do_catalogo("en")) - _chaves_usadas())
    assert not sobram, f"mensagens que o codigo nao usa mais: {sobram}"


@pytest.mark.parametrize("code", ["pt", "es", "fr", "ja", "zh"])
def test_marcadores_e_formatos_iguais_aos_do_ingles(code):
    """`{pct:.1f}` que vire `{pct}` ou `{pct:.1}` so estoura naquele idioma; `{n}` a mais tambem."""
    ingles, traducao = _mensagens_do_catalogo("en"), _mensagens_do_catalogo(code)
    assert set(ingles) == set(traducao)
    for chave, texto in ingles.items():
        assert _marcadores(traducao[chave]) == _marcadores(texto), (code, chave)
        # as que comecam com espaco sao emendadas a outra frase; chines e japones nao usam o espaco
        if code not in ("ja", "zh") and not chave.startswith("msg_sep_"):
            assert traducao[chave].startswith(" ") == texto.startswith(" "), (code, chave)


@pytest.mark.parametrize("code", IDIOMAS)
def test_toda_mensagem_formata_com_valores_de_exemplo(code):
    mensagens = _mensagens()
    formatador = mensagens._Formatador(code)
    for chave, texto in _mensagens_do_catalogo(code).items():
        valores = {}
        for nome, spec in re.findall(r"\{(\w+)(?::([^}]*))?\}", texto):
            if spec.endswith("s"):
                valores[nome] = "x"
            elif spec.endswith(("d", ",")) or spec.endswith(",") or re.fullmatch(r">?\d*,", spec):
                valores[nome] = 1234
            elif spec:
                valores[nome] = 1234.5
            else:
                valores[nome] = "x"
        saida = formatador.vformat(texto, (), valores)
        assert saida.strip() and "{" not in saida, (code, chave, saida)


def test_os_numeros_saem_no_formato_de_cada_lingua():
    formatar = lambda code, modelo, valor: _mensagens()._Formatador(code).format(modelo, valor)  # noqa: E731
    assert formatar("pt", "{:,.1f}", 1234.5) == "1.234,5"
    assert formatar("es", "{:,.1f}", 1234.5) == "1.234,5"
    assert formatar("fr", "{:,.1f}", 1234.5) == "1 234,5"
    assert formatar("en", "{:,.1f}", 1234.5) == "1,234.5"
    assert formatar("zh", "{:,.1f}", 1234.5) == "1,234.5"
    assert formatar("pt", "{:,}", 25113) == "25.113"
    # texto fica como veio: versao, caminho, CRS, coordenada ja formatada
    assert formatar("pt", "{}", "1.5.4") == "1.5.4"
    assert formatar("pt", "{}", "523456.7") == "523456.7"
    assert formatar("pt", "{}", True) == "True"


def test_traducao_com_marcador_errado_cai_no_ingles(monkeypatch):
    """Um erro de traducao nao pode derrubar o calculo: a frase sai em ingles."""
    mensagens = _mensagens()
    quebrado = dict(mensagens._carregar("fr"))
    quebrado["msg_rota_salva"] = "Itinéraire enregistré : {chemin}"
    monkeypatch.setitem(mensagens._cache, "fr", quebrado)
    monkeypatch.setattr(mensagens, "_idioma", "fr")
    assert mensagens.t("msg_rota_salva", path="r.gpkg") == "Access route saved: r.gpkg"


def test_idioma_desconhecido_vira_ingles(monkeypatch):
    mensagens = _mensagens()
    monkeypatch.setattr(mensagens, "_idioma", mensagens._idioma)
    mensagens.definir_idioma("de")
    assert mensagens.idioma() == "en"


def test_nenhuma_frase_ao_usuario_escrita_direto_no_codigo():
    """Toda frase que o usuario le passa por t('msg_...'); texto literal so sem letras."""
    achados = []
    for arquivo in sorted(PROCESSING.glob("*.py")):
        if arquivo.name == "mensagens.py":
            continue
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            if isinstance(no, ast.Call) and no.args:
                f = no.func
                nome = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                if nome in CHAMADAS_AO_USUARIO:
                    for pedaco in _literais(no.args[0]):
                        if _tem_letras(pedaco):
                            achados.append(f"{arquivo.name}:{no.lineno} {pedaco[:60]!r}")
            if isinstance(no, ast.Raise) and isinstance(no.exc, ast.Call) and no.exc.args:
                f = no.exc.func
                if getattr(f, "id", None) in ("ValueError", "RuntimeError"):
                    pedacos = _literais(no.exc.args[0])
                    texto = "".join(pedacos)
                    if pedacos and _tem_letras(texto) and not texto.startswith(ERROS_DE_PROGRAMACAO):
                        achados.append(f"{arquivo.name}:{no.lineno} {texto[:60]!r}")
    assert not achados, "frases ao usuario fora do catalogo:\n" + "\n".join(achados)


def test_o_algoritmo_fala_no_idioma_da_janela():
    """O idioma das mensagens e definido no inicio de cada execucao, pelo mesmo criterio dos rotulos."""
    fonte = (PROCESSING / "algorithm.py").read_text(encoding="utf-8")
    inicio = fonte.index("    def processAlgorithm(")
    corpo = fonte[inicio:fonte.index("    def _run_algorithm(", inicio)]
    assert "mensagens.definir_idioma(_algorithm_language())" in corpo
