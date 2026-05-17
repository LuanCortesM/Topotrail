# Metodologia TopoTrail

## Modelo conceitual

TopoTrail combina criterios topograficos para estimar adequabilidade relativa de deslocamento em campo e apoiar planejamento de trilhas e acessos.

## TopoTrail como analise de viabilidade topografica

O objetivo metodologico do TopoTrail e modelar viabilidade topografica para planejamento preliminar de novas trilhas. A unidade de analise principal e o relevo representado pelo DEM/MDE, combinado com declividade, curvaturas, adequabilidade, risco topografico relativo, zonas potenciais, rotas e corredores.

O plugin nao modela caminhabilidade territorial completa. Ele nao reconhece automaticamente estradas, trilhas existentes, pastos, areas abertas, uso do solo, propriedade, hidrografia ou restricoes legais. Esses temas sao complementares e devem ser cruzados posteriormente no QGIS quando o planejamento exigir uma leitura territorial mais ampla.

Assim, uma estrada ou pasto visualmente caminhavel pode ser classificado como pouco favoravel se, topograficamente, apresentar declividade, curvatura, risco, fragmentacao, NoData ou margem de threshold desfavoravel. Essa divergencia deve ser interpretada como diferenca entre viabilidade topografica e caminhabilidade observada/territorial, nao como bug automatico.

As saidas do TopoTrail sao defensaveis como camada tecnica topografica preliminar. A decisao final deve integrar outras camadas tematicas e validacao de campo.

## CRS metrico

Calculos de declividade, curvatura, area, distancia, rota e corredor dependem de unidades metricas. Por isso, o processamento deve ocorrer em CRS projetado.

## Reprojecao para UTM

Quando a entrada esta em CRS geografico, o CRS UTM de trabalho pode ser escolhido a partir do centro do raster. No hemisferio sul usa EPSG:327xx; no hemisferio norte usa EPSG:326xx.

## Alinhamento raster

Rasters auxiliares devem compartilhar CRS, dimensoes, resolucao, extensao e GeoTransform com o DEM de referencia.

## NoData

NoData e convertido para NaN nos arrays numericos. Pixels invalidos nao devem entrar como valores validos na adequabilidade.

## Declividade

A declividade deve considerar o tamanho real do pixel:

```text
dy, dx = np.gradient(dem, pixel_size_y, pixel_size_x)
slope = degrees(arctan(sqrt(dx^2 + dy^2)))
```

## Curvaturas

Curvaturas horizontal e vertical sao tratadas como criterios topograficos normalizados/pontuados, respeitando NoData e resolucao espacial.

## Adequabilidade multicriterio

A combinacao principal e:

```text
S = (w_alt * A + w_slope * D + w_curv_h * CH + w_curv_v * CV) / soma_dos_pesos
```

Onde:

- `S`: adequabilidade final;
- `A`: altitude normalizada;
- `D`: declividade normalizada invertida;
- `CH`: curvatura horizontal pontuada;
- `CV`: curvatura vertical pontuada;
- `w`: peso definido pelo usuario.

## Risco topografico relativo

O risco e tratado como indicador relativo derivado dos criterios topograficos e da adequabilidade. Deve ser interpretado como apoio tecnico, nao como mapa absoluto de perigo.

## Rota de menor custo

A rota usa uma superficie de custo derivada da adequabilidade e dos criterios topograficos. Celas NoData ou bloqueadas nao devem ser atravessadas.

## Corredor

O corredor e um buffer metrico ao redor da rota. Sua largura e interpretada em metros.

## Limitacoes

- DEM ruim gera resultado ruim.
- Resolucao espacial altera declividade e curvatura.
- Pesos sao subjetivos e devem ser justificados.
- O resultado nao substitui validacao de campo.
- Camadas como hidrografia, trilhas existentes, estradas, uso do solo, propriedade, vegetacao e restricoes legais sao complementares ao nucleo topografico e podem ser integradas no QGIS conforme o objetivo do estudo.
