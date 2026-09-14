"""As saidas vetoriais, escritas com o GDAL de verdade.

O achado que originou este arquivo: apontar a saida para um GeoPackage que ja
existe -- o gesto que a janela do Processing convida a fazer, porque o usuario
costuma ter um so arquivo de projeto com tudo dentro -- chamava
`DeleteDataSource` no arquivo inteiro. As camadas do usuario sumiam, sem aviso,
e o algoritmo relatava sucesso.
"""
import pytest


def _ponto(ogr, x, y):
    geometria = ogr.Geometry(ogr.wkbPoint)
    geometria.AddPoint_2D(x, y)
    return geometria


def _camadas(ogr, caminho):
    fonte = ogr.Open(caminho)
    nomes = sorted(fonte.GetLayerByIndex(i).GetName()
                   for i in range(fonte.GetLayerCount()))
    del fonte
    return nomes


def test_gravar_num_geopackage_existente_preserva_as_outras_camadas(
        plugin, ogr, osr, tmp_path):
    caminho = str(tmp_path / "projeto_do_usuario.gpkg")
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)

    fonte = ogr.GetDriverByName("GPKG").CreateDataSource(caminho)
    for nome in ("pontos_de_campo", "limite_da_propriedade", "amostras_2024"):
        fonte.CreateLayer(nome, srs=srs, geom_type=ogr.wkbPoint)
    del fonte

    plugin.FeatureSet([_ponto(ogr, -45.0, -22.0)], [{"n": 1}],
                      srs.ExportToWkt()).to_file(
        caminho, driver="GPKG", layer_name="rota")

    assert _camadas(ogr, caminho) == [
        "amostras_2024", "limite_da_propriedade", "pontos_de_campo", "rota"], (
        "gravar a rota apagou camadas do usuario")


def test_gravar_a_mesma_camada_duas_vezes_substitui_em_vez_de_empilhar(
        plugin, ogr, osr, tmp_path):
    caminho = str(tmp_path / "saida.gpkg")
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)

    for x in (-45.0, -44.0):
        plugin.FeatureSet([_ponto(ogr, x, -22.0)], [{"n": 1}],
                          srs.ExportToWkt()).to_file(
            caminho, driver="GPKG", layer_name="rota")

    fonte = ogr.Open(caminho)
    assert fonte.GetLayerCount() == 1
    camada = fonte.GetLayerByIndex(0)
    assert camada.GetFeatureCount() == 1, "a segunda execucao empilhou uma copia"
    assert camada.GetNextFeature().GetGeometryRef().GetX() == pytest.approx(-44.0)
    del fonte
