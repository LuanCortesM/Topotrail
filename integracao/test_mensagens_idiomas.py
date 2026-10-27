"""O andamento, os avisos e os erros do calculo saem no idioma escolhido, nos seis idiomas.

Ate a 1.5.4 tudo isso saia em portugues sem acento, qualquer que fosse o idioma
da janela. Aqui o algoritmo roda de verdade no exemplo, em cada idioma, duas
vezes: com a rota, e com uma declividade maxima que impede a rota. Nenhuma linha
do andamento, aviso ou erro pode trazer palavra que so exista em portugues.
"""
import importlib.util
import os

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXEMPLO = os.path.join(RAIZ, "exemplo")
SO_EM_PORTUGUES = ("ção", "ções", "não ", "Não ", "células", "declividade", "Nenhuma", "trecho",
                   "Concluído", "faixa", "cursos d'água", "salvo:", "salva:")


def _parametros(saida, **extras):
    spec = importlib.util.spec_from_file_location("tt_exemplo_parametros_idiomas", os.path.join(EXEMPLO, "executar.py"))
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    parametros = modulo.parametros(os.path.join(EXEMPLO, "mde.tif"), os.path.join(EXEMPLO, "origem.geojson"),
                                   os.path.join(EXEMPLO, "destino.geojson"), None, saida)
    parametros.update(extras)
    return parametros


@pytest.mark.parametrize("idioma", ["pt", "en", "es", "fr", "ja", "zh"])
def test_o_calculo_fala_o_idioma_escolhido(executar, plugin, idioma, tmp_path):
    from qgis.core import QgsSettings

    QgsSettings().setValue("TopoTrail/language", idioma)
    resultado, feedback, erro = executar(_parametros(str(tmp_path / "e.gpkg")))
    assert erro is None, (erro, feedback.linhas[-5:])
    _, falha, erro_rota = executar(_parametros(str(tmp_path / "f.gpkg"), SLOPE_MAX=1.0, GENERATE_ZONES=False))
    assert erro_rota is not None
    linhas = feedback.linhas + falha.linhas + [str(erro_rota)]

    # a rota salva e o titulo dos parametros, no idioma pedido
    for chave in ("msg_rota_salva", "msg_param_titulo"):
        inicio = plugin.mensagens.texto(chave, idioma).split("{")[0].strip()
        assert any(inicio in linha for linha in linhas), (idioma, chave, inicio)
    if idioma != "pt":
        restos = [linha for linha in linhas if any(palavra in linha for palavra in SO_EM_PORTUGUES)]
        assert not restos, (idioma, restos[:5])
