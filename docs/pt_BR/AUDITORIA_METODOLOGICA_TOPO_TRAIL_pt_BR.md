# TOPO_TRAIL_METHODOLOGICAL_AUDIT.md

## 1. Resumo executivo

As quatro criticas recebidas sao tecnicamente relevantes, mas nao têm o mesmo peso.

Veredito resumido:

| Critica | Veredito | Gravidade |
|---|---|---|
| Reamostragem bilinear de declividade e curvaturas | Parcialmente verdadeira | Media |
| Isotropia da rota de menor custo | Verdadeira | Media |
| Constantes matematicas fixas ou pouco explicadas | Verdadeira | Media |
| Codigo morto/incompleto em `utils.py` | Confirmado e removido | Resolvido na arvore ativa do plugin |

O plugin esta adequado para teste experimental e pode ser descrito como ferramenta preliminar de planejamento topografico, desde que as limitacoes metodologicas fiquem explicitas. Para publicacao cientifica, recomenda-se documentar claramente que os rasters derivados sao fornecidos pelo usuario, que a rota atual e isotropica, e que certas constantes sao decisoes empiricas de normalizacao/estabilizacao. Mudancas profundas, como recalcullar automaticamente declividade/curvaturas ou implementar custo anisotropico, devem entrar como versao futura, nao como alteracao silenciosa da versao atual.

## 2. Reamostragem de derivadas topograficas

### Diagnostico

A critica e parcialmente verdadeira.

A funcao `align_raster_to_reference` existe em `processing/algorithm.py:388` e usa reamostragem bilinear por padrao. O mapa de reamostragem define `"bilinear": gdal.GRA_Bilinear` em `processing/algorithm.py:397-402`.

No fluxo principal, os rasters de declividade, curvatura horizontal e curvatura vertical sao validados contra o MDE de trabalho. Quando nao sao compativeis, sao alinhados ao MDE por `align_raster_to_reference(..., resampling="bilinear")` em `processing/algorithm.py:1765-1788`.

O MDE/DEM nao passa por essa funcao no fluxo principal. Ele e preparado antes por `ensure_projected_working_crs`, que pode reprojetar o MDE para um CRS metrico de trabalho. A funcao de alinhamento com bilinear e aplicada aos rasters derivados fornecidos pelo usuario quando ha diferenca de CRS, extensao, resolucao, dimensoes ou GeoTransform.

### Arquivos e funcoes envolvidos

| Arquivo | Funcao/trecho | Papel |
|---|---|---|
| `processing/algorithm.py:388` | `align_raster_to_reference` | Alinha raster candidato ao grid do MDE |
| `processing/algorithm.py:397-402` | `resampling_map` | Define bilinear como padrao |
| `processing/algorithm.py:561` | `calculate_slope_degrees` | Calcula declividade em graus a partir do MDE |
| `processing/algorithm.py:587` | `calculate_curvature_arrays` | Calcula proxies de curvatura a partir do MDE |
| `processing/algorithm.py:1765-1788` | fluxo principal | Alinha declividade e curvaturas fornecidas pelo usuario |

### Evidencias no codigo

- O plugin exige quatro entradas raster no algoritmo: MDE, declividade, curvatura horizontal e curvatura vertical (`processing/algorithm.py:1425-1428`).
- `calculate_slope_degrees` e `calculate_curvature_arrays` existem, mas nao sao chamadas no fluxo principal de `processAlgorithm`.
- A documentacao atual informa que os rasters auxiliares devem compartilhar grid com o DEM e que sao alinhados quando necessario (`README.md:63`; `docs/METODOLOGIA_TOPOtrail.md:27`).

### Impacto metodologico

O uso de bilinear em declividade e curvaturas pode suavizar extremos, reduzir picos locais e alterar a expressao de feicoes abruptas do relevo. Esse impacto tende a ser maior em curvaturas, porque elas sao derivadas de ordem mais alta e mais sensiveis a resolucao, kernel e alinhamento. Nao e necessariamente um erro funcional, pois o plugin preserva a possibilidade de usar rasters derivados externos, mas e uma limitacao metodologica que precisa ser declarada.

### Recomendacao

Correcao mais rigorosa: reprojetar/alinhavar o MDE para o CRS/grid de trabalho e recalcular declividade e curvaturas nesse grid usando uma metodologia documentada e reprodutivel. Isso exigiria definir algoritmo de derivacao, unidade de declividade, tratamento de borda, escala/kernel, comparabilidade com as cartas atuais e possivel mudanca de interface.

