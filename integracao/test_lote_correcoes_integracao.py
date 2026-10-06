"""Execucoes completas que fixam o lote de correcoes da auditoria.

Tudo aqui roda com GDAL e QGIS de verdade: sao defeitos que so aparecem numa
execucao de ponta a ponta, e que os dubles de `tests/` nao poderiam pegar.
"""
import os

import pytest

from cenas import (escrever_dem, escrever_poligonos, escrever_pontos,
                   parametros_base, relevo)


@pytest.fixture()
def cena(tmp_path):
    """MDE sintetico de 60x60 a 30 m, com inicio e fim em celulas validas."""
    dem = escrever_dem(str(tmp_path / "dem.tif"), relevo())
    inicio = escrever_pontos(str(tmp_path / "p0.geojson"), [(500100.0, 7499900.0)])
    fim = escrever_pontos(str(tmp_path / "p1.geojson"), [(501600.0, 7498400.0)])
    return dem, inicio, fim


# ---- 2. OUTPUT_FILE nunca voltava no dicionario de resultados -------------

def test_output_file_volta_no_dicionario_de_resultados(executar, cena, tmp_path):
    """Antes: chaves = [OUTPUT_DEBUG_LOG, OUTPUT_RISK_RASTER, OUTPUT_SCORE_RASTER,
    OUTPUT_TRANSITABILITY, OUTPUT_VECTOR] -- 'OUTPUT_FILE' presente? False.

    Sem a chave o Modelador nao encadeia a saida e o modo lote nao recebe de
    volta o caminho que pediu.
    """
    dem, inicio, fim = cena
    saida = str(tmp_path / "saida.gpkg")
    resultado, feedback, erro = executar(
        parametros_base(dem, saida, inicio, fim, GENERATE_ZONES=False))

    assert erro is None, feedback.linhas[-5:]
    assert "OUTPUT_FILE" in resultado, sorted(resultado)
    assert resultado["OUTPUT_FILE"] == saida


# ---- 3. excecoes nuas viram QgsProcessingException -----------------------

_PESOS_ZERADOS = {"WEIGHT_SLOPE": 0.0, "WEIGHT_CURVH": 0.0, "WEIGHT_CURVV": 0.0}


@pytest.mark.parametrize("extras,trecho", [
    (_PESOS_ZERADOS, "soma dos pesos"),
    ({"SLOPE_MAX": 0.001}, "Nenhuma celula"),
    ({"TRANSITABILITY_BREAKS": "isso nao e numero"}, "limites de transitabilidade"),
    ({"START_POINT_FILE": "/nao/existe.geojson"}, "nao encontrado"),
])
def test_erros_do_usuario_sao_qgsprocessingexception(
        executar, cena, tmp_path, extras, trecho):
    """Antes: Exception/ValueError cruas -- o Processing re-embrulhava com o
    traceback inteiro e a frase escrita para o usuario virava a ultima linha de
    uma pilha com os caminhos absolutos da maquina de quem empacotou.
    """
    from qgis.core import QgsProcessingException

    dem, inicio, fim = cena
    parametros = parametros_base(dem, str(tmp_path / "e.gpkg"), inicio, fim)
    parametros.update(extras)
    resultado, feedback, erro = executar(parametros)

    assert erro is not None, "o caso deveria falhar"
    assert isinstance(erro, QgsProcessingException), type(erro).__name__
    assert trecho in str(erro), str(erro)
    assert "Traceback" not in str(erro)


def test_faixa_de_altitude_fora_do_mde_nao_derruba_rota_nem_rasters(executar, cena, tmp_path):
    """Antes: sem nenhuma celula para as zonas, a execucao inteira parava -- e a
    rota e os rasters, que nao dependem da faixa de altitude, se perdiam."""
    dem, inicio, fim = cena
    parametros = parametros_base(dem, str(tmp_path / "f.gpkg"), inicio, fim,
                                 ALT_MIN=5000.0, ALT_MAX=9000.0)
    resultado, feedback, erro = executar(parametros)
    assert erro is None, (erro, feedback.linhas[-5:])
    assert "OUTPUT_ROUTE" in resultado and "OUTPUT_SCORE_RASTER" in resultado
    assert "OUTPUT_VECTOR" not in resultado
    assert feedback.procurar("zonas nao foram geradas")
    assert feedback.procurar("5000 a 9000 m")


