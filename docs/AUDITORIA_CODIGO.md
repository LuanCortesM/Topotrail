# TopoTrail — auditoria de código antes da publicação

**Pergunta:** o plugin está perfeito e funcional em nível de publicação — a matemática, as regras geográficas e o funcionamento nos seis idiomas?

**Resposta curta:** a versão 0.13.1 **não** estava. Três auditorias independentes e adversariais (matemática, geografia, idiomas), cada uma obrigada a reproduzir numericamente o que afirmava, encontraram 26 defeitos, 8 deles sérios. A versão **0.14.0** corrige todos os confirmados, com 19 testes de regressão novos, e foi re-verificada nos mesmos cenários que os expuseram. O que segue é o registro: o que foi checado e está certo, o que estava errado e como foi corrigido, e o que ficou apenas documentado.

**Versão auditada:** 0.13.1 · **Versão corrigida:** 0.14.0 · Auditoria de 2026-09-05.

---

## 1. Matemática

### Verificado como correto (reproduzido contra a forma analítica)

| Componente | Teste | Resultado |
|---|---|---|
| Declividade (`terrain.py`) | plano 0,3x + 0,4y; pixel 10×30 m; 45° | 50,00 % em todo o interior e bordas; 45° → 100 % exato |
| Curvaturas | plano inclinado, cilindro, taça z = a(x²+y²), calota esférica R = 500 | plano → 0/0; cilindro → plana 0, perfil negativa; taça: plana = 1/r, perfil = −1/R na calota |
| VRM (Sappington 2007) | planos de qualquer inclinação; pares de gradientes arbitrários | 0 em todo plano; ângulo entre normais igual ao verdadeiro; recortado em [0, 1] |
| Tobler | S ∈ {0, ±0,1, −0,05, ±0,5, 0,707}; 200 m a ±10 % | 6·exp(−3,5·\|S+0,05\|) exato; 0,05635 h subida / 0,03971 h descida, analítico |
| A* anisotrópico | 30 grades aleatórias 25×25 vs Dijkstra | custo idêntico a 0,0 (heurística admissível) |
| Held-Karp (ordem dos destinos) | 20 matrizes assimétricas, 2–6 intermediários, vs força bruta | idêntico em todos os casos |
| Priority-Flood | fosso, rampa monótona, borda de nodata | fosso elevado ao nível de vertimento + ε; rampa intocada; nodata é exutório |
| D8 / acumulação | vale em V drenando para leste | diagonal onde o desnível manda; acumulação no exutório = 180 = todas as células |
| TWI | rampa de 10 % | ln(a/tanβ) = 7,86327 vs 7,86327 analítico |
| Combinação de critérios | Σwᵢnᵢ/Σwᵢ; pesos e limiares validados | reproduzido exatamente |
| Risco topográfico | 0,75·clip(s/máx)^1,35 + 0,25·(\|κh\|/P95 + \|κv\|/P95)/2 | reproduzido exatamente; NaN preservado fora da máscara |
| Área do pixel / filtro de fragmento | 10 m → 100 m²; 1″ a −22,5° → 877 m² (esperado 880); 0,05 ha remove fragmentos de 4 e 2 células | correto, conectividade 8 como documentado |
| Transitabilidade | intervalos semiabertos, monótona na declividade, NaN → 0, bloqueada → 5 | correto |

### Defeitos encontrados e corrigidos

**M1 — Borda de nodata inventava declividade (sério).** Células vizinhas ao nodata eram derivadas contra a *média da cena*. Medido: rampa de 30 % a 2000 m → 247 % na primeira coluna válida; buraco interior → vizinhos a 195–255 %; cena realista reprojetada (borda inclinada) → **101 células de classe 5 "escarpada"** num relevo sem nada acima de 40 %, todas no anel; o TWI ficava NaN no mesmo anel e o modelo o lia como "o mais úmido". Como todo MDE geográfico é reprojetado, todo produto tinha esse anel.
*Correção:* derivada que respeita o nodata (`_masked_gradient`: central onde há dois vizinhos válidos, unilateral onde há um), aplicada a declividade, curvaturas, VRM e TWI. *Re-verificado:* anel de 2.384 células do MDE 4326 → **0 de classe 5**; rampa com faixa de nodata → 30,0 % até a borda.

**M2 — Critério sem cobertura penalizava a célula, e o aviso dizia o contrário (sério).** `nan_to_num` contava a lacuna como nota zero — a pior — enquanto o aviso dizia "favorece artificialmente". *Correção:* a célula descoberta é pontuada só pelos critérios que tem, com a soma dos pesos renormalizada por célula; aviso reescrito. *Re-verificado:* raster extra cobrindo metade da área → metade descoberta com diferença **0,00** em relação à corrida sem o critério.

**M3 — Curvaturas citadas errado (menor, mas é citação).** As fórmulas são as curvaturas geométricas de contorno/perfil de Moore, Grayson & Ladson (1991) / Mitasova & Hofierka (1993), não as quadráticas de Zevenbergen & Thorne (1987) — na taça, Z&T daria plana constante 0,002 e o código dá 1/r = 0,0100. As fórmulas estão certas para o que são; a docstring e o log estavam errados. *Correção:* citação corrigida nos dois lugares.

