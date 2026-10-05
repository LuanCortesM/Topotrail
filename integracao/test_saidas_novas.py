"""Corredor de alternativas, limites de normalizacao e parametros avancados,
no QGIS de verdade, sobre o MDE do exemplo."""
import json
import os

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXEMPLO = os.path.join(RAIZ, "exemplo")


def _parametros(saida, **extras):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "tt_exemplo_parametros", os.path.join(EXEMPLO, "executar.py"))
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    parametros = modulo.parametros(
        os.path.join(EXEMPLO, "mde.tif"), os.path.join(EXEMPLO, "origem.geojson"),
        os.path.join(EXEMPLO, "destino.geojson"), None, saida)
    parametros.update({"STREAMS_FROM_DEM": False, "GENERATE_ZONES": False})
    parametros.update(extras)
    return parametros


def _primeira_feicao(ogr, caminho):
    """(fonte, feicao): a fonte precisa continuar viva enquanto a feicao e lida."""
    fonte = ogr.Open(caminho)
    return fonte, fonte.GetLayer(0).GetNextFeature()


def _eventos(log):
    with open(log, encoding="utf-8") as arquivo:
        return [json.loads(linha) for linha in arquivo if linha.strip()]


def test_o_corredor_de_alternativas_contem_a_rota(executar, ogr, tmp_path):
    resultado, feedback, erro = executar(_parametros(str(tmp_path / "a.gpkg"),
                                                     ROUTE_ALTERNATIVES_PCT=5.0))
    assert erro is None, (erro, feedback.linhas[-5:])
    assert os.path.isfile(resultado["OUTPUT_ALTERNATIVES"])
    assert os.path.isfile(resultado["OUTPUT_SLACK"])
    fonte = ogr.Open(resultado["OUTPUT_ALTERNATIVES"])
    camada = fonte.GetLayer(0)
    assert camada.GetFeatureCount() == 1
    feicao = camada.GetNextFeature()
    corredor = feicao.GetGeometryRef().Clone()
    assert feicao.GetField("folga_pct") == pytest.approx(5.0)
    assert feicao.GetField("area_ha") > 0
    fonte_rota, feicao_rota = _primeira_feicao(ogr, resultado["OUTPUT_ROUTE"])
    rota = feicao_rota.GetGeometryRef().Clone()
    # a rota passa pelos centros das celulas do corredor
    assert corredor.Buffer(1.0).Contains(rota)
    assert feedback.procurar("Corredor de alternativas")


def test_sem_folga_nao_ha_corredor_de_alternativas(executar, tmp_path):
    resultado, feedback, erro = executar(_parametros(str(tmp_path / "b.gpkg")))
    assert erro is None, erro
    assert "OUTPUT_ALTERNATIVES" not in resultado
    assert not (tmp_path / "b_alternativas.gpkg").exists()


def test_fixar_os_limites_registrados_reproduz_a_execucao(executar, ogr, tmp_path):
    """O log grava os limites que a cena produziu; passá-los de volta como
    parametro tem de dar a mesma rota -- e e isso que permite comparar recortes."""
    resultado, _, erro = executar(_parametros(str(tmp_path / "auto.gpkg")))
    assert erro is None, erro
    limites = [e for e in _eventos(resultado["OUTPUT_DEBUG_LOG"])
               if e.get("event") == "limites_normalizacao"][-1]
    assert limites["origem"]["curvatura_horizontal"].startswith("cena")
    fixos, _, erro = executar(_parametros(
        str(tmp_path / "fixo.gpkg"),
        CURVH_LIMIT=limites["limites"]["curvatura_horizontal"],
        CURVV_LIMIT=limites["limites"]["curvatura_vertical"]))
    assert erro is None, erro
    origem = [e for e in _eventos(fixos["OUTPUT_DEBUG_LOG"])
              if e.get("event") == "limites_normalizacao"][-1]["origem"]
    assert origem["curvatura_horizontal"] == "parametro"

    def wkb(caminho):
        fonte, feicao = _primeira_feicao(ogr, caminho)
        return bytes(feicao.GetGeometryRef().ExportToWkb())

    assert wkb(resultado["OUTPUT_ROUTE"]) == wkb(fixos["OUTPUT_ROUTE"])