Correcao minima para a versao atual: manter compatibilidade com os quatro rasters de entrada, documentar a limitacao, e registrar como TODO tecnico a opcao futura de recalcular derivados a partir do MDE preparado. Se os derivados forem fornecidos pelo usuario, recomendar que sejam gerados previamente no mesmo CRS, resolucao e grid do MDE para evitar reamostragem.

## 3. Isotropia do algoritmo de rota

### Diagnostico

A critica e verdadeira.

A funcao `least_cost_path` esta em `processing/algorithm.py:1103`. O custo de transicao e:

```python
move_cost = ((current_cost + next_cost) / 2.0) * step_length
```

Essa formula aparece em `processing/algorithm.py:1154`.

### Formula encontrada

O custo usa:

- custo da celula atual;
- custo da proxima celula;
- comprimento do passo, com vizinhos ortogonais `1.0` e diagonais `sqrt(2.0)`.

Nao usa diferenca de altitude entre celulas no calculo da transicao. A funcao `save_access_route` recebe `elevation_array`, mas usa a altitude apenas para atributos finais da rota, como altitude inicial/final e ganho aproximado, nao para definir o custo de movimento.

### Isotropico ou anisotropico?

O algoritmo atual e isotropico. Se duas celulas tiverem os mesmos custos de superficie, subir ou descer entre elas gera o mesmo custo de transicao. A direcao espacial so entra pelo comprimento do passo; o gradiente altimetrico direcional nao entra.

### Impacto na interpretacao de rotas

Isso nao invalida o plugin, mas define uma limitacao. A rota representa menor custo sobre uma superficie de adequabilidade topografica, nao um modelo fisiologico completo de deslocamento humano. Como a declividade ja entra no raster de custo, encostas inclinadas sao penalizadas, mas a penalizacao nao distingue subida de descida em uma mesma encosta.

### Recomendacao para versao atual

Documentar explicitamente a isotropia e manter o comportamento atual para estabilidade. Uma mudanca direta para custo anisotropico alteraria resultados, validacoes anteriores, parametros e interpretacao cientifica.

### Recomendacao para versao futura

Criar modo opcional de rota anisotropica, mantendo o modo isotropico como padrao ou como modo legado. Esse modo poderia considerar `delta_z / distancia_horizontal` entre celulas e aplicar uma funcao direcional inspirada em Tobler's Hiking Function ou em uma penalizacao propria calibrada para trilhas de campo.

Impactos esperados:

- Novo parametro de modo de rota: isotropico/anisotropico.
- Possivel parametro de penalizacao de subida e descida.
- Necessidade de explicar se descidas muito ingremes tambem sao penalizadas.
- Mudanca nas rotas geradas e na comparabilidade com resultados anteriores.
- Necessidade de testes especificos com origem/destino invertidos.

## 4. Constantes matematicas

| Arquivo | Funcao | Constante | Uso | Impacto metodologico | Esta documentada? | Recomendacao |
|---|---|---:|---|---|---|---|
| `processing/algorithm.py:1229` | `save_access_route` | `0.05` | Epsilon em `1/(adequabilidade + 0.05)` | Medio: limita custo maximo e evita divisao por zero | Parcial, aparece na string de log/docstring, sem justificativa | Transformar em constante nomeada e documentar como estabilizador empirico |
| `processing/algorithm.py:862` | `compute_topographic_risk` | `1.35` | Expoente da curva de risco de declividade | Medio: altera resposta da declividade no risco | Nao suficientemente | Transformar em constante nomeada, comentar e explicar no artigo |
| `processing/algorithm.py:870` | `compute_topographic_risk` | `0.75/0.25` | Pesos declividade/curvatura no risco | Medio: define importancia relativa do risco | Parcial, README descreve qualitativamente | Transformar em constantes nomeadas; explicar como decisao empirica |
| `processing/algorithm.py:846` | `robust_abs_norm` | `95.0` | Percentil robusto para normalizar curvaturas | Medio: controla sensibilidade a extremos | Nao suficientemente | Constante nomeada ou parametro futuro |
| `processing/algorithm.py:531` | `normalize_curvature_preference` | `floor=0.2` | Piso de score para curvatura | Medio: evita zerar completamente curvaturas extremas | Nao suficientemente | Constante nomeada/documentar |
| `processing/algorithm.py:540` | `normalize_curvature_preference` | `99` | Percentil para limite de desvio de curvatura | Medio: controla extremos | Nao suficientemente | Constante nomeada/documentar |
| `processing/algorithm.py:1224` | `save_access_route` | `8000000` | Limite de celulas no recorte de rota | Baixo/medio: seguranca computacional, evita travamento | Mensagem de erro explica parcialmente | Constante tecnica nomeada |
| `processing/algorithm.py:1079` | `nearest_valid_cell` | `30` | Raio de busca por celula valida | Baixo/medio: pode deslocar ponto para celula proxima | Nao | Constante tecnica nomeada ou documentar |
| `processing/algorithm.py:652` | `binarize_by_altitude_bands` | `50.0` | Tamanho minimo de faixa altimetrica | Medio: afeta threshold por faixa | Exposto parcialmente como parametro minimo | Justificavel, manter como limite minimo documentado |
| `processing/algorithm.py:1435-1566` | parametros QGIS | `2600`, `55`, `50`, `75`, `50`, `200`, `100`, `5000` | Defaults de interface/processamento | Medio: alteram outputs, mas sao configuraveis | Parcialmente | Manter configuraveis; justificar no artigo como parametros de teste, nao universais |
| `processing/route_scenarios.py:23-77` | `DEFAULT_SCENARIOS` | varios pesos/limiares | Cenarios experimentais de rota | Medio/alto nos cenarios | Parcial via descricoes | Manter em modulo experimental, documentar como presets |
| `processing/route_scenarios.py:83-88` | `DEFAULT_RISK_THRESHOLDS` | `15`, `25`, `35`, `45`, `98` | Classes de risco auxiliares | Medio | Parcial | Explicar como classificacao relativa, nao perigo absoluto |