**M4 — Buffer dos cursos d'água era quadrado (nota).** Dilatação 3×3 repetida = distância de Chebyshev: 50 m viravam 71 m na diagonal. *Correção:* distância euclidiana (`distance_transform_edt`) em metros.

**M5 — Raster degenerado dava erro cru do NumPy (menor).** 1×N, N×1, 1×1. *Correção:* mensagem própria "precisa ter pelo menos 2 × 2 células".

**M6 — Modificadores da transitabilidade se acumulam (nota).** Célula rugosa *e* úmida cai duas classes; a docstring dizia "uma". Comportamento defensável; *documentado* em vez de alterado.

**Notas de modelagem, para o artigo, sem alteração:** faixas de altitude com menos de 50 células válidas nunca são selecionadas; umidade e rugosidade usam escala de razão (1 − x/P95), o que reduz o peso efetivo relativo à declividade; hidrologia acima de 1,2 M células decima em vez de agregar; o ε do Priority-Flood cria uma rampa de N mm num lago de N células (irrelevante para D8; TWI tem piso de tanβ).

## 2. Regras geográficas

### Verificado como correto

UTM automática certa nos dois hemisférios, dos dois lados de Greenwich, no limite de zona e no equador; comprimento de rota vs geodésico dentro de 0,1–0,4 % em todos os casos. CRS projetado sem autoridade (WKT local) funciona de ponta a ponta. MDE em pés com unidade vertical "pés" dá resultado idêntico ao MDE em metros (|Δ| = 2×10⁻⁴). Pontos em CRS diferente do raster são transformados. Toda `SpatialReference` que participa de transformação usa ordem de eixo tradicional. CRS de saída EPSG:4326/32722/31983/3857 → geometria e CRS declarado corretos à precisão de máquina. Rasters próprios de declividade em graus ou % dão notas idênticas (1,8×10⁻⁷); raster desalinhado (60 m, 4326, deslocado) é reamostrado na grade do MDE (r = 0,986 vs 0,860 se estivesse deslocado 2 células). Nodata Int16, Float64, Float32 NaN e o anel de −9999 pós-reprojeção são todos excluídos; rasters de saída com nodata, tabela de cores e nomes de categoria.

### Defeitos encontrados e corrigidos

**G1 — CRS projetado em pés tratado como metros (sério).** EPSG:2229 (State Plane, pé americano): declividade ÷3,28, rota "35.200 m" para 10.730 m reais, corredor de "50 m" com 15 m, área ×10,8; sem aviso. *Correção:* `projected_crs_is_metric` lê a unidade linear; unidade ≠ metro → reprojeta para a UTM automática com aviso. *Re-verificado:* mesma cena em 2229 → CRS de trabalho EPSG:32611, pixel 30,47 m, declividade p50 17,41 % (controle em metros 17,57 %), rota 10.815,7 m (geodésica 10.819,5), corredor 1,088×10⁶ m² (controle 1,093×10⁶).

**G2 — Web Mercator aceito como métrico (sério).** Escala cresce com 1/cos φ: 8 % de erro a 22°, 100 % a 60°. *Correção:* família Mercator (não transversa) é reprojetada para UTM, com aviso.

**G3 — Pixel retangular e grade rotacionada entravam no roteamento com passo errado (sério, silencioso).** 10×30 m → rota 19 % mais longa, tempo de Tobler 4,11 h vs 3,42 h; grade a 30° → pixel lido como 25,98 m, declividade +15 %. *Correção:* reamostragem para grade quadrada norte-acima (menor lado) com aviso; tamanho de pixel lido como hipotenusa dos termos do geotransform. *Re-verificado:* 10×30 → 10 m, rota 10.829 m (geodésica 10.846); rotacionada → 30 m, declividade 17,47 % (ref. 17,81 %).

**G4 — Camada de restrição reaberta pelo caminho quebrava fora do arquivo puro (sério para quem usa a caixa de ferramentas).** GeoPackage aberto pelo navegador (`|layername=`), camada de memória. *Correção:* geometrias lidas pelo próprio QGIS (WKB) quando vem uma `QgsVectorLayer`. *Re-verificado:* `|layername=` → 1.007 células (esperado 1.007); camada de memória → 1.007.

**G5 — CRS de saída personalizado quebrava ou era ignorado (sério).** `USER:100000` → "Corrupt data" depois de todos os rasters gravados; CRS sem autoridade → saída ficava no CRS de trabalho sem aviso. *Correção:* alvo por WKT, nunca por authid. *Re-verificado:* USER:100001 e WKT sem autoridade → vetores reprojetados, mensagem com o rótulo certo.

**G6 — `world_to_pixel` usava `round` (menor).** Ponto a 0,6 da célula ia para a vizinha; o mesmo ponto em dois CRS caía em células diferentes (263 vs 264 vértices). *Correção:* `floor`. *Re-verificado:* colunas contínuas 20,0–20,99 → célula 20; 21,5 → 21.

