# TopoTrail

TopoTrail e um plugin para QGIS voltado ao planejamento preliminar de trilhas, acessos e deslocamentos de campo em areas naturais e unidades de conservacao.

A ferramenta modela **viabilidade topografica** a partir de Modelo Digital de Elevacao, declividade e curvaturas do relevo por analise multicriterio em SIG. O resultado principal e um raster continuo de adequabilidade topografica. A partir dele, o plugin tambem pode gerar zonas potenciais, uma rota sugerida entre origem e destino e um corredor de acesso ao redor dessa rota.

O TopoTrail nao tenta reconhecer automaticamente estradas, pastos, trilhas existentes, uso do solo, hidrografia ou restricoes legais. Essas camadas sao complementares e podem ser cruzadas posteriormente no QGIS conforme o objetivo do planejamento.

## Status da versao

Versao atual: `0.5.0`.

Esta e uma versao experimental para testes de viabilidade topografica. Use os resultados como apoio tecnico preliminar e valide em campo antes de qualquer decisao operacional.

A interface grafica inclui um seletor simples `PT-BR | ENG` para alternar entre portugues e ingles.

## Changelog

### 0.5.0

- A documentacao em ingles passa a ser a documentacao principal para publicacao e revisao externa.
- As copias de referencia em portugues foram preservadas em `docs/pt_BR`.
- A interface grafica recebeu um seletor `PT-BR | ENG`.
- Codigo helper legado e incompleto foi removido da arvore ativa do plugin.
- O fluxo validado de adequabilidade topografica, risco relativo, rota e corredor foi preservado.

Repositorio: https://github.com/LuanCortesM/Topotrail

Problemas e sugestoes: https://github.com/LuanCortesM/Topotrail/issues

## Instalacao para testes

1. Baixe o arquivo `TopoTrail.zip` da versao publicada.
2. No QGIS, abra `Complementos > Gerenciar e Instalar Complementos`.
3. Escolha `Instalar a partir de ZIP`.
4. Selecione `TopoTrail.zip`.
5. Ative o plugin TopoTrail.

Requisitos principais:

- QGIS 3.22 ou superior.
- Ambiente QGIS com GDAL, NumPy, SciPy, GeoPandas e Shapely disponiveis.
- DEM/MDE e rasters auxiliares com CRS definido.

## Creditos

Desenvolvedor: Luan da Silva Cortes Maciel (MACIEL, L. S.)

Orientador: Leandro Freitas

Contexto: desenvolvido como produto da pesquisa de mestrado em Biodiversidade em Unidades de Conservacao, vinculada a Escola Nacional de Botanica Tropical e ao Jardim Botanico do Rio de Janeiro.

Projeto associado: Herpeto Mantiqueira.

## Entradas

- Modelo Digital de Elevacao
- Declividade
- Curvatura horizontal
- Curvatura vertical
- Ponto inicial e ponto final, opcionais, para planejamento de acesso
- Coordenadas de origem e destino, ou captura direta dos pontos no mapa do QGIS

## Saidas

- Raster continuo de adequabilidade topografica
- Vetor com zonas potenciais de trilhas e areas de acesso
- Rota sugerida de acesso, quando origem e destino sao informados
- Corredor de acesso ao redor da rota sugerida

## Metodologia

O TopoTrail combina restricoes booleanas, como intervalo altimetrico e declividade maxima absoluta, com combinacao linear ponderada dos criterios topograficos. A declividade e tratada como custo, enquanto as curvaturas sao avaliadas pela proximidade a formas menos extremas do relevo.

Antes dos calculos espaciais, o plugin prepara um CRS de trabalho projetado em metros. Se o MDE estiver em CRS geografico, o centro do raster e usado para escolher automaticamente a zona UTM adequada. Para o Sudeste do Brasil, isso normalmente resulta em EPSG:32723, mas a regra e generica para outros hemisferios e longitudes. Os rasters de declividade e curvaturas sao validados contra o MDE e, quando necessario, alinhados para a mesma grade, resolucao, extensao e CRS.