def test_a_velocidade_de_campo_vira_atributo_da_rota(executar, ogr, tmp_path):
    resultado, _, erro = executar(_parametros(str(tmp_path / "v.gpkg"), FIELD_SPEED_KMH=3.0))
    assert erro is None, erro
    fonte, feicao = _primeira_feicao(ogr, resultado["OUTPUT_ROUTE"])
    assert feicao.GetField("velocidade_campo_kmh") == pytest.approx(3.0)
    assert feicao.GetField("tempo_campo_h") == pytest.approx(feicao.GetField("tempo_h") * 6.0 / 3.0)


def test_com_celula_fixa_dois_recortes_dao_a_mesma_rota(executar, ogr, tmp_path):
    """MDE em graus, como o Topodata ou o SRTM: sem celula fixa, cada recorte
    e reprojetado para uma grade UTM propria e a rota pode mudar com a margem.
    Com WORKING_CELL_M a grade e a mesma, e a rota tambem."""
    from osgeo import gdal

    geografico = str(tmp_path / "mde_graus.tif")
    assert gdal.Warp(geografico, os.path.join(EXEMPLO, "mde.tif"), dstSRS="EPSG:4326",
                     resampleAlg="bilinear") is not None
    info = gdal.Info(geografico, format="json")["cornerCoordinates"]
    oeste, norte = info["upperLeft"]
    leste, sul = info["lowerRight"]
    recortes = []
    for i, margem in enumerate((0.004, 0.006)):
        caminho = str(tmp_path / "recorte{}.tif".format(i))
        gdal.Translate(caminho, geografico, projWin=[oeste + margem, norte - margem,
                                                     leste - margem, sul + margem])
        recortes.append(caminho)

    # Pontos no interior, a mais de 2 km das bordas: perto da borda os dois
    # recortes diferem de verdade (derivadas e NoData da reprojecao), e isso nao
    # e o que se mede aqui.
    from cenas import escrever_pontos
    origem = escrever_pontos(str(tmp_path / "o.geojson"), [(503000.0, 7494000.0)])
    destino = escrever_pontos(str(tmp_path / "d.geojson"), [(506000.0, 7497000.0)])

    def rota(mde, nome, **extras):
        parametros = _parametros(str(tmp_path / nome), **extras)
        parametros.update({"INPUT_DEM": mde, "START_POINT_FILE": origem,
                           "END_POINT_FILE": destino})
        resultado, feedback, erro = executar(parametros)
        assert erro is None, (erro, feedback.linhas[-5:])
        fonte, feicao = _primeira_feicao(ogr, resultado["OUTPUT_ROUTE"])
        return bytes(feicao.GetGeometryRef().ExportToWkb()), resultado

    # A receita completa: celula fixa e limites de normalizacao fixos (os que
    # uma execucao de referencia registrou no log).
    _, referencia = rota(recortes[0], "ref.gpkg", WORKING_CELL_M=30.0)
    limites = [e for e in _eventos(referencia["OUTPUT_DEBUG_LOG"])
               if e.get("event") == "limites_normalizacao"][-1]["limites"]
    fixos = dict(WORKING_CELL_M=30.0, CURVH_LIMIT=limites["curvatura_horizontal"],
                 CURVV_LIMIT=limites["curvatura_vertical"])
    a, ra = rota(recortes[0], "a.gpkg", **fixos)
    b, rb = rota(recortes[1], "b.gpkg", **fixos)
    assert a == b
    for resultado in (ra, rb):
        lidos = [e for e in _eventos(resultado["OUTPUT_DEBUG_LOG"])
                 if e.get("event") == "rasters_lidos"][-1]
        x0, pixel = lidos["transform"][0], lidos["transform"][1]
        assert pixel == pytest.approx(30.0)
        assert x0 / 30.0 == pytest.approx(round(x0 / 30.0), abs=1e-6)


def test_parametros_de_especialista_ficam_em_avancados(plugin, qgis_app):
    algoritmo = plugin.TopotrailAlgorithm()
    algoritmo.initAlgorithm()
    avancado = plugin._flag_avancado()
    assert avancado is not None
    for chave in ("ROUTE_MARGIN_M", "CURVH_LIMIT", "FIELD_SPEED_KMH", "TRANSITABILITY_BREAKS"):
        assert algoritmo.parameterDefinition(chave).flags() & avancado, chave
    for chave in ("INPUT_DEM", "START_POINT_FILE", "ROUTE_ALTERNATIVES_PCT", "OUTPUT_FILE"):
        assert not (algoritmo.parameterDefinition(chave).flags() & avancado), chave
