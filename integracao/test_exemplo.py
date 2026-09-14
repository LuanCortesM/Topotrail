"""O exemplo de exemplo/ roda, e produz os numeros que exemplo/README.md promete.

Existe porque um exemplo reprodutivel so vale enquanto continua reproduzindo. Os
valores de `exemplo/executar.py` foram medidos numa execucao real da 1.3.0; se
uma alteracao do modelo os mover, e este teste que avisa -- e nao um revisor
tentando conferir a documentacao.

Fica na suite de integracao, e nao em tests/, porque o exemplo e uma execucao
completa do algoritmo com GDAL e QGIS de verdade: em tests/ o QGIS e um duble e
nao ha rota nenhuma para medir.

    /usr/bin/python3.12 -m pytest integracao -q
"""
import importlib.util
import os
import re

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA = os.path.join(RAIZ, "exemplo")


def _modulo_executar():
    caminho = os.path.join(PASTA, "executar.py")
    if not os.path.isfile(caminho):
        pytest.skip("exemplo/executar.py nao existe")
    spec = importlib.util.spec_from_file_location("tt_exemplo_executar", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_os_arquivos_do_exemplo_estao_no_repositorio():
    """Sem o MDE e os tres pontos versionados nao ha exemplo para rodar."""
    faltando = [nome for nome in ("mde.tif", "origem.geojson", "destino.geojson",
                                  "intermediario.geojson", "gerar_mde.py",
                                  "executar.py", "README.md")
                if not os.path.isfile(os.path.join(PASTA, nome))]
    assert not faltando, "exemplo/ incompleto: {}".format(faltando)


def test_o_exemplo_declara_todos_os_parametros_do_algoritmo(plugin):
    """O exemplo e tambem a referencia de chamada roteirizada.

    Um parametro que exista no algoritmo e nao apareca em `executar.py` fica
    sem documentacao nenhuma, que e a pendencia que o exemplo veio fechar.
    """
    modulo = _modulo_executar()
    algoritmo = plugin.TopotrailAlgorithm()
    algoritmo.initAlgorithm()
    do_algoritmo = {definicao.name() for definicao in algoritmo.parameterDefinitions()}
    do_exemplo = set(modulo.parametros("d", "o", "f", "v", "s"))
    assert do_algoritmo - do_exemplo == set(), (
        "parametros sem exemplo: {}".format(sorted(do_algoritmo - do_exemplo)))
    assert do_exemplo - do_algoritmo == set(), (
        "parametros que o algoritmo nao tem: {}".format(sorted(do_exemplo - do_algoritmo)))


def test_o_readme_do_exemplo_traz_os_valores_esperados():
    """O texto e a lista de conferencia nao podem divergir.

    Foi exatamente assim que `docs/METODOLOGIA_TOPOtrail.md` passou meses
    descrevendo um modelo que o software ja nao tinha.
    """
    modulo = _modulo_executar()
    texto = open(os.path.join(PASTA, "README.md"), encoding="utf-8").read()
    # Numeros em ingles, com ponto decimal; separador de milhar opcional.
    normalizado = texto.replace(",", "")
    ausentes = []
    for chave, valor in sorted(modulo.ESPERADO.items()):
        if isinstance(valor, str):
            procurado = valor
        elif isinstance(valor, int):
            procurado = str(valor)
        else:
            procurado = "{:g}".format(valor)
        if not re.search(r"(?<![\d.])" + re.escape(procurado) + r"(?![\d])", normalizado):
            ausentes.append("{} = {}".format(chave, procurado))
    assert not ausentes, (
        "valores de executar.py que nao aparecem em exemplo/README.md: "
        + ", ".join(ausentes))


def test_o_exemplo_reproduz_os_valores_documentados(qgis_app, plugin):
    """A execucao de ponta a ponta, com os parametros e os pontos do exemplo."""
    modulo = _modulo_executar()
    mde = os.path.join(PASTA, "mde.tif")
    if not os.path.isfile(mde):
        pytest.skip("exemplo/mde.tif ausente; rode exemplo/gerar_mde.py")

    saida_dir = os.path.join(PASTA, "saida")
    os.makedirs(saida_dir, exist_ok=True)
    saida = os.path.join(saida_dir, "exemplo.gpkg")

    parametros = modulo.parametros(
        mde,
        os.path.join(PASTA, "origem.geojson"),
        os.path.join(PASTA, "destino.geojson"),
        os.path.join(PASTA, "intermediario.geojson"),
        saida)

    algoritmo = plugin.TopotrailAlgorithm()
    algoritmo.initAlgorithm()
    from qgis.core import QgsProcessingContext, QgsProcessingFeedback
    resultado = algoritmo.processAlgorithm(
        parametros, QgsProcessingContext(), QgsProcessingFeedback())

    _, rota = modulo.ler_atributos(resultado["OUTPUT_ROUTE"])
    travessias, _ = modulo.ler_atributos(resultado["OUTPUT_CROSSINGS"])
    zonas, _ = modulo.ler_atributos(resultado["OUTPUT_VECTOR"])
    atributos = rota[0]

    medido = {
        "comprimento_m": round(float(atributos["compr_m"]), 1),
        "tempo_h": round(float(atributos["tempo_h"]), 2),
        "tempo_hms": atributos["tempo_hms"],
        "ganho_m": round(float(atributos["ganho_m"]), 1),
        "perda_m": round(float(atributos["perda_m"]), 1),
        "alt_max_m": round(float(atributos["alt_max_m"]), 1),
        "travessias": int(travessias),
        "zonas": int(zonas),
    }

    divergencias = modulo.conferir(medido)
    assert not divergencias, (
        "o exemplo deixou de reproduzir exemplo/README.md:\n  "
        + "\n  ".join(divergencias))


def test_os_sete_produtos_saem_da_execucao_do_exemplo(qgis_app, plugin):
    """O exemplo tem de exercitar os sete produtos, nao um subconjunto."""
    modulo = _modulo_executar()
    mde = os.path.join(PASTA, "mde.tif")
    if not os.path.isfile(mde):
        pytest.skip("exemplo/mde.tif ausente; rode exemplo/gerar_mde.py")

    saida_dir = os.path.join(PASTA, "saida")
    os.makedirs(saida_dir, exist_ok=True)
    parametros = modulo.parametros(
        mde,
        os.path.join(PASTA, "origem.geojson"),
        os.path.join(PASTA, "destino.geojson"),
        os.path.join(PASTA, "intermediario.geojson"),
        os.path.join(saida_dir, "exemplo.gpkg"))

    algoritmo = plugin.TopotrailAlgorithm()
    algoritmo.initAlgorithm()
    from qgis.core import QgsProcessingContext, QgsProcessingFeedback
    resultado = algoritmo.processAlgorithm(
        parametros, QgsProcessingContext(), QgsProcessingFeedback())

    for chave in ("OUTPUT_SCORE_RASTER", "OUTPUT_RISK_RASTER",
                  "OUTPUT_TRANSITABILITY", "OUTPUT_VECTOR", "OUTPUT_ROUTE",
                  "OUTPUT_CORRIDOR", "OUTPUT_CROSSINGS", "OUTPUT_DEBUG_LOG"):
        assert chave in resultado, "o exemplo nao produziu {}".format(chave)
        assert os.path.isfile(resultado[chave]), (
            "{} declarado mas ausente: {}".format(chave, resultado[chave]))
