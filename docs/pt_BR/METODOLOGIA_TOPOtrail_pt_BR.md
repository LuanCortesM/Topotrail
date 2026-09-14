# Metodologia do TopoTrail

Fórmulas, constantes empíricas nomeadas e regras de normalização, como estão
implementadas na versão **1.3.0**. Toda afirmação deste documento foi conferida
contra `processing/` neste repositório; onde uma constante é nomeada, o nome é o
do código, para que possa ser encontrada e lida em contexto.

A revisão crítica dessas escolhas de modelagem — o que elas supõem e onde são
reconhecidamente frágeis — é outro documento,
[`AUDITORIA_METODOLOGICA_pt_BR.md`](AUDITORIA_METODOLOGICA_pt_BR.md). Note que
ele auditou a **versão 0.5.0** e é mantido como registro datado, e não como
descrição do modelo atual; a seção final dele diz quais das suas recomendações
foram implementadas e em que versão. A calibração empírica das constantes contra
trajetos de GPS de campo está em [`VALIDACAO.md`](../VALIDACAO.md), que
igualmente traz a versão do plugin por trás de cada número.

## Para que o modelo serve, e para que não serve

O TopoTrail modela adequabilidade **topográfica** para deslocamento a pé e para
planejamento preliminar de trilhas e acessos. A unidade de análise é o relevo,
representado por um Modelo Digital de Elevação. O MDE é o único dado
obrigatório; todos os demais atributos do terreno são derivados dele.

O plugin não modela caminhabilidade territorial completa. Ele não reconhece
estradas, trilhas existentes, pastos, uso do solo, propriedade ou restrições
legais, e a hidrografia que ele conhece é a que extrai do próprio MDE. Esses
temas são complementares e devem ser sobrepostos a estas saídas no QGIS. Um
pasto visualmente caminhável pode, portanto, receber nota baixa se,
topograficamente, a declividade, a curvatura ou o comportamento de limiar
naquela célula forem desfavoráveis. Isso é uma diferença entre adequabilidade
topográfica e caminhabilidade observada, e não automaticamente um defeito.

## Os sete produtos

| Produto | O que é |
|---|---|
| Adequabilidade topográfica | Raster contínuo de 0 a 1, a combinação ponderada descrita adiante. |
| Risco topográfico relativo | Raster contínuo de 0 a 1, indicador próprio — **não** é `1 − S`. |
| Classes de transitabilidade | Cinco classes absolutas de declividade, com legenda escrita. |
| Zonas de acesso potencial | Polígonos acima de um limiar de adequabilidade, com área. |
| Rota sugerida | Linha de menor custo entre a origem e um ou mais destinos. |
| Corredor de acesso | Buffer métrico em torno da rota. |
| Travessias de cursos d'água | Um ponto por travessia que a rota faz, graduada e com aviso. |

Mais um **registro de diagnóstico em JSON**, um registro por etapa, descrito ao
final.

## Sistema de referência de trabalho e preparo do MDE

Declividade, curvatura, área, distância e custo de deslocamento só têm sentido em
unidades métricas, o que impõe uma condição sobre o sistema de referência em que
o cálculo ocorre. O plugin verifica essa condição e a corrige:

* MDE em coordenadas geográficas é reprojetado para a zona UTM correspondente ao
  centro geométrico da cena, com o hemisfério escolhido pelo sinal da latitude.
  Acima de 84° de latitude, fora do domínio da UTM, a execução prossegue com
  aviso de que a distorção pode ser grande e de que um sistema polar é
  preferível;
* MDE em sistema projetado mas não métrico — pés, ou uma projeção de Mercator
  cuja escala varia com a latitude — é igualmente reprojetado, com aviso
  explícito;
* grades rotacionadas, ou com células não quadradas, são reamostradas para uma
  grade quadrada orientada ao norte, porque o cálculo de gradiente por
  diferenças finitas pressupõe isso;
* com `STRICT_CRS_MODE` ligado, que é o padrão publicado, um MDE **sem** sistema
  de referência interrompe a execução: o CRS precisa ser corrigido na origem do
  dado.

Rasters próprios de declividade e curvatura são validados contra o MDE e
alinhados à sua grade, resolução, extensão e CRS quando necessário. Alinhar
reamostra, e reamostrar suaviza extremos locais, sobretudo de curvatura — então,
para uso científico estrito, gere-os previamente na grade de trabalho, ou deixe o
plugin derivá-los, que é o padrão e garante a grade por construção.