Para uso cientifico mais rigoroso, recomenda-se fornecer declividade e curvaturas ja calculadas no mesmo CRS, resolucao, extensao e grid do MDE de trabalho. Quando o plugin precisa alinhar esses rasters derivados, a reamostragem pode suavizar extremos locais do relevo, especialmente em curvaturas. A versao atual preserva a entrada dos quatro rasters fornecidos pelo usuario; o recalcullulo automatico de derivados a partir do MDE reprojetado e uma melhoria planejada para versao futura.

Se o MDE estiver sem CRS, o modo cientifico estrito bloqueia o processamento com mensagem clara: o CRS correto deve ser definido na fonte antes da analise. Existe um modo interno nao estrito, mantido apenas para diagnostico/compatibilidade, que pode assumir `EPSG:4326`, preparar uma copia temporaria e registrar essa decisao no log. O uso cientifico recomendado e sempre manter o modo estrito e corrigir o CRS na fonte.

A adequabilidade topografica e calculada por:

```text
S = (w_alt * A + w_slope * D + w_curv_h * CH + w_curv_v * CV) / soma_dos_pesos
```

Onde `S` e a adequabilidade final, `A` e altitude normalizada, `D` e declividade normalizada invertida, `CH` e curvatura horizontal normalizada, `CV` e curvatura vertical normalizada, e `w` sao os pesos definidos pelo usuario. Pesos negativos sao rejeitados e a soma dos pesos deve ser maior que zero.

O risco topografico relativo nao e simplesmente `1 - S`. Ele combina risco de declividade com uma componente de rugosidade/curvatura, usando a declividade em relacao ao limite maximo e curvaturas normalizadas por magnitude robusta. Portanto, deve ser lido como uma camada complementar de dificuldade topografica relativa.

Para a criacao de novas trilhas, o modo mais importante e o planejamento de acesso: o raster de adequabilidade vira uma superficie de custo e o plugin procura uma rota de menor custo entre o ponto de origem e o destino. As zonas potenciais devem ser lidas como contexto espacial; a rota e o corredor sao os produtos mais diretos para orientar deslocamento de campo. Quando o objetivo for apenas chegar a um ponto, desative a geracao de zonas vetoriais para acelerar o processamento.

A rota de menor custo da versao atual e isotropica: o custo de deslocamento depende da superficie de custo e da distancia entre celulas, mas nao diferencia explicitamente subida e descida entre duas celulas adjacentes. Portanto, a rota deve ser lida como caminho preliminar de menor custo topografico, nao como modelo fisiologico completo de caminhada.

## Limitações metodológicas

- O resultado depende diretamente da qualidade, resolucao e data do DEM.
- Declividade e curvaturas mudam quando a resolucao espacial muda.
- Reamostrar declividade e curvaturas pode suavizar extremos; prefira rasters derivados ja alinhados ao MDE.
- A rota atual e isotropica e nao diferencia custo direcional de subida e descida.
- Algumas constantes de custo, risco e normalizacao sao decisoes empiricas do modelo e devem ser declaradas no artigo ou relatorio tecnico.
- Os pesos sao definidos pelo usuario e precisam de justificativa metodologica.
- Adequabilidade topografica nao substitui validacao de campo.
- O plugin nao considera automaticamente vegetacao, hidrografia, propriedade, risco legal, estradas, trilhas existentes, pastos ou restricoes ambientais.
- Camadas tematicas adicionais devem ser cruzadas posteriormente no QGIS quando o objetivo exigir uma analise territorial integrada.
- KML deve ser tratado como formato de visualizacao; GeoPackage e preferivel para analise.

## Leitura cartografica

O raster de adequabilidade deve ser usado como uma camada semi-transparente sobre a imagem de satelite ou carta base. As zonas vetoriais sao uma generalizacao do raster acima do threshold; por isso podem ficar fragmentadas quando o filtro de area minima e muito baixo. Para mapas de apresentacao, use area minima maior e prefira GeoPackage. Para planejamento de acesso em campo, priorize a rota sugerida e o corredor.

Quando o objetivo envolver montanhas altas, mantenha ativado o equilibrio por faixa altimetrica. Esse modo evita que o threshold global selecione apenas areas baixas e suaves, preservando tambem as melhores celulas relativas dentro das faixas de maior altitude.