**G7 — Ponto fora do MDE dizia "sem célula válida próxima" (menor).** *Correção:* mensagem diz que o ponto está fora, dá a extensão e lembra que coordenadas digitadas são lidas no CRS do projeto; tooltip nos campos X, Y diz o mesmo nos seis idiomas.

**G8 — Camada de pontos sem CRS assumida em silêncio (menor).** *Correção:* aviso no log de mensagens do QGIS dizendo o CRS assumido.

**G9 — KML "reprojetado" para um CRS que o formato não aceita (nota).** *Correção:* mensagem explica que KML é sempre WGS84.

**G10 — MDE dentro de GeoPackage rejeitado (`os.path.exists`) (menor).** *Correção:* sondagem com `gdal.Open`; nome de camada `gpkg_*` (reservado) recebe prefixo. *Re-verificado:* `GPKG:/…:dem` roda.

**G11 — Zona UTM para longitude 0–360 e latitude > 84° (nota).** *Correção:* longitude normalizada; aviso acima de 84°.

## 3. Os seis idiomas

### Verificado como correto

Paridade total: 226 (agora 234) chaves em todos os arquivos, sem vazios, todos os `{placeholders}` presentes, listas de mesmo tamanho, nenhum vazamento de português. Nome, grupo, todos os parâmetros, opções de enum e descrições de saída do Processing mudam com `TopoTrail/language` nos seis códigos; código inválido ou vazio cai na detecção; a escolha explícita sobrepõe o locale do QGIS. Legendas de classe gravadas no GeoTIFF de transitabilidade no idioma ativo (`.aux.xml`, verificado com `gdalinfo`); a corrida completa em todos os idiomas com mensagens não-ASCII. Ordem dos enums da janela igual à do algoritmo nos seis combos. Todas as mensagens de `_validate` traduzidas e formatadas. Detecção: `pt_BR/es_ES/zh_CN/zh_TW/ja_JP/fr_CA/pt-BR` → idioma certo; `de_DE/en_US/vazio` → inglês. Layout a 940×720 e 1040×780, quatro passos, seis idiomas: nenhum rótulo cortado, nenhuma sobreposição; harness Qt6 = 0 problemas. **Qualidade das traduções (es, fr, zh, ja): fluentes, terminologia consistente, sem artefato de máquina — publicáveis como rascunho**, com as correções abaixo aplicadas.

### Defeitos encontrados e corrigidos

**I1 — Ajuda do algoritmo no Processing em português nos seis idiomas (sério).** `shortHelpString` passava uma frase inteira como *chave*. *Correção:* chave `alg_help`. **I2 — Resumo do passo 4 misturava idiomas** ("経路とアクセス回廊 (with intermediate destinations)"). *Correção:* `summary_via`. **I3 — Mensagens de marcar no mapa só pt/en.** *Correção:* `err_no_canvas`, `pick_prompt`. **I4 — Títulos e filtros de diálogo de arquivo em português.** *Correção:* chaves existentes reaproveitadas + `filter_vectors`, `filter_all`. **I5 — Nomes das camadas carregadas no projeto em português.** *Correção:* `alg_o_*`. **I6 — Combo "Mauvaises (plus bas est mieux)" cortado após trocar idioma.** *Correção:* `AdjustToContents` em todos os combos; harness Qt6 passa a varrer combos. **I7 — Trocar idioma resetava o modelo de custo para Tobler.** *Correção:* padrão fixado uma só vez. **I8 — `LANG=zh.UTF-8` caía em inglês.** *Correção:* separador `[_.@-]`. **I9 — "中文" sem dizer que é simplificado.** *Correção:* "中文（简体）". **I10 — `longName` do provedor em português.** *Correção:* inglês. **I11 — README dizia "PT-BR | ENG".** *Correção:* seis idiomas, e declara que o log é só em português. **I12 — Traduções:** es "No pude abrir" → "No se pudo abrir"; fr "Escarpement" → "Escarpée", "Courbure planaire" → "en plan", direções reescritas; zh/ja "起伏度" (amplitude de relevo) → "地形粗糙度（VRM）" / "地形の粗さ（VRM）", zonas com o mesmo nome no diálogo e no algoritmo, travessão chinês fora do japonês; en "Escarpment" → "Very steep", "Slope scoring zero" → "Slope at which the score reaches zero".

**Ficou documentado, não traduzido:** as ~75 mensagens de exceção e as 78 linhas de log do algoritmo estão em português. O README agora diz isso. Traduzir as exceções é trabalho conhecido para uma versão futura, não bloqueador.

## 4. Veredito

Depois da 0.14.0: **a matemática é correta e agora também nas bordas; as regras geográficas cobrem os casos que um usuário fora do Brasil vai trazer (pés, Mercator, grades irregulares, CRS personalizado, GeoPackage); os seis idiomas são funcionais na janela, no Processing e nos produtos.** A suíte tem 230 testes, todos verdes, mais o harness Qt6 nos seis idiomas e a corrida integrada em QGIS headless sem geopandas.

O que separa isto de "publicado" continua sendo administrativo, não técnico: `paper.md`, ORCID, assinatura dos commits, release e DOI no Zenodo, e um teste de fumaça em QGIS 4 instalado.