## NoData

Célula sem dado vira NaN e propaga-se como NaN por toda a cadeia, em vez de
entrar na aritmética como se fosse altitude válida. O gradiente na borda de uma
região sem dado é calculado apenas com os vizinhos existentes — de um lado só
quando é o caso. Sem esse cuidado, a diferença entre uma altitude real e um valor
de preenchimento produz declividades espúrias de centenas por cento exatamente
nos limites da cena, que é onde a rota costuma entrar e sair.

## Atributos derivados do terreno

### Declividade

A declividade é expressa **em porcentagem** — cem vezes a tangente do ângulo de
maior declive, de modo que 100% corresponde a 45° —, e não em graus:

```text
D = 100 * raiz( (dz/dx)^2 + (dz/dy)^2 )
```

Porcentagem é a unidade interna do plugin em todo o cálculo. Um raster de
declividade fornecido pelo usuário é declarado em porcentagem ou em graus pelo
parâmetro `SLOPE_UNIT` e convertido; a unidade não pode ser inferida, porque
abaixo de 45 as duas ocupam a mesma faixa numérica.

### Curvaturas

As duas curvaturas são as curvaturas normais **tangencial** (`Ch`, chamada de
horizontal na interface) e **de perfil** (`Cv`, vertical), em m⁻¹, nas formas de
Mitášová & Hofierka (1993), com `p = (dz/dx)^2 + (dz/dy)^2`:

```text
Ch = (zxx*zy^2 - 2*zxy*zx*zy + zyy*zx^2) / ( p * (1 + p)^(1/2) )
Cv = (zxx*zx^2 + 2*zxy*zx*zy + zyy*zy^2) / ( p * (1 + p)^(3/2) )
```

Duas decisões de implementação afetam esses números e precisam ser declaradas.

**Tangencial, e não curvatura de contorno.** Até a versão 1.2.0 a curvatura
horizontal era a curvatura geométrica de contorno de Moore, Grayson & Ladson
(1991), que tem `p^(3/2)` no denominador e por isso diverge quando o gradiente
tende a zero: num ponto plano a curva de nível se fecha cada vez mais apertada, e
uma célula perfeitamente suave recebe valor extremo embora a superfície ali não
tenha nada de abrupto. Como o modelo pontua a forma pela distância a zero, o
efeito era perverso — o terreno mais suave, que é o que o modelo quer premiar,
recebia a pior nota de forma. Medida na cena da Mantiqueira da dissertação, a
correlação entre o logaritmo da declividade e a nota de forma era de +0,58; com a
curvatura tangencial ela cai para +0,06. Corrigido na 1.3.0.

**Um único operador para as três segundas derivadas.** O operador de diferença
central é aplicado duas vezes, de modo que `zxx`, `zyy` e `zxy` saem todos do
mesmo operador. O custo é atenuação — as derivadas ficam avaliadas num passo de
duas células, preservando 40,5% da amplitude em formas de quatro células e 81,1%
em formas de oito, o que é atenuação real na escala dos esporões e colos que
decidem por onde uma trilha passa. O benefício é que o Hessiano discreto
permanece próximo do posto um sobre superfícies de curvas de nível retas, de modo
que a curvatura tangencial de uma encosta lisa continua pequena em qualquer
orientação. Substituir apenas as derivadas puras por um estêncil de três pontos
melhora a resolução de formas curtas e piora essa segunda propriedade em mais de
vinte vezes. A escolha foi medir as duas alternativas e ficar com a atenuação
declarada, em vez de trocá-la por um artefato dependente de orientação.

Convenção de sinal, verificada contra superfícies de forma conhecida em
`tests/test_terrain_math.py`: formas **convexas** — domos, cristas, esporões —
recebem valores negativos; formas **côncavas** — bacias, cabeceiras, calhas —
valores positivos; a curvatura tangencial é exatamente nula numa crista
cilíndrica, cujas curvas de nível são retas. Onde o gradiente é nulo a curvatura
é indefinida e o modelo atribui zero, que é a nota máxima do critério — escolha
que favorece terreno plano e que convém lembrar em relevo baixo.

### Rugosidade