# ---- 4. excecoes do GDAL so no escopo do algoritmo -----------------------

def test_importar_o_plugin_nao_liga_as_excecoes_do_gdal():
    """Antes: gdal.UseExceptions()/ogr.UseExceptions() no import.

    Medido na auditoria: antes de importar o TopoTrail,
    gdal.GetUseExceptions() = 0 e gdal.Open de arquivo inexistente devolvia
    None; depois do import, 1 e RuntimeError -- para todo outro plugin do
    processo QGIS e para o codigo Python do proprio QGIS. O subprocesso e
    proposital: dentro do pytest outra fixture ja pode ter ligado as excecoes.
    """
    import subprocess
    import sys as _sys

    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    programa = (
        "import sys\n"
        "sys.path.insert(0, %r)\n"
        "from osgeo import gdal, ogr\n"
        "antes = (gdal.GetUseExceptions(), ogr.GetUseExceptions())\n"
        "import importlib\n"
        "importlib.import_module('%s.processing.algorithm')\n"
        "depois = (gdal.GetUseExceptions(), ogr.GetUseExceptions())\n"
        "try:\n"
        "    aberto = repr(gdal.Open('/nao/existe.tif'))\n"
        "except Exception:\n"
        "    aberto = 'LEVANTOU'\n"
        "print(antes, depois, aberto)\n"
    ) % (os.path.dirname(raiz), os.path.basename(raiz))
    concluido = subprocess.run(
        [_sys.executable, "-c", programa], capture_output=True, text=True)
    if concluido.returncode != 0:
        pytest.skip("plugin nao importavel em subprocesso: "
                    + concluido.stderr[-300:])
    assert concluido.stdout.strip().splitlines()[-1] == "(0, 0) (0, 0) None", (
        concluido.stdout)


def test_o_algoritmo_liga_e_devolve_o_estado_das_excecoes(plugin, qgis_app, cena,
                                                          tmp_path):
    """Durante a execucao as excecoes valem; depois dela o estado volta ao que era.

    Antes, ligadas no import, elas ja valiam para o processo inteiro e o
    algoritmo nao tinha escopo nenhum: desligando-as antes da execucao, a
    execucao inteira rodava com elas desligadas.
    """
    from osgeo import gdal, ogr
    from qgis.core import QgsProcessingContext, QgsProcessingFeedback

    class _Espia(QgsProcessingFeedback):
        def __init__(self):
            super().__init__()
            self.estados = []

        def pushInfo(self, mensagem):
            self.estados.append(
                (gdal.GetUseExceptions(), ogr.GetUseExceptions()))

    ogr.DontUseExceptions()   # ordem inversa: no GDAL < 3.7 e uma pilha
    gdal.DontUseExceptions()
    dem, inicio, fim = cena
    algoritmo = plugin.TopotrailAlgorithm()
    algoritmo.initAlgorithm()
    espia = _Espia()
    algoritmo.processAlgorithm(
        parametros_base(dem, str(tmp_path / "x.gpkg"), inicio, fim,
                        GENERATE_ZONES=False),
        QgsProcessingContext(), espia)

    assert espia.estados, "o algoritmo nao emitiu nenhuma linha de feedback"
    assert all(estado == (1, 1) for estado in espia.estados), set(espia.estados)
    assert (gdal.GetUseExceptions(), ogr.GetUseExceptions()) == (0, 0)