### Quais constantes sao justificaveis?

Constantes de conversao, como `10000` para ha/m2, `sqrt(2)` para movimento diagonal, EPSG e valores de NoData, sao tecnicas e justificaveis. Limites computacionais, como tamanho maximo do recorte de rota, tambem sao justificaveis, desde que nomeados.

### Quais precisam virar parametro?

Para a versao atual, nenhuma precisa obrigatoriamente virar parametro de interface. Expor tudo agora aumentaria complexidade e risco de uso incorreto. Para versao futura, o epsilon da rota, pesos do risco e expoente de declividade podem virar parametros avancados ou presets metodologicos.

### Quais podem ficar no codigo com comentario/documentacao?

`0.05`, `1.35`, `0.75/0.25`, percentis robustos e piso de curvatura podem ficar se virarem constantes nomeadas e forem explicados como decisoes empiricas de modelagem preliminar.

### Quais devem ser explicadas no artigo?

Devem ser explicados no artigo: epsilon da rota, pesos do risco, expoente de risco de declividade, percentis de normalizacao de curvatura, parametros default de declividade, area minima e threshold.

## 5. Codigo morto ou experimental

Atualizacao: o modulo legado `processing/utils.py` foi removido da arvore ativa do plugin apos confirmacao de que nao era importado pelo fluxo de producao. A tabela abaixo fica como registro historico da auditoria que motivou a remocao.

| Funcao | Arquivo | Implementada? | E chamada? | Pode remover? | Risco de remocao | Recomendacao |
|---|---|---|---|---|---|---|
| `reproject_raster` | `processing/utils.py` | Simples/antiga | Nao encontrada em fluxo atual | Provavelmente sim | Baixo, mas e API publica do modulo | Manter por ora ou mover para modulo legado |
| `calculate_centerline` | `processing/utils.py` | Parcial | Nao chamada fora de `utils.py` | Sim, se nao houver uso externo | Baixo/medio | Remover antes da versao 1.0.0 ou marcar como experimental |
| `find_saddle_points` | `processing/utils.py` | Nao, retorna `[]` | So chamada por `calculate_centerline` | Sim | Baixo | Remover/isolar; nao deve estar em versao cientifica final |
| `generate_drainage_lines` | `processing/utils.py` | Nao, retorna `[]` | So chamada por `calculate_centerline` | Sim | Baixo | Remover/isolar; nao deve estar em versao cientifica final |
| `simplify_lines` | `processing/utils.py` | Nao, retorna `[]` | So chamada por `calculate_centerline` | Sim | Baixo | Remover/isolar; nao deve estar em versao cientifica final |
| `sanitize_geometries` | `processing/utils.py` | Sim | Chamada por `export_to_format` | Sim, se remover `export_to_format` | Medio | Manter se `export_to_format` ficar |
| `export_to_format` | `processing/utils.py` | Sim, mas legado | Nao chamada no fluxo atual | Provavelmente sim | Medio se usado externamente | Manter por ora, revisar em limpeza pre-1.0 |
| `generate_statistics_report` | `processing/utils.py` | Nao, TODO e retorna caminho | Nao chamada | Sim | Baixo | Remover/isolar antes da versao 1.0.0 |

