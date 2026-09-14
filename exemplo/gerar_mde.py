#!/usr/bin/env python3
"""Gera o MDE sintetico do exemplo a partir de uma funcao analitica de relevo.

Por que sintetico: o exemplo precisa ser redistribuivel sem nenhuma questao de
licenca e reproduzivel byte a byte em qualquer maquina. Um recorte de MDE de
terceiros carregaria os termos de uso da fonte, e os trajetos de GPS de campo do
autor nao sao redistribuidos por conterem localidades de ocorrencia de especies.
A alternativa e um relevo escrito por extenso: a superficie abaixo e uma soma de
termos analiticos, sem nenhum numero aleatorio, entao o arquivo que sai desta
maquina e o mesmo que sai da sua.

O relevo tem, de proposito, as feicoes de que o TopoTrail precisa para exercitar
todas as suas etapas:

  * dois macicos separados por um vale, para que exista um colo por onde passar
    e nao apenas uma linha reta;
  * corrugacao em cristas e talvegues, para que a extracao de drenagem tenha
    canais de verdade a encontrar;
  * um vale principal meandrante cortando a cena de lado a lado, para que a rota
    tenha de atravessa-lo e a camada de travessias saia com feicoes;
  * declividades de 0 a mais de 100%, para que as cinco classes de
    transitabilidade sejam todas povoadas.

    python3 exemplo/gerar_mde.py
"""
import os

import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()

PASTA = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.path.join(PASTA, "mde.tif")

# Grade de trabalho: 300 x 300 celulas de 30 m = 9 km x 9 km, em UTM 23S
# (EPSG:32723), que e metrico. O plugin aceita MDE geografico e reprojeta
# sozinho, mas um exemplo nao deve depender dessa etapa para funcionar.
COLUNAS = 300
LINHAS = 300
CELULA_M = 30.0
EPSG = 32723
ORIGEM_X = 500000.0
ORIGEM_Y = 7500000.0


def superficie():
    """Devolve a matriz de altitudes em metros, float32.

    Os eixos X e Y estao em metros a partir do canto superior esquerdo da cena.
    Cada termo e comentado com o que ele produz no terreno.
    """
    coluna, linha = np.meshgrid(np.arange(COLUNAS), np.arange(LINHAS))
    x = coluna * CELULA_M
    y = linha * CELULA_M

    # Base regional: a cena desce de norte para sul.
    z = 900.0 + 0.045 * (LINHAS * CELULA_M - y)

    # Dois macicos. O do norte e mais alto; o do sul e mais largo e mais baixo.
    z += 780.0 * np.exp(-(((x - 2700.0) ** 2 + (y - 2400.0) ** 2)
                          / (2.0 * 1450.0 ** 2)))
    z += 560.0 * np.exp(-(((x - 6600.0) ** 2 + (y - 6300.0) ** 2)
                          / (2.0 * 1650.0 ** 2)))

    # Corrugacao em cristas e talvegues: e ela que da canais para a drenagem
    # encontrar e formas concavas e convexas para as curvaturas medirem.
    z += 95.0 * np.sin(2.0 * np.pi * x / 2100.0) * np.cos(2.0 * np.pi * y / 2700.0)
    z += 38.0 * np.sin(2.0 * np.pi * (x + y) / 1300.0)

    # Vale principal meandrante, de oeste para leste: e o que a rota tera de
    # atravessar. A incisao e gaussiana em torno do eixo do vale.
    eixo = 4500.0 + 900.0 * np.sin(2.0 * np.pi * x / 7000.0)
    z -= 230.0 * np.exp(-(((y - eixo) ** 2) / (2.0 * 430.0 ** 2)))

    # Escarpa: um degrau de 130 m de altura em cerca de 40 m de distancia
    # horizontal, no flanco norte do macico do sul, com atenuacao gaussiana nas
    # pontas para nao virar um paredao de lado a lado da cena. E ela que povoa a
    # classe 5 de transitabilidade e obriga a rota a contornar alguma coisa.
    z += (130.0 * np.tanh((y - 6900.0) / 40.0)
          * np.exp(-(((x - 4200.0) ** 2) / (2.0 * 1100.0 ** 2))))

    return z.astype(np.float32)


def gravar(matriz, caminho=SAIDA):
    driver = gdal.GetDriverByName("GTiff")
    fonte = driver.Create(caminho, COLUNAS, LINHAS, 1, gdal.GDT_Float32,
                          options=["COMPRESS=DEFLATE", "PREDICTOR=3",
                                   "ZLEVEL=9", "TILED=NO"])
    fonte.SetGeoTransform((ORIGEM_X, CELULA_M, 0.0, ORIGEM_Y, 0.0, -CELULA_M))
    referencia = osr.SpatialReference()
    referencia.ImportFromEPSG(EPSG)
    fonte.SetProjection(referencia.ExportToWkt())
    banda = fonte.GetRasterBand(1)
    banda.WriteArray(matriz)
    banda.FlushCache()
    fonte = None
    return caminho


def main():
    matriz = superficie()
    caminho = gravar(matriz)
    print("{}: {} x {} celulas de {:.0f} m, altitude {:.1f} a {:.1f} m, {:.0f} kB".format(
        os.path.basename(caminho), COLUNAS, LINHAS, CELULA_M,
        float(matriz.min()), float(matriz.max()),
        os.path.getsize(caminho) / 1024.0))


if __name__ == "__main__":
    main()