def test_o_ramo_de_erro_amigavel_volta_a_ser_alcancavel(plugin, qgis_app):
    """Antes: com as excecoes ligadas no import, gdal.Open levantava antes de
    devolver None e as oito mensagens amigaveis viravam codigo morto --
    raster_metadata('/nao/existe.tif') entregava
    'RuntimeError: /nao/existe.tif: No such file or directory'.
    Agora a mesma frase sai com as excecoes ligadas e desligadas.
    """
    from osgeo import gdal, ogr

    for ligadas in (True, False):
        if ligadas:
            gdal.UseExceptions()
            ogr.UseExceptions()
        else:
            ogr.DontUseExceptions()
            gdal.DontUseExceptions()
        with pytest.raises(Exception) as capturado:
            plugin.raster_metadata("/nao/existe.tif")
        assert "Nao foi possivel abrir raster para metadados" in str(capturado.value), (
            ligadas, str(capturado.value))
    ogr.DontUseExceptions()   # ordem inversa: no GDAL < 3.7 e uma pilha
    gdal.DontUseExceptions()


# ---- 5. legenda gravada no raster segue TRANSITABILITY_BREAKS -------------

def test_legenda_gravada_no_raster_segue_os_limites_escolhidos(executar, cena,
                                                               tmp_path):
    """Antes (caso P15 da auditoria), com TRANSITABILITY_BREAKS = '2, 4, 6, 8':
    legenda_no_raster = ['', '1 - Suave (< 20%)', '2 - Moderada (20-35%)',
    '3 - Forte (35-60%)', '4 - Muito forte (60-100%)', '5 - Escarpada (> 100%)']
    -- os limites de fabrica, contradizendo o dado gravado no mesmo arquivo.
    """
    import xml.etree.ElementTree as ET

    dem, inicio, fim = cena
    resultado, feedback, erro = executar(
        parametros_base(dem, str(tmp_path / "p15.gpkg"), inicio, fim,
                        GENERATE_ZONES=False,
                        TRANSITABILITY_BREAKS="2, 4, 6, 8"))
    assert erro is None, feedback.linhas[-5:]

    # O GeoTIFF nao tem lugar padrao para nomes de categoria: o GDAL os grava
    # no .aux.xml irmao, que e de onde a auditoria leu a legenda errada.
    lateral = resultado["OUTPUT_TRANSITABILITY"] + ".aux.xml"
    assert os.path.exists(lateral), lateral
    categorias = [no.text or "" for no in
                  ET.parse(lateral).getroot().iter("Category")]
    assert categorias == ["", "1 - Suave (< 2%)", "2 - Moderada (2-4%)",
                          "3 - Forte (4-6%)", "4 - Muito forte (6-8%)",
                          "5 - Escarpada (> 8%)"], categorias


# ---- 6. teto e aviso de memoria tambem no caminho "rasters proprios" -----

@pytest.fixture()
def cena_rasters(tmp_path, cena):
    """A mesma cena, com declividade e curvaturas prontas na grade do MDE."""
    import numpy as np
    from osgeo import gdal

    dem, inicio, fim = cena
    fonte = gdal.Open(dem)
    z = fonte.GetRasterBand(1).ReadAsArray().astype("float32")
    del fonte
    dz_dy, dz_dx = np.gradient(z, 30.0, 30.0)
    caminhos = {
        "INPUT_SLOPE": escrever_dem(str(tmp_path / "slope.tif"),
                                    (np.hypot(dz_dx, dz_dy) * 100.0).astype("float32")),
        "INPUT_CURVH": escrever_dem(str(tmp_path / "curvh.tif"),
                                    np.gradient(dz_dx, 30.0, axis=1).astype("float32")),
        "INPUT_CURVV": escrever_dem(str(tmp_path / "curvv.tif"),
                                    np.gradient(dz_dy, 30.0, axis=0).astype("float32")),
    }
    caminhos.update(DERIVE_FROM_DEM=False, SLOPE_UNIT=0)
    return dem, inicio, fim, caminhos


def _terrain(plugin):
    import importlib

    return importlib.import_module(plugin.__name__.rsplit(".", 1)[0] + ".terrain")


