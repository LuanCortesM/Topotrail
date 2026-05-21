# Guia do usuario - TopoTrail

## O que e

TopoTrail e um plugin QGIS para apoiar planejamento tecnico de trilhas, acessos e deslocamentos de campo em areas naturais e unidades de conservacao.

## Para que serve

O plugin usa relevo, altitude, declividade e curvaturas para gerar:

- raster de adequabilidade topografica;
- raster de risco topografico relativo;
- zonas potenciais;
- rota de menor custo entre origem e destino;
- corredor ao redor da rota.

## TopoTrail como analise de viabilidade topografica

O TopoTrail modela viabilidade topografica para planejamento preliminar de novas trilhas. Ele usa DEM/MDE, declividade, curvaturas, risco topografico relativo, adequabilidade, zonas, rotas e corredores para indicar onde o relevo tende a ser mais favoravel ou desfavoravel.

O plugin nao tenta reconhecer automaticamente estrada, pasto, trilha existente, uso do solo, propriedade, hidrografia ou restricao legal. Essas camadas podem ser cruzadas depois no QGIS como analises complementares, conforme o objetivo do planejamento.

Por isso, uma area visualmente aberta, como pasto ou estrada, pode nao aparecer como potencial se o relevo naquele pixel for penalizado por declividade, curvatura, risco, threshold, NoData ou filtro de area minima. Isso nao significa automaticamente erro do plugin: a pergunta correta e se a exclusao e coerente com a viabilidade topografica calculada.

O resultado deve ser interpretado como uma base topografica preliminar. Para decisao operacional, recomenda-se cruzar as saidas do TopoTrail com hidrografia, trilhas existentes, estradas, uso do solo, areas protegidas, restricoes legais e validacao de campo.

## Requisitos

- QGIS 3.22 ou superior.
- GDAL, NumPy, SciPy, GeoPandas e Shapely disponiveis no ambiente Python do QGIS.
- DEM/MDE com CRS definido.

## Entradas

- DEM/MDE de altitude.
- Raster de declividade.
- Raster de curvatura horizontal.
- Raster de curvatura vertical.
- Pesos dos criterios.
- Ponto inicial e ponto final, se for gerar rota.
- Pasta/arquivo de saida.

## Cuidados com CRS

Calculos de relevo, area, distancia, rota e corredor exigem CRS projetado em metros. Se o DEM estiver em CRS geografico, o processamento prepara um CRS metrico de trabalho quando aplicavel. Raster sem CRS deve ser corrigido na fonte antes de uso cientifico.

## Saidas

- Adequabilidade: valores continuos indicando areas topograficamente mais favoraveis.
- Risco topografico relativo: indicador derivado da adequabilidade e/ou dos criterios topograficos.
- Zonas: poligonos opcionais de areas favoraveis.
- Rota: linha de acesso sugerida.
- Corredor: poligono ao redor da rota.
- Log diagnostico tecnico.

## Como usar

1. Abra o QGIS.
2. Ative o plugin TopoTrail.
3. Abra a interface pelo menu TopoTrail.
4. Selecione os rasters obrigatorios.
5. Configure pesos e parametros.
6. Informe origem e destino se quiser rota.
7. Escolha o arquivo de saida.
8. Execute e revise as camadas geradas.

## Limitacoes metodologicas

- O resultado depende da qualidade e resolucao do DEM.
- Declividade e curvaturas devem preferencialmente estar no mesmo CRS, resolucao, extensao e grid do MDE; se o plugin precisar alinha-las, derivados topograficos podem ser suavizados.
- A rota sugerida e isotropica na versao atual: ela usa superficie de custo e distancia do passo, mas nao diferencia explicitamente subida e descida.
- Constantes internas de custo, risco e normalizacao sao escolhas empiricas do modelo preliminar e devem ser citadas em uso cientifico.
- Pesos devem ter justificativa tecnica.
- Adequabilidade topografica nao substitui validacao de campo.
- O plugin nao considera automaticamente vegetacao, hidrografia, propriedade privada, restricoes legais, estrada, pasto ou trilha existente; essas camadas sao complementares e podem ser cruzadas no QGIS.
- Rotas sugeridas devem ser avaliadas por especialista antes de uso operacional.

## Erros comuns

- Raster sem CRS.
- Rasters desalinhados.
- Pesos com soma zero.
- Origem sem destino ou destino sem origem.
- Caminho de saida sem permissao.
- Arquivos carregados no QGIS bloqueando sobrescrita.