A rugosidade é a **Vector Ruggedness Measure** de Sappington, Longshore &
Thompson (2007), `vector_ruggedness()`: cada célula vira o vetor unitário normal
à superfície, os vetores da vizinhança 3×3 são somados, e o índice é um menos o
módulo da resultante dividido pelo número de normais. É **adimensional, em
[0, 1]**, e vale zero num plano por mais íngreme que ele seja. Esse
desacoplamento da declividade é justamente o ponto: é o que separa uma encosta
lisa de campo de um campo de blocos na mesma inclinação média.

O `roughness_index()` — o Terrain Ruggedness Index de Riley, DeGloria & Elliot
(1999), a diferença absoluta média de altitude para os oito vizinhos, em metros —
também está implementado e **não** é o que o modelo usa. O TRI não é independente
da declividade: numa rampa perfeitamente lisa de 80% ele vale 6,00 m, contra
3,36 m numa superfície ruidosa de declividade média 27%. Fica disponível por ser
o padrão citável e por ser útil como medida de amplitude local em metros.

### Hidrologia

As depressões são preenchidas pelo **priority-flood com épsilon**, que impõe uma
superfície estritamente descendente e é exato (Barnes, Lehman & Mulla 2014). O
fluxo segue a regra **D8** (O'Callaghan & Mark 1984): cada célula drena para o
vizinho de maior declive, com o passo diagonal pesado por √2 para não ser tratado
como ortogonal. A acumulação é propagada em ordem decrescente de altitude e dá a
área de contribuição de cada célula; as células acima do limiar de área de bacia
(`STREAM_MIN_BASIN_KM2`, padrão 1 km²) formam a rede de canais. O limiar é uma
escolha metodológica de verdade e deve ser reportado; a densidade de drenagem é a
verificação útil sobre ele, e cai à medida que a célula de trabalho cresce, então
o plugin reporta as duas juntas.

O **índice topográfico de umidade** é `ln(a / tan β)` (Beven & Kirkby 1979),
calculado a partir da mesma acumulação, e por isso custa quase nada uma vez
extraída a drenagem.

## Adequabilidade: a combinação multicritério

Cada critério é convertido numa nota entre 0 e 1 antes de ser combinado.

| Critério | Como é pontuado | Peso padrão |
|---|---|---|
| Declividade `D` | Linear entre 0 e `SLOPE_SCORE_MAX`, e então **invertida**: plano vale 1, no limite vale 0. | 1,0 |
| Altitude `A` | Linear entre `ALT_MIN` e `ALT_MAX`. | **0,0** |
| Curvatura tangencial `CH` | Proximidade de zero, ver abaixo. | 1,0 |
| Curvatura de perfil `CV` | Proximidade de zero, ver abaixo. | 1,0 |
| Umidade `W` | Normalização robusta do TWI, invertida — mais seco é melhor. | **0,0** |
| Rugosidade `R` | Normalização robusta do VRM, invertida — mais liso é melhor. | **0,0** |
| Raster adicional | Normalizado, com sentido declarado (valor alto é bom, ou ruim). | **0,0** |

Pontuação das curvaturas: a nota é
`piso + (1 - piso) * (1 - min(|C - 0| / L, 1))`, com o piso em
`CURVATURE_SCORE_FLOOR = 0,2` e o desvio tolerado `L` fixado no percentil 99
(`CURVATURE_DEVIATION_PERCENTILE`) dos desvios da própria cena. O terreno
preferido é o de forma suave, nem fortemente côncavo nem fortemente convexo, e as
formas mais extremas ainda recebem 0,2 em vez de zero.

A adequabilidade `S` de cada célula é a média ponderada das notas disponíveis
para ela:

```text
S = soma( w_i * N_i ) / soma( w_i )
```

**A soma dos pesos é calculada célula a célula, e não uma vez para a cena
inteira.** Isso importa quando um critério não cobre toda a grade — um raster
adicional de extensão menor, ou o índice de umidade nas bordas: a célula
descoberta é pontuada apenas pelos critérios que de fato possui, com os pesos
renormalizados, em vez de receber nota zero pela ausência, o que equivaleria a
penalizá-la pela pior nota possível. Quando a renormalização afeta parte
apreciável da cena, o plugin avisa e recomenda cautela na comparação entre
células. Pesos negativos são recusados e a soma dos pesos tem de ser maior que
zero.

**Sobre o peso da altitude.** Ele vale 0 por padrão, de propósito. A altitude
entra no modelo como *restrição* — a faixa altimétrica —, não como preferência.
Como a altitude normalizada cresce monotonicamente, qualquer peso acima de zero
significa literalmente "quanto mais alto, melhor para uma trilha", o que
raramente é a intenção.

Duas restrições booleanas atuam antes de a nota ser usada: a faixa altimétrica
(`ALT_MIN`, `ALT_MAX`) e a declividade máxima (`SLOPE_MAX`). Células fora delas
ficam de fora das zonas, e células acima de `SLOPE_MAX` não são navegáveis pela
rota.

## Risco topográfico relativo

Indicador próprio, construído a partir dos mesmos critérios, e não o complemento
da adequabilidade:

```text
risco = 0,75 * clip(D / SLOPE_MAX, 0, 1)^1,35  +  0,25 * (Ch' + Cv') / 2
```

em que `Ch'` e `Cv'` são os módulos das curvaturas normalizados pelo percentil 95
dos seus próprios valores absolutos (`CURVATURE_RISK_PERCENTILE`). O expoente
`SLOPE_RISK_EXPONENT = 1,35` faz encostas próximas do limite pesarem
desproporcionalmente. Os pesos são `RISK_SLOPE_WEIGHT = 0,75` e
`RISK_CURVATURE_WEIGHT = 0,25`. É, por construção, **relativo à cena analisada**,
e não uma medida absoluta de perigo; os expoentes e pesos são constantes
empíricas do modelo e devem ser declarados quando os valores forem citados.

## Classes de transitabilidade

Diferente em natureza da adequabilidade, que é contínua e relativa. A base são
cinco classes definidas por quatro limiares **absolutos** de declividade,
`DEFAULT_SLOPE_BREAKS = (20, 35, 60, 100)` por cento, expostos no parâmetro
`TRANSITABILITY_BREAKS`:

| Classe | Declividade | Rótulo (pt / en) |
|---|---|---|
| 1 | < 20% | Suave / Gentle |
| 2 | 20 a 35% | Moderada / Moderate |
| 3 | 35 a 60% | Forte / Steep |
| 4 | 60 a 100% | Muito forte / Very steep |
| 5 | > 100%, ou bloqueada | Escarpada / Escarpment |

Ser absoluto é o ponto: uma classe tem de significar a mesma coisa na Mantiqueira
e nos Andes, ou dois mapas não se comparam. **Os rótulos descrevem a declividade,
não um veredito sobre quem passa.** Uma versão anterior chamava a classe 5 de
intransponível, e 25.113 fixos de GPS sobre terreno comprovadamente percorrido a
pé falsificaram isso: a maior declividade efetivamente caminhada foi de 115,8%,
dentro da classe 5. Os limiares foram mantidos e os rótulos reescritos; um teste
impede que a afirmação antiga volte. Os rótulos vivem em `i18n/*.json`, nos seis
idiomas — essa é a fonte única deles — e são preenchidos com os limiares que a
execução realmente usou, de modo que a legenda não pode contradizer o dado que
descreve.

Três modificadores atuam sobre a classe base, e precisam ser declarados junto de
qualquer número extraído do mapa:

* rugosidade acima do percentil 90 da cena (`ROUGHNESS_PERCENTILE`) rebaixa a
  célula uma classe;
* umidade acima do percentil 95 (`WETNESS_PERCENTILE`) rebaixa a célula uma
  classe;
* célula bloqueada por restrição vai diretamente para a classe 5.

Os dois primeiros nunca criam classe 5 — terreno rugoso ou encharcado é pior de
caminhar, mas não é um paredão — e são relativos à cena de propósito: a
rugosidade absoluta depende da resolução do MDE e o TWI depende do tamanho da
bacia, de modo que um limiar absoluto para eles não seria transferível. A
consequência é que a comparabilidade estrita entre cenas vale para a
classificação por declividade, e não para o mapa final.

Acima de `COARSE_CELL_WARNING_M = 60 m` de tamanho de célula o plugin avisa que a
classificação passou a descrever a média da paisagem em vez do terreno que uma
pessoa encontra: no mesmo terreno, passar de 30 m para 250 m move 27 pontos
percentuais de área para a classe 1.

A legenda é gravada no próprio raster de saída, no idioma da execução, e é
gravada duas vezes porque o GeoTIFF não tem lugar padrão para nomes de
categoria. O GDAL grava os nomes de categoria no `*.tif.aux.xml` ao lado do
raster, que é o que o QGIS lê para montar a legenda; os mesmos cinco rótulos vão
também como os metadados GDAL `TOPOTRAIL_CLASSE_1` a `TOPOTRAIL_CLASSE_5`, que o
driver GTiff guarda na etiqueta `GDAL_METADATA` **dentro** do `.tif`, junto com a
paleta de cores. Um `.tif` separado do seu arquivo irmão conserva, portanto, as
cores e o significado de cada uma.

## Zonas de acesso potencial

Células cuja adequabilidade está acima de um limiar, vetorizadas em polígonos com
os campos `value`, `area_m2` e `area_ha`. O limiar é declarado (`THRESHOLD`) ou,
quando este é zero, tirado de um percentil da própria adequabilidade da cena
(`AUTO_PERCENTILE`, padrão 75). Com `ALTITUDE_BAND_THRESHOLD` ligado — que é o
padrão, e vale apenas para o limiar automático — o percentil é tomado **dentro de
cada faixa altimétrica** de `ALTITUDE_BAND_SIZE_M` (padrão 200 m, mínimo 50 m),
para que uma cena alta não selecione só os seus fundos de vale. Fragmentos
menores que `MIN_PATCH_AREA_HA` (padrão 50 ha) são descartados.

## Superfície de custo, rota e corredor

A rota pode ser calculada sob **três modelos de custo**. O parâmetro
`ROUTE_COST_MODEL` os seleciona, e o padrão publicado, tanto na janela quanto na
caixa de ferramentas de Processing, é o de Tobler.

**Inverso**, `1 / (S + 0,05)` (`ROUTE_COST_EPSILON`). É o modelo das versões
0.5.x, mantido por continuidade e com um defeito diagnosticado: o contraste que
ele aparenta oferecer pressupõe que `S` percorra todo o intervalo [0, 1],
enquanto em cena real a distribuição é concentrada no miolo. Na cena da
Mantiqueira, o percentil 5 da adequabilidade é 0,49 e o percentil 95 é 0,77, de
modo que o custo entre esses dois percentis varia apenas por um fator de 1,5 —
contraste insuficiente para que valha a pena desviar.

**Exponencial**, `exp(k * (1 - S))`, com `k = ROUTE_CONTRAST` e padrão
`DEFAULT_ROUTE_CONTRAST = 6,0`. Preserva o contraste independentemente de quão
comprimida esteja a distribuição, e torna `k` o controle explícito de quanto vale
a pena desviar.

**Tempo de caminhada (Tobler), o padrão e o modelo recomendado.** Aqui o custo
deixa de ser adimensional e passa a ser hora. O tempo de um passo de comprimento
horizontal `L` e desnível `Δz` é a função de caminhada de Tobler (1993)
multiplicada por um retardo por terreno:

```text
t = (L/1000) / ( 6,0 * exp(-3,5 * |Δz/L + 0,05|) )  *  retardo
retardo(célula) = 1 + 2,0 * (1 - S)
```

com `TOBLER_MAX_SPEED_KMH = 6,0`, `TOBLER_DECAY = 3,5`,
`TOBLER_OPTIMUM_SLOPE = 0,05` e `TERRAIN_SLOWDOWN_MAX = 2,0`. O retardo
efetivamente cobrado num passo é a **média do retardo das duas células**, de modo
que terreno perfeito caminha na velocidade de Tobler e o pior terreno leva três
vezes mais tempo. O primeiro fator é anisotrópico — a velocidade máxima está numa
descida suave, em `Δz/L = −0,05`, e não no plano — e essa assimetria é exatamente
o que uma superfície isotrópica não consegue exprimir.

Duas consequências da estrutura merecem registro. Multiplicar a velocidade máxima
por uma constante divide todos os custos pela mesma constante, então **o caminho
escolhido é bit a bit idêntico**; só a duração estimada escala. Por isso a rota
também traz `tempo_campo_h`, a mesma rota reescalada para
`FIELD_SURVEY_SPEED_KMH = 2,4`, o ritmo mediano medido em levantamento de campo.
E Tobler descreve um caminhante sem carga sobre trilha existente: é estimativa de
esforço relativo, não previsão de horário.

### A busca

O caminho é obtido por **A\*** sobre a vizinhança de oito células, com heurística
construída a partir do tempo mínimo por metro na cena, o que a mantém admissível
e consistente e, portanto, mantém o resultado ótimo. Uma vizinhança de oito
células impõe um viés direcional conhecido: um trajeto a 22,5° dos eixos da grade
sai até 8,2% mais longo que a distância que representa (Rees 2004; Medrano 2021).
Comprimentos de rota devem ser lidos com essa margem, e diferenças dessa ordem
entre dois traçados não são interpretáveis como diferença de terreno.

**A regra do passo diagonal (desde a 1.3.0).** O passo diagonal atravessa o
vértice compartilhado por quatro células, e duas delas não são nem a origem nem o
destino do passo: são as células que ele contorna. Olhar apenas a célula de
destino — que é o que a implementação fazia até a versão 1.2.0, como faz boa
parte das implementações de vizinhança de oito — permite que a rota escape por
uma passagem de largura zero entre duas células declaradas intransponíveis, e que
cruze um canal sem pousar em nenhuma célula de curso d'água, de modo que o fator
de vadeação não é cobrado e a travessia nunca chega à lista conferida em campo. A
partir da 1.3.0 um passo diagonal só existe onde há passagem por fora dele: as
duas células ortogonais que ele contorna têm de ser transponíveis, e quando o
maior fator de travessia delas excede o que as duas células do próprio passo já
cobram, o passo paga a diferença. Uma célula fora da janela de busca não é
barreira — é terreno que a janela não cobre. Quando os dois pontos passam a não
se conectar por causa disso, a mensagem de erro diz que o que falta é largura, e
não declividade admitida.

### Vários destinos

Com destinos intermediários, a rota é a concatenação dos trechos consecutivos, o
que é ótimo dada a ordem. Pedida a otimização da ordem (`OPTIMISE_ORDER`), ela é
resolvida **exatamente** pela programação dinâmica de Held & Karp (1962), tratada
como caminho hamiltoniano dirigido, porque a matriz de custos é assimétrica no
modo de tempo — subir e descer não custam o mesmo. O limite de
`MAX_OPTIMISED_WAYPOINTS = 8` pontos intermediários não decorre da programação
dinâmica, que com oito pontos é de microssegundos, e sim da montagem da matriz de
custos, que exige da ordem de n² execuções completas do A\*.

### Corredor

Um buffer métrico em torno da rota, com raio declarado pelo usuário
(`ROUTE_BUFFER_M`, padrão 100 m) — um raio de 100 m produz, portanto, um corredor
de 200 m de largura.

## Travessia graduada de cursos d'água

Quando a extração de drenagem está ativa, cada célula de canal recebe um fator
multiplicador do custo em função da área de contribuição da bacia a montante. O
MDE não sabe vazão nem estação; sabe a área de contribuição, e a geometria
hidráulica liga uma coisa à outra — largura e vazão de canal crescem com a área de
drenagem em lei de potência (Leopold & Maddock 1953; Faustini, Kaufmann & Herlihy
2009, largura de margens plenas W ~ A^0,5 em rios vadeáveis dos EUA).

| Classe | Área de contribuição | Tratamento |
|---|---|---|
| Córrego de cabeceira | < 2 km² | custo × 2 |
| Riacho | 2 a 10 km² | custo × 4 |
| Rio pequeno | 10 km² até o teto vadeável | custo × 8 |
| Rio | acima do teto (`STREAM_FORD_MAX_KM2`, padrão 50 km²) | barreira; a travessia não é presumida |

`FORD_CLASSES` guarda as três primeiras. As classes são um **proxy declarado, não
uma medida de segurança**: cada travessia que a rota efetivamente faz sai numa
camada vetorial própria com a área de contribuição, a classe, o fator aplicado e
um aviso de conferência em campo, de modo que a decisão volte para quem vai
caminhar em vez de ficar escondida dentro do custo.

Uma camada de restrição fornecida pelo usuário é outra coisa. Ela é dilatada por
`CONSTRAINT_BUFFER_M` (padrão 30 m) e então excluída de vez
(`CONSTRAINT_AVOID`, o padrão) ou encarecida por
`CONSTRAINT_PENALTY_FACTOR = 8,0` (`CONSTRAINT_PENALISE`). Drenagem como
restrição vem **desligada** por padrão, e isso é decisão apoiada em evidência,
não esquecimento: nos trajetos de campo da caatinga as trilhas reais cruzaram
1,37 canais por km contra 0,68 da linha reta entre os mesmos extremos. Não há
evitação revelada a calibrar — ver [`VALIDACAO.md`](../VALIDACAO.md), seções 6 e
8.4.

## O registro de diagnóstico

Toda execução grava `*_diagnostico_topotrail.log`: um registro JSON por etapa,
com a versão do plugin, as versões do Python, do GDAL e do sistema operacional,
**todos os 45 parâmetros como foram resolvidos**, e as estatísticas de
distribuição de cada raster intermediário — inclusive o modelo de custo
efetivamente usado e os sete pesos. É o que permite rastrear uma rota apresentada
num relatório até a análise que a produziu, e é a forma prevista de um terceiro
reproduzir uma execução. `exemplo/` traz um exemplo completo com os valores de
saída esperados.

## Constantes empíricas nomeadas

Todas vivem em `processing/algorithm.py`, salvo indicação em contrário. São
decisões de modelagem, não medições, exceto onde
[`VALIDACAO.md`](../VALIDACAO.md) diz o contrário — e devem ser reportadas junto
de qualquer resultado tirado do plugin.

| Constante | Valor | O que define |
|---|---|---|
| `CURVATURE_SCORE_FLOOR` | 0,2 | Menor nota que uma curvatura extrema pode receber. |
| `CURVATURE_DEVIATION_PERCENTILE` | 99,0 | Desvio de curvatura tolerado na nota de adequabilidade. |
| `CURVATURE_RISK_PERCENTILE` | 95,0 | Normalização das curvaturas no indicador de risco. |
| `SLOPE_RISK_EXPONENT` | 1,35 | Convexidade do termo de declividade do risco. |
| `RISK_SLOPE_WEIGHT` / `RISK_CURVATURE_WEIGHT` | 0,75 / 0,25 | Repartição do indicador de risco. |
| `ROUTE_COST_EPSILON` | 0,05 | O `eps` do modelo de custo inverso. |
| `DEFAULT_ROUTE_CONTRAST` | 6,0 | `k` padrão do modelo exponencial. |
| `TOBLER_MAX_SPEED_KMH` | 6,0 | Velocidade máxima de Tobler. Não altera o traçado. |
| `TOBLER_DECAY` | 3,5 | Decaimento de Tobler. Confirmado contra sete trilhas reais. |
| `TOBLER_OPTIMUM_SLOPE` | 0,05 | Gradiente de velocidade máxima, uma descida suave. |
| `FIELD_SURVEY_SPEED_KMH` | 2,4 | Ritmo de campo medido, para a segunda duração. |
| `TERRAIN_SLOWDOWN_MAX` | 2,0 | Retardo máximo por terreno. Existência validada; magnitude indeterminada entre 2,0 e 4,0. |
| `CONSTRAINT_PENALTY_FACTOR` | 8,0 | Fator de custo de restrição penalizada. Não calibrado; ver `VALIDACAO.md` §8.4. |
| `FORD_CLASSES` | 2 / 10 km², ×2 ×4 ×8 | Classes de travessia por área de contribuição. |
| `DEFAULT_STREAM_FORD_MAX_KM2` | 50,0 | Teto vadeável padrão; acima dele, barreira. |
| `MAX_OPTIMISED_WAYPOINTS` | 8 | Teto da otimização exata de ordem de visita. |
| `DEFAULT_SLOPE_BREAKS` (`transitability.py`) | 20, 35, 60, 100 % | Os quatro limiares de transitabilidade. |
| `ROUGHNESS_PERCENTILE` (`transitability.py`) | 90,0 | Rugosidade acima da qual a célula é rebaixada uma classe. |
| `WETNESS_PERCENTILE` (`transitability.py`) | 95,0 | Umidade acima da qual a célula é rebaixada uma classe. |
| `COARSE_CELL_WARNING_M` (`transitability.py`) | 60,0 | Tamanho de célula acima do qual a classificação recebe aviso. |
| `SATURATION_WARNING_FRACTION` / `MIN_SCORE_AMPLITUDE` | 0,40 / 0,05 | Quando o plugin avisa que o modelo deixou de discriminar. |
| `NEAREST_VALID_CELL_RADIUS` / `NEAREST_VALID_CELL_WARN_M` | 30 células / 100,0 m | Quanto um extremo de rota pode ser deslocado até célula válida, e quando isso é avisado. |
| `WARN_TERRAIN_CELLS` / `MAX_TERRAIN_CELLS` (`terrain.py`) | 8e6 / 1e8 | Tamanhos de grade em que derivar o relevo é avisado e depois recusado. |

## Limitações

* MDE ruim produz resultado ruim; nada a jusante conserta isso.
* Declividade, curvatura e rugosidade mudam com a resolução espacial, e a
  distribuição das classes de transitabilidade muda bastante. Informe o tamanho
  da célula ao lado de qualquer número tirado destes mapas.
* Sobre floresta, a maioria dos MDEs globais dá o dossel, não o solo. Atributos
  calculados numa vizinhança 3×3 amostram, em parte, o interpolador, e não o
  microrrelevo.
* A vizinhança de oito células enviesa o comprimento da rota em até 8,2%.
* O operador de curvatura atenua formas curtas, nas proporções declaradas acima.
* Onde o gradiente é nulo a curvatura é indefinida e recebe a melhor nota
  possível, o que favorece terreno plano em relevo baixo.
* O indicador de risco é relativo à cena, nunca um mapa absoluto de perigo.
* Os pesos, o limite de declividade e o percentil de corte são juízo do usuário,
  e não padrões calibrados: exigem justificativa. O que *foi* calibrado contra
  trilhas reais são duas constantes internas do modelo de custo — o decaimento da
  função de caminhada e o retardo máximo por terreno —, que não aparecem entre os
  pesos.
* A duração em ritmo de Tobler é estimativa de esforço relativo, não previsão de
  horário: contra GPS de campo ela é otimista por um fator de 1,7 a 3,1.
* Hidrografia, trilhas existentes, estradas, uso do solo, propriedade, vegetação
  e restrições legais são complementares a este núcleo topográfico, e devem ser
  sobrepostas a ele no QGIS.
* Nada disto substitui validação de campo.

## Referências

Barnes R, Lehman C & Mulla D (2014) Priority-flood: an optimal depression-filling
and watershed-labeling algorithm for digital elevation models. *Computers &
Geosciences* 62: 117–127.

Beven KJ & Kirkby MJ (1979) A physically based, variable contributing area model
of basin hydrology. *Hydrological Sciences Bulletin* 24: 43–69.

Faustini JM, Kaufmann PR & Herlihy AT (2009) Downstream variation in bankfull
width of wadeable streams across the conterminous United States. *Geomorphology*
108: 292–311.

Held M & Karp RM (1962) A dynamic programming approach to sequencing problems.
*Journal of the SIAM* 10: 196–210.

Leopold LB & Maddock T (1953) *The hydraulic geometry of stream channels and some
physiographic implications*. USGS Professional Paper 252.

Medrano FA (2021) Effects of raster terrain representation on GIS shortest path
analysis. *PLOS ONE* 16: e0250106.

Mitášová H & Hofierka J (1993) Interpolation by regularized spline with tension:
II. Application to terrain modeling and surface geometry analysis. *Mathematical
Geology* 25: 657–669.

Moore ID, Grayson RB & Ladson AR (1991) Digital terrain modelling. *Hydrological
Processes* 5: 3–30.

O'Callaghan JF & Mark DM (1984) The extraction of drainage networks from digital
elevation data. *Computer Vision, Graphics, and Image Processing* 28: 323–344.

Rees WG (2004) Least-cost paths in mountainous terrain. *Computers & Geosciences*
30: 203–209.

Riley SJ, DeGloria SD & Elliot R (1999) A terrain ruggedness index that quantifies
topographic heterogeneity. *Intermountain Journal of Sciences* 5: 23–27.

Sappington JM, Longshore KM & Thompson DB (2007) Quantifying landscape ruggedness
for animal habitat analysis. *Journal of Wildlife Management* 71: 1419–1426.

Tobler W (1993) *Three presentations on geographical analysis and modeling*. NCGIA
Technical Report 93-1.