def test_aviso_de_memoria_tambem_quando_o_usuario_traz_os_rasters(
        executar, plugin, cena_rasters, tmp_path, monkeypatch):
    """Antes (E1 x E2 da auditoria, mesma grade de 9.000.000 de celulas):
    [E1_deriva] aviso_MDE_grande presente, 96 B/celula;
    [E2_rasters_fornecidos] aviso_MDE_grande NENHUM, 103 B/celula --
    o caminho sem aviso gastava mais memoria que o que avisava.
    """
    terrain = _terrain(plugin)
    monkeypatch.setattr(terrain, "WARN_TERRAIN_CELLS", 100)
    dem, inicio, fim, proprios = cena_rasters
    resultado, feedback, erro = executar(
        parametros_base(dem, str(tmp_path / "m.gpkg"), inicio, fim,
                        GENERATE_ZONES=False, **proprios))
    assert erro is None, feedback.linhas[-5:]
    assert feedback.procurar("MDE grande"), feedback.linhas[:10]


def test_teto_de_memoria_tambem_quando_o_usuario_traz_os_rasters(
        executar, plugin, cena_rasters, tmp_path, monkeypatch):
    """Uma grade acima de MAX_TERRAIN_CELLS passava pelo teto sem ser barrada."""
    from qgis.core import QgsProcessingException

    terrain = _terrain(plugin)
    monkeypatch.setattr(terrain, "MAX_TERRAIN_CELLS", 100)
    dem, inicio, fim, proprios = cena_rasters
    resultado, feedback, erro = executar(
        parametros_base(dem, str(tmp_path / "t.gpkg"), inicio, fim,
                        GENERATE_ZONES=False, **proprios))
    assert isinstance(erro, QgsProcessingException), erro
    assert "Recorte o MDE" in str(erro), str(erro)


# ---- 8. restricao mais fina que o pixel avisa em vez de sumir -------------

def test_restricao_mais_fina_que_o_pixel_avisa(executar, cena, tmp_path):
    """Antes (caso B1 da auditoria): cerca de 5 m atravessando toda a cena num
    pixel de 30 m -> 'Camada de restricao: 1 feicoes, buffer de 0 m,
    0 celulas atingidas (0.00% da grade).' como informacao, nenhuma mensagem
    'Restricoes:' e o comprimento devolvido igual ao da rota sem restricao.
    """
    dem, inicio, fim = cena
    # Faixa de 5 m de largura atravessando a cena inteira na diagonal do
    # retangulo: intersecta a grade, mas nao cobre nenhum centro de celula.
    faixa = escrever_poligonos(str(tmp_path / "cerca.gpkg"), [
        "POLYGON ((500000 7499000, 501800 7499000, 501800 7499005, "
        "500000 7499005, 500000 7499000))"])
    resultado, feedback, erro = executar(
        parametros_base(dem, str(tmp_path / "b1.gpkg"), inicio, fim,
                        GENERATE_ZONES=False, CONSTRAINT_LAYER=faixa,
                        CONSTRAINT_BUFFER_M=0.0, CONSTRAINT_MODE=0))
    assert erro is None, feedback.linhas[-5:]
    assert feedback.procurar("0 celulas atingidas"), "a cena escolhida nao reproduz o caso"
    avisos = feedback.procurar("nao atingiu nenhuma celula")
    assert avisos, [linha for linha in feedback.linhas if "restricao" in linha.lower()]
    assert "buffer" in avisos[0]


# ---- 9. deslocamento do ponto pedido sai no log e vira aviso --------------

