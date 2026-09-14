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


def test_a_legenda_das_classes_viaja_dentro_do_geotiff(plugin, ogr, tmp_path):
    """O rotulo das classes tem de sobreviver ao envio do .tif sozinho.

    O README, a ajuda da janela nos seis idiomas e o capitulo da dissertacao
    afirmam que a legenda e gravada no proprio arquivo. Nao era: o driver GTiff
    guarda nomes de categoria num .aux.xml irmao, e quem enviasse so o .tif
    recebia as cores certas sem saber o que cada uma significa. Os mesmos
    rotulos passaram a ir tambem como metadado GDAL, que fica dentro do TIFF.
    """
    import shutil

    gdal = pytest.importorskip("osgeo.gdal")
    gdal.UseExceptions()
    import numpy as np

    classes = np.array([[1, 2, 3], [4, 5, 1]], dtype=np.uint8)
    base = str(tmp_path / "cena.gpkg")     # a funcao deriva <base>_transitabilidade.tif
    rotulos = {1: "1 - Suave (< 20%)", 2: "2 - Moderada (20-35%)",
               3: "3 - Forte (35-60%)", 4: "4 - Muito forte (60-100%)",
               5: "5 - Escarpada (> 100%)"}
    caminho = plugin.save_transitability_raster(
        classes, (0.0, 30.0, 0.0, 0.0, 0.0, -30.0), "", base, labels=rotulos)
    if not caminho:
        caminho = str(tmp_path / "cena_transitabilidade.tif")

    # so o .tif, sem o arquivo irmao: e o que chega a quem recebe por e-mail
    sozinho = str(tmp_path / "sozinho.tif")
    shutil.copy(caminho, sozinho)
    # a referencia ao dataset precisa sobreviver: um band orfao invalida o SWIG
    fonte = gdal.Open(sozinho)
    banda = fonte.GetRasterBand(1)
    metadados = banda.GetMetadata_Dict()
    for codigo, rotulo in rotulos.items():
        assert metadados.get("TOPOTRAIL_CLASSE_{}".format(codigo)) == rotulo, (
            "a legenda da classe {} nao viajou dentro do arquivo".format(codigo))
    assert banda.GetColorTable() is not None, "as cores tambem precisam estar no arquivo"
    del fonte
