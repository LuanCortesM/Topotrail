"""Aviso de desvio pela declividade maxima, no QGIS de verdade, numa cena com uma escarpa de 90%.

Dois planaltos separados por uma escarpa de 90% de declividade; a unica passagem abaixo de 85% fica a ~4,5 km dos
pontos. A rota existe (contorna pela passagem), e a rota sem o limite cruzaria a escarpa: o plugin tem de avisar e
dizer quanto subir. Numa cena sem escarpa, nada de aviso. A rota nunca muda por causa do aviso.
"""
import json
import os

import numpy as np

from cenas import CENA_GEOTRANSFORM, escrever_dem, escrever_pontos

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXEMPLO = os.path.join(RAIZ, "exemplo")


def _parametros(dem, origem, destino, saida, **extras):
    import importlib.util

    spec = importlib.util.spec_from_file_location("tt_exemplo_parametros_desvio", os.path.join(EXEMPLO, "executar.py"))
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    parametros = modulo.parametros(dem, origem, destino, None, saida)
    parametros.update({"STREAMS_FROM_DEM": False, "GENERATE_ZONES": False})
    parametros.update(extras)
    return parametros


def _xy(linha, coluna):
    x0, dx, _, y0, _, dy = CENA_GEOTRANSFORM
    return x0 + (coluna + 0.5) * dx, y0 + (linha + 0.5) * dy


def _cena(tmp_path, com_escarpa=True):
    z = np.full((200, 100), 100.0)
    if com_escarpa:
        z[:, 49] = 127.0          # escarpa: (154 - 100) / 60 m = 90% na diferenca central
        z[:, 50:] = 154.0
        for linha in range(150, 170):   # a passagem suave, ~4,5 km abaixo (dentro da margem de busca de 5 km)
            z[linha, 30:71] = np.linspace(100.0, 154.0, 41)
    else:
        z += np.linspace(0.0, 30.0, 100)[None, :]
    dem = escrever_dem(str(tmp_path / ("escarpa.tif" if com_escarpa else "suave.tif")), z.astype(np.float32))
    origem = escrever_pontos(str(tmp_path / "o.geojson"), [_xy(5, 20)])
    destino = escrever_pontos(str(tmp_path / "d.geojson"), [_xy(5, 80)])
    return dem, origem, destino


def _evento(resultado, nome):
    with open(resultado["OUTPUT_DEBUG_LOG"], encoding="utf-8") as arquivo:
        eventos = [json.loads(linha) for linha in arquivo if linha.strip()]
    return [e for e in eventos if e.get("event") == nome]


def test_rota_que_contorna_a_escarpa_avisa_quanto_subir(executar, tmp_path):
    dem, origem, destino = _cena(tmp_path)
    resultado, feedback, erro = executar(_parametros(dem, origem, destino, str(tmp_path / "r.gpkg")))
    assert erro is None, (erro, feedback.linhas[-6:])
    avisos = feedback.procurar("contorna terreno")
    assert len(avisos) == 1, feedback.linhas[-8:]
    assert "aumente a declividade maxima para 90%" in avisos[0]
    desvio = _evento(resultado, "desvio_pela_declividade")
    assert desvio and desvio[0]["avisar"] and desvio[0]["razao"] > 2


def test_sem_escarpa_nao_ha_aviso_nem_comparacao(executar, tmp_path):
    dem, origem, destino = _cena(tmp_path, com_escarpa=False)
    resultado, feedback, erro = executar(_parametros(dem, origem, destino, str(tmp_path / "r.gpkg")))
    assert erro is None, erro
    assert not feedback.procurar("contorna terreno")
    # sem celula barrada so pela declividade, a rota sem limite nem e calculada
    assert not _evento(resultado, "desvio_pela_declividade")