def test_ponto_deslocado_e_relatado_com_a_distancia(executar, plugin, tmp_path):
    """Antes (13_cerca_realista / 12_silencios X2): o ponto pedido virava outro
    ate 30 celulas longe -- 7.500 m medidos numa celula de 500 m -- com
    'qualquer_mensagem_sobre_deslocamento: (NENHUMA)'.
    """
    import json

    # Celula de 500 m, com um buraco de NoData de 9x9 celulas em volta do
    # ponto inicial: o deslocamento medido passa de 100 m com folga.
    geotransform = (300000.0, 500.0, 0.0, 7500000.0, 0.0, -500.0)
    matriz = relevo(60, 60)
    matriz[10:19, 10:19] = -9999.0
    dem = escrever_dem(str(tmp_path / "grosso.tif"), matriz,
                       geotransform=geotransform, nodata=-9999.0)
    inicio = escrever_pontos(str(tmp_path / "i.geojson"),
                             [(300000.0 + 500.0 * 14.5, 7500000.0 - 500.0 * 14.5)])
    fim = escrever_pontos(str(tmp_path / "f.geojson"),
                          [(300000.0 + 500.0 * 40.5, 7500000.0 - 500.0 * 40.5)])

    resultado, feedback, erro = executar(
        parametros_base(dem, str(tmp_path / "d.gpkg"), inicio, fim,
                        GENERATE_ZONES=False))
    assert erro is None, feedback.linhas[-5:]

    avisos = [linha for linha in feedback.linhas
              if linha.startswith("AVISO: ") and "foi movido" in linha]
    assert avisos, [linha for linha in feedback.linhas if "ponto" in linha.lower()]
    assert "O comprimento, o tempo e o ganho" in avisos[0]

    registro = [json.loads(linha) for linha in
                open(resultado["OUTPUT_DEBUG_LOG"], encoding="utf-8")
                if '"pontos_deslocados"' in linha]
    assert registro, "o deslocamento nao foi ao log de diagnostico"
    pontos = registro[-1]["pontos"]
    assert pontos[0]["deslocamento_m"] > 100.0, pontos


def test_deslocamento_pequeno_nao_vira_aviso(executar, cena, tmp_path):
    """Um empurrao de uma celula de 30 m fica dentro do corredor entregue:
    informa, mas nao avisa -- o aviso precisa significar alguma coisa."""
    import numpy as np

    dem, inicio, fim = cena
    from osgeo import gdal
    fonte = gdal.Open(dem)
    matriz = fonte.GetRasterBand(1).ReadAsArray()
    del fonte
    matriz = np.array(matriz)
    matriz[2:5, 2:5] = -9999.0
    dem2 = escrever_dem(str(tmp_path / "furo.tif"), matriz, nodata=-9999.0)
    inicio2 = escrever_pontos(str(tmp_path / "i2.geojson"),
                              [(500000.0 + 30.0 * 3.5, 7500000.0 - 30.0 * 3.5)])

    resultado, feedback, erro = executar(
        parametros_base(dem2, str(tmp_path / "p.gpkg"), inicio2, fim,
                        GENERATE_ZONES=False))
    assert erro is None, feedback.linhas[-5:]
    movidos = [linha for linha in feedback.linhas if "foi movido" in linha]
    assert movidos, feedback.linhas[:12]
    assert not any(linha.startswith("AVISO: ") for linha in movidos), movidos


# ---- 10. sentinela nao declarada num raster fornecido pelo usuario --------

def test_sentinela_num_raster_de_criterio_avisa_nomeando_o_raster(
        executar, cena_rasters, tmp_path):
    """Antes (15_criterio_degenerado.py): 2% das linhas em -3.4e38 sem NoData
    declarado levaram 'Curvatura horizontal: alvo=0.0000, limite=0.0004' para
    'limite=33999999521443642490773241379936429670' e a nota media de 0,656
    para 0,984, com 'avisos: (NENHUM)'.
    """
    import numpy as np
    from osgeo import gdal

    dem, inicio, fim, proprios = cena_rasters
    fonte = gdal.Open(proprios["INPUT_CURVH"])
    curvatura = np.array(fonte.GetRasterBand(1).ReadAsArray())
    del fonte
    curvatura[::50, :] = -3.4e38            # sem NoData declarado, de proposito
    proprios = dict(proprios)
    proprios["INPUT_CURVH"] = escrever_dem(
        str(tmp_path / "curvh_sujo.tif"), curvatura.astype("float32"))

    resultado, feedback, erro = executar(
        parametros_base(dem, str(tmp_path / "s.gpkg"), inicio, fim,
                        GENERATE_ZONES=False, **proprios))
    assert erro is None, feedback.linhas[-5:]
    avisos = [linha for linha in feedback.linhas
              if linha.startswith("AVISO: ") and "Curvatura horizontal" in linha]
    assert avisos, [linha for linha in feedback.linhas if "Curvatura" in linha]
    assert any("escala fisica" in aviso or "limite do percentil" in aviso
               for aviso in avisos), avisos