Existe codigo morto/incompleto. Ele nao afeta o funcionamento atual do plugin, porque `algorithm.py`, `route_scenarios.py`, `topotrail.py` e `topotrail_dialog.py` nao chamam essas funcoes. Para avaliacao cientifica ou repositorio oficial, entretanto, funcoes publicas com TODO e `return []` podem gerar desconfiança.

## 6. Correcoes recomendadas

### Correcoes urgentes antes de publicacao

- Transformar constantes metodologicas principais em constantes nomeadas sem alterar valores.
- Documentar no README/metodologia que derivados fornecidos pelo usuario podem ser alinhados por bilinear e que o uso rigoroso recomenda derivados ja gerados no grid final.
- Documentar que a rota e isotropica.
- Manter a arvore ativa do plugin livre de modulos legados com stubs TODO. O modulo anterior `processing/utils.py` foi removido apos confirmacao de que nao era importado pelo fluxo de producao.
- Gerar pacote limpo sem `test_runs`, `backups`, `github_publish`, `_restore...` e `__pycache__`.

### Melhorias recomendadas para artigo cientifico

- Explicar que o TopoTrail modela viabilidade topografica preliminar, nao caminhabilidade total.
- Declarar explicitamente dependência da resolucao e qualidade do DEM.
- Justificar os thresholds e defaults usados no estudo de caso.
- Diferenciar zonas caminhaveis, adequabilidade e rota de menor custo.
- Explicar que custo de rota atual e isotropico e baseado em superficie de custo.

### Melhorias futuras para versao 1.0.0 ou posterior

- Modo opcional de recalculo de declividade/curvaturas a partir do MDE preparado.
- Modo opcional de rota anisotropica com custo direcional.
- Parametros avancados ou presets metodologicos para epsilon, pesos de risco e expoente de declividade.
- Manter codigo helper experimental em branch separada de desenvolvimento ate que esteja completo e testado.
- Testes automatizados de inversao origem/destino para diferenciar rota isotropica e futura rota anisotropica.

## 7. Texto sugerido para limitacoes metodologicas

### Portugues

O TopoTrail deve ser interpretado como uma ferramenta preliminar de avaliacao topografica para planejamento de trilhas e acessos. A versao atual utiliza MDE, declividade e curvaturas fornecidos pelo usuario; quando esses rasters nao compartilham exatamente a mesma grade, CRS, resolucao e extensao, o plugin pode alinha-los ao grid de trabalho, o que pode introduzir suavizacao em derivados topograficos. A rota de menor custo e calculada sobre uma superficie de custo isotropica derivada da adequabilidade, portanto nao diferencia explicitamente o custo direcional de subida e descida entre celulas. Algumas constantes de normalizacao, estabilizacao numerica e ponderacao de risco sao empiricas e devem ser interpretadas como parametros metodologicos do modelo, nao como limiares universais de caminhabilidade ou perigo.

### English

TopoTrail should be interpreted as a preliminary topographic assessment tool for trail and access planning. The current version uses user-supplied DEM, slope and curvature rasters; when these rasters do not share the same grid, CRS, resolution and extent, the plugin may align them to the working grid, which can introduce smoothing in topographic derivatives. The least-cost route is computed over an isotropic cost surface derived from suitability, and therefore does not explicitly distinguish directional uphill and downhill movement costs between cells. Some normalization, numerical-stabilization and risk-weighting constants are empirical modelling choices and should be interpreted as methodological parameters, not universal thresholds of walkability or hazard.

## 8. Veredito final

Estado metodologico atual: adequado para publicacao como ferramenta preliminar com limitacoes explicitas.

Justificativa: o fluxo principal e coerente para analise multicriterio topografica, valida/alinha rasters, gera adequabilidade, risco, zonas, rota e corredor, e possui logs suficientes para rastreabilidade. As criticas nao indicam bug fatal, mas apontam limitacoes reais que precisam estar claras no artigo, README e documentacao metodologica. O modulo legado com stubs incompletos identificado anteriormente foi removido da arvore ativa do plugin. Para uma versao estavel ou uma afirmacao cientifica mais forte sobre custo de deslocamento humano, ainda seriam necessarios recalcullos de derivados no grid final e custo anisotropico opcional.
