# Validação empírica das constantes do TopoTrail

Este documento registra a primeira confrontação do modelo do TopoTrail com
terreno realmente percorrido a pé. Até esta versão, cinco constantes governavam
o resultado do plugin sem nenhuma verificação externa: os três parâmetros da
função de Tobler, os limites de classe de transitabilidade e o fator de
penalidade das restrições. O que segue é o que os dados de campo mostraram —
inclusive onde contrariaram o que o próprio plugin afirmava.

## 1. Dados

Onze trajetos de GPS cedidos pelo autor, registrados em levantamento de campo
(Projeto Herpeto Mantiqueira e campanhas na caatinga), somando **110 horas** e
**224 km** de deslocamento, em duas regiões e dois biomas:

| Região | Trajetos | Extensão | Duração | MDE usado | Célula |
|---|---|---|---|---|---|
| Serra da Mantiqueira (SP/MG) | 2 com estampa de tempo + 1 travessia sem | 1,2 km | 1,7 h | cartas topográficas 1″ | 30 m |
| Caatinga (PI/CE) | 9 | 223 km | 108,7 h | Copernicus DEM GLO‑90 | 90 m |

Nove trajetos são `gx:Track` do KML com estampa de tempo por fixo (22 mil fixos
datados); a travessia Marins–Itaguaré tem geometria mas não tem tempo, e serve
apenas para validação geométrica.

Um dos trajetos da caatinga (`dia_20_e_21_junho`) contém um deslocamento de
automóvel — o GPS ficou ligado no trajeto até o litoral. O filtro de velocidade
o identificou sozinho: das 884 janelas possíveis, apenas 92 (10,4%) sobreviveram
ao teto de 12 km/h, contra 60–96% nos demais trajetos. Isso é registrado aqui
não como incidente, mas porque é evidência de que o filtro faz o que promete.

## 2. Método

Cada trajeto é projetado no seu fuso UTM e cortado em janelas de comprimento de
percurso fixo. Uma janela de **comprimento** fixo, e não de tempo fixo, é
essencial: uma janela de tempo mistura trechos longos e planos com trechos
curtos e íngremes, e o gradiente da janela então não corresponde a nada que
tenha sido caminhado.

Para cada janela: distância horizontal percorrida, desnível lido **no MDE**
(não no GPS — o erro vertical do GPS de consumo é 2 a 3 vezes o horizontal, e a
diferença de duas altitudes ruidosas em 180 m é dominada por ruído; além disso
o MDE é o que o próprio plugin usa, então uma calibração contra o GPS não
transferiria), gradiente = desnível / distância, velocidade = distância /
tempo. Janelas contendo pausa maior que 120 s são descartadas: numa campanha
herpetológica, parar para manejar um animal não é caminhar devagar, é não
caminhar.

## 3. Resultado: a função de Tobler

Ajuste de `W = vmax · exp(−decay · |S + ótimo|)` por mínimos quadrados no
logaritmo da velocidade, caatinga, 270 janelas de 180 m, excluído o trecho de
automóvel:

| Parâmetro | Publicado (Tobler 1993) | Observado | Erro-padrão |
|---|---|---|---|
| vmax | 6,0 km/h | **2,45** | ± 0,09 |
| decay | 3,5 | **1,50** | ± 0,38 |
| ótimo | +0,05 | **0,00** | ± 0,02 |

**R² (no log) = 0,04.** O gradiente explica cerca de 4% da variância da
velocidade observada. Reescalando apenas o `vmax` e mantendo a forma publicada,
o R² é *negativo* (−0,12): dentro da faixa observada (|S| < 0,25), a curva de
Tobler ajusta pior que uma velocidade constante.

### 3.1 Isto é real ou artefato? Três controles

**A. Comprimento da janela.** O `decay` estimado é 0,0 em janelas de 90 m — uma
célula do MDE não resolve gradiente nenhum — e estabiliza entre 1,3 e 1,7 para
janelas de 180 m ou mais, até 720 m. Não é artefato de janelamento; 180 m é o
limite inferior válido para um MDE de 90 m.

**B. Definição de parada.** Aqui está a maior sensibilidade do estudo:

| Pausa tolerada | n | vmax | decay |
|---|---|---|---|
| 20 s | 83 | 3,60 | 1,14 |
| 60 s | 198 | 2,88 | 1,36 |
| 120 s | 270 | 2,43 | 1,31 |
| sem filtro | 345 | 1,92 | 1,00 |

O **vmax não é identificável** a partir destes dados: varia de 1,9 a 3,6 km/h
conforme o que se decide chamar de parada. O **decay é estável** (1,0–1,4) em
todos os critérios. A forma da curva é robusta; a escala não é.

**C. Diluição de regressão.** O gradiente vem de um MDE de 90 m, fortemente
suavizado; erro de medida no preditor achata a estimativa em direção a zero.
Substituindo a altimetria do MDE pela do GPS, o `decay` sobe de 1,69 para
**2,31 ± 0,68** em janelas de 360 m — a 1,7 desvios-padrão dos 3,5 publicados.

## 4. O que foi feito com isso

### 4.1 vmax: erro grande, consequência nula sobre a rota

O `vmax` é o parâmetro medido com mais confiança e é o que **menos importa**. O
A* compara custos relativos: multiplicar a velocidade por uma constante divide
todos os custos pela mesma constante, a ordenação não muda e o caminho
escolhido é **bit a bit idêntico**. Verificado computacionalmente para
vmax ∈ {2,4; 3,0; 5,0; 6,0; 8,0}: mesma rota, e custo escalando exatamente por
6/vmax, sem resíduo. A propriedade está fixada em
`tests/test_routing_math.py::test_the_route_does_not_depend_on_tobler_s_maximum_speed`.

O erro aparece inteiramente na **duração estimada**, que é otimista por um fator
de 1,7 a 3,1 para trabalho de campo. Documentado no código e exposto como
`FIELD_SURVEY_SPEED_KMH = 2.4` para quem quiser uma estimativa de tempo
realista.

### 4.2 decay: consequência grande, medida inconclusiva

O inverso. O `decay` **muda a rota**: entre 1,3 e 3,5, os caminhos escolhidos
compartilham apenas 9% das células. E é justamente o parâmetro que a calibração
não conseguiu determinar — o intervalo de confiança cobre desde 1,0 até,
corrigida a diluição, algo próximo de 3,5.

**Decisão: mantém-se o valor publicado de 3,5.** Não há base para substituir uma
constante da literatura por uma estimativa própria menos precisa que ela. Isto é
registrado como a principal limitação conhecida do modelo, e o teste
`test_the_route_does_depend_on_the_decay` existe para impedir que alguém
futuramente presuma que o `decay` é tão inócuo quanto o `vmax`.

### 4.3 O achado desconfortável

Com R² de 0,04, **a topografia não é o que determina o ritmo de um levantamento
de campo**. Vegetação, carga, terreno sob os pés e comportamento de busca
dominam. A função de Tobler permanece a melhor base disponível para *comparar*
trechos entre si — que é do que a rota precisa — mas a duração que ela devolve
não deve ser lida como previsão de tempo de campo, e o plugin não deve
apresentá-la como tal.

## 5. Resultado: as classes de transitabilidade

Classes atribuídas a 28.567 fixos de GPS sobre terreno comprovadamente
percorrido a pé:

| Classe (limite) | Mantiqueira (30 m) | Caatinga (90 m) |
|---|---|---|
| 1 (< 20%) | 0,0% | 56,3% |
| 2 (20–35%) | 52,7% | 24,8% |
| 3 (35–60%) | 33,0% | 13,0% |
| 4 (60–100%) | 14,4% | 5,8% |
| 5 (> 100%) | 0,0% | 0,08% |

**A legenda anterior estava errada.** A classe 5 chamava-se "intransitável a pé"
e a classe 4 "muito difícil, escalonamento". Uma equipe de campo com equipamento
percorreu 14,4% do trajeto da Mantiqueira em classe 4, e a maior declividade
efetivamente caminhada foi de **115,8%** — acima do limite que a legenda
declarava intransponível.

Os **limites permanecem** (20/35/60/100% são estratos de declividade
defensáveis, e a classe 5 é de fato rara nos trajetos reais). Os **rótulos
mudaram** para descrever declividade em vez de emitir um veredito sobre quem
consegue passar: "1 – Suave (< 20%)" … "5 – Escarpada (> 100%)". Fixado em
`test_the_labels_do_not_claim_a_verdict_about_the_walker`.

## 5b. Resultado: a geometria das rotas

A pergunta que faltava: a rota que o plugin desenha passa por onde as pessoas
passam? Critério de Goodchild & Hunter (1997) — proporção da trilha real que cai
dentro de um buffer em torno da rota modelada — sempre acompanhado do mesmo
número para uma **linha reta** entre os mesmos extremos. A linha reta é o modelo
nulo: se a rota do plugin não vence a linha reta, o modelo de custo não está
contribuindo nada.

### 5b.1 Deslocamentos de trabalho (caatinga, 7 trajetos, 61,5 km)

| Trajeto | real | reta | plugin | concord. <250 m reta | plugin | desvio mediano reta | plugin |
|---|---|---|---|---|---|---|---|
| dia_18_junho_covao | 11,7 km | 2,7 | 3,9 | 15,7% | **86,4%** | 865 m | **140 m** |
| dia_19_junho | 10,6 | 3,0 | 4,0 | 45,8% | **99,5%** | 364 m | **128 m** |
| trajeto_1_janeiro | 14,3 | 6,5 | 6,9 | 26,6% | **96,3%** | 349 m | **91 m** |
| trajeto_2_janeiro | 9,9 | 3,6 | 3,8 | 67,7% | **90,2%** | 167 m | **122 m** |
| trajeto_3_janeiro | 5,3 | 3,0 | 3,3 | 49,3% | 48,8% | 259 m | 281 m |
| trajeto_4_janeiro | 3,9 | 1,4 | 1,6 | 59,0% | 67,4% | 176 m | 179 m |
| trajeto_5_janeiro | 5,9 | 3,5 | 3,9 | 100% | 100% | 31 m | 33 m |

**O plugin vence o modelo nulo com folga em 4 dos 7 trajetos e empata nos
outros 3.** Nos quatro casos de ganho, o desvio mediano cai de 349–865 m para
91–140 m, uma redução de 3 a 6 vezes. Nos empates, ou o trajeto é curto e quase
retilíneo (trajeto_5, sinuosidade 1,67, ambos com 100%), ou o modelo não
encontrou estrutura para explorar.

Viés sistemático a registrar: a rota modelada acumula muito menos subida que a
real (por exemplo 478 m contra 1.901 m em dia_18_junho_covao). O modelo prefere
contornar; as equipes sobem mais do que precisariam. Parte disso é objetivo de
amostragem, parte é que o modelo não conhece o que há sob os pés.

### 5b.2 O caso em que o plugin perde: travessia Marins–Itaguaré

| | comprimento | sinuosidade | concord. <250 m | desvio mediano | cume | subida acumulada | adequab. média |
|---|---|---|---|---|---|---|---|
| Trilha real | 21,66 km | 2,43 | — | — | 2.398 m | 2.180 m | 0,643 |
| Linha reta (controle) | 8,91 | 1,00 | 25,3% | 643 m | 2.197 m | 1.370 m | 0,659 |
| Plugin (Tobler) | 11,01 | 1,23 | 2,7% | 1.860 m | 1.679 m | 427 m | 0,746 |

Aqui o plugin é **três vezes pior que a linha reta**. O diagnóstico é claro e
não é um defeito de implementação: a trilha real sobe a 2.398 m, que é o ponto
mais alto de toda a cena, e acumula 2.180 m de subida. A rota do plugin sobe
427 m — cinco vezes menos — sobre terreno de adequabilidade **maior** (0,746
contra 0,643) e declividade menor (20,1% contra 29,9%).

Ou seja: o modelo achou um caminho genuinamente mais fácil. Quem percorreu a
travessia não estava minimizando esforço — estava subindo o Marins e o Itaguaré,
que é o propósito da travessia. **É incompatibilidade de objetivo, não erro de
modelo**, e só é lícito afirmar isso porque a rota modelada é mensuravelmente
mais fácil, e não apenas diferente.

**Consequência para o escopo:** o TopoTrail modela deslocamento de acesso, não
travessia de cumes nem trilha recreativa com objetivo panorâmico. Isso passa a
ser uma limitação declarada, não uma suposição.

## 6. Resultado: cursos d'água não são evitados

`CONSTRAINT_PENALTY_FACTOR = 8,0` supõe que atravessar drenagem é custoso e que
as pessoas desviam. Teste de preferência revelada: cruzamentos de canal por km
na trilha real contra a linha reta entre os mesmos extremos, 7 trajetos, 61,5 km.

| | cruzamentos | por km |
|---|---|---|
| Trilhas reais | 84 | **1,37** |
| Linha reta (controle) | 16 | 0,68 |

As equipes cruzaram **o dobro** da drenagem que o acaso geométrico produziria.
Não há evitação a calibrar — há o contrário. Em paisagem semiárida o leito seco
é frequentemente a melhor superfície de caminhada, e num levantamento
herpetológico a drenagem é alvo de amostragem, não obstáculo.

**Decisão:** o fator não é calibrável com estes dados e passa a ser documentado
como intensidade declarada pelo usuário, não como constante medida. A restrição
de cursos d'água permanece **opcional e desligada por padrão**, com aviso
explícito no código de que penalizá-la por padrão afastaria a rota justamente do
que este tipo de usuário quer visitar.

## 6b. Resultado: dependência de resolução

Mesmo terreno da Mantiqueira, variando apenas o tamanho da célula:

| Célula | Declividade mediana | Classe 1 | Classe 4 |
|---|---|---|---|
| 30 m | 20,7% | 48,2% | 1,65% |
| 60 m | 19,5% | 51,3% | 1,22% |
| 90 m | 18,0% | 55,8% | 0,86% |
| 180 m | 13,8% | 69,0% | 0,33% |
| 250 m | 11,3% | 75,7% | 0,18% |

A proporção de terreno "suave" passa de 48% para 76% sem que nada no terreno
mude, e a classe 4 cai nove vezes. O mapa de transitabilidade é fortemente
dependente da resolução, e o plugin não registrava nem avisava isso.

Corrigido: `classify()` passou a receber `cell_size_m`, a gravá-lo nas métricas
e a emitir aviso acima de 60 m. **Nenhum número tirado deste mapa é
interpretável sem o tamanho da célula ao lado**, e isso vale para qualquer
seção de métodos que os cite.

## 6c. Resultado: o retardo por terreno não prevê ritmo

O modelo afirma que o tempo é `tobler(gradiente) × (1 + 2,0 × (1 − S))`, com S a
adequabilidade. Em logaritmo isso é linear e o coeficiente é estimável. Ajuste
conjunto sobre 270 janelas da caatinga:

| Parâmetro | No código | Ajustado |
|---|---|---|
| vmax | 6,0 | 2,22 ± 0,16 |
| decay | 3,5 | 1,17 ± 0,40 |
| **SLOWDOWN** | **2,0** | **−0,32 ± 0,18** |

O coeficiente sai indistinguível de zero e com o sinal trocado. A correlação
entre adequabilidade e log da velocidade é −0,064. Acrescentar o termo eleva o
R² de 0,024 para 0,034. **Como previsão de tempo, a constante não tem apoio
empírico nenhum.**

Duas ressalvas contra sobreinterpretar: a adequabilidade vem do mesmo MDE de
90 m e é quase colinear com a declividade que Tobler já usa, e ela não contém
vegetação — que é provavelmente o que de fato governa o ritmo na caatinga. O
resultado diz que *este proxy* não prevê ritmo, não que o terreno seja
irrelevante.

**Decisão: a constante fica, com o papel redefinido.** Ela não foi removida
porque sua função na rota não é prever tempo, e sim exprimir preferência —
caminhar por terreno mais suave é preferível por risco, esforço e erosão, mesmo
que o cronômetro não registre diferença. Mas isso é escolha de projeto, não
quantidade medida, e o nome "slowdown" prometia a segunda coisa. O efeito sobre
a geometria é grande: entre 0 e 2,0 as rotas compartilham 45% das células.
**É a maior alavanca ainda não calibrada do modelo**, e quem publicar números do
plugin deve declarar o valor usado.

## 8. Calibração contra o objetivo certo: a geometria

O estudo da seção 6c calibrou `TERRAIN_SLOWDOWN_MAX` contra **velocidade** e o
reprovou. A pergunta estava errada. Prever tempo nunca foi função dessa
constante — a função dela é escolher por onde a rota passa. Uma constante de
roteamento tem de ser medida contra roteamento.

Refeita a calibração contra a concordância geométrica com os sete trajetos de
trabalho (Goodchild–Hunter a 250 m), varrendo `TERRAIN_SLOWDOWN_MAX` e
`TOBLER_DECAY` conjuntamente:

| SLOWDOWN \ decay | 1,3 | 2,3 | **3,5** | 5,0 |
|---|---|---|---|---|
| 0,0 | 61,0% | 62,9% | 72,0% | 79,2% |
| 0,5 | 69,3% | 69,9% | 74,0% | 79,0% |
| 1,0 | 68,4% | 72,4% | 83,5% | 81,1% |
| **2,0** | 72,4% | 76,9% | **84,1%** | 84,9% |
| 4,0 | 74,0% | 79,3% | 87,9% | 86,6% |

### 8.1 O termo de terreno existe

Desligar `SLOWDOWN` custa **12 pontos de concordância** (72,0% contra 84,1%).
Contra o objetivo certo, o termo se sustenta com folga — o oposto do que a
calibração por velocidade sugeria. A seção 6c não estava errada nos números;
estava medindo outra coisa.

### 8.2 O `decay` publicado é confirmado

A concordância sobe monotonicamente de 72,4% em `decay = 1,3` para 84,1% em
3,5, e estabiliza depois. **A calibração geométrica confirma o 3,5 de Tobler**,
justamente onde o ajuste por velocidade sugeria 1,3. Como o `decay` governa
geometria e não ritmo, a medida geométrica é a que vale, e o valor publicado
fica — agora por evidência, não por deferência à literatura.

### 8.3 A magnitude do `SLOWDOWN` não é resolúvel com sete trilhas

O melhor valor no conjunto todo é 4,0, com 87,9% contra os 84,1% do padrão. Mas
sob **validação cruzada leave-one-out** — parâmetros escolhidos usando só os
outros seis trajetos, avaliados no que ficou de fora:

| Trajeto deixado de fora | Escolhido | No trajeto | Padrão (2,0; 3,5) |
|---|---|---|---|
| dia_18_junho_covao | (4,0; 3,5) | 86,4% | 86,4% |
| dia_19_junho | (4,0; 3,5) | 99,6% | 99,5% |
| trajeto_1_janeiro | (4,0; 3,5) | 96,3% | 96,3% |
| trajeto_2_janeiro | (4,0; 3,5) | 93,6% | 90,2% |
| trajeto_3_janeiro | (4,0; 3,5) | 48,8% | 48,8% |
| trajeto_4_janeiro | (4,0; 5,0) | 67,4% | 67,4% |
| trajeto_5_janeiro | (4,0; 3,5) | 92,5% | **100,0%** |
| **Média** | | **83,5%** | **84,1%** |

**Fora da amostra, o valor "melhor" é pior que o padrão.** É a assinatura
clássica de superajuste: sete curvas não sustentam o ajuste de dois parâmetros.

**Decisão: os padrões não mudam.** `TERRAIN_SLOWDOWN_MAX = 2,0` e
`TOBLER_DECAY = 3,5` permanecem — não por inércia, mas porque a calibração
honesta não produziu nada melhor. O que mudou é o estatuto: eram valores
arbitrários e passaram a ser valores com evidência. Separar 2,0 de 4,0 exige
mais trilhas, não mais análise.

### 8.4 Penalizar drenagem não ajuda a geometria

| Fator de penalidade | Concordância | Desvio mediano |
|---|---|---|
| 0,5 (drenagem como atrativo) | 69,4% | 194 m |
| **1,0 (desligado, padrão)** | **87,9%** | **130 m** |
| 2,0 | 87,7% | 129 m |
| 8,0 | 87,7% | 130 m |

Penalizar não melhora nada, e tratar drenagem como atrativo piora bastante. A
melhor política medida é a que já era o padrão: desligada. O fator permanece
disponível para restrições reais que o usuário queira impor — cerca, área
vedada, propriedade privada — e não como constante calibrada.

## 9. Rotas com múltiplos destinos, e o que isso provou

A limitação declarada na seção 5b.2 — o plugin perde para a linha reta na
travessia Marins–Itaguaré porque modela acesso e não travessia de cumes — era
uma hipótese sobre a causa. Com destinos intermediários implementados, ela pôde
ser testada: se a explicação estivesse certa, declarar os cumes deveria
recuperar a concordância; se fosse defeito do modelo, não deveria.

| | km | <60 m | <150 m | <250 m | <500 m | desvio mediano | cume | subida |
|---|---|---|---|---|---|---|---|---|
| Linha reta (controle) | 8,91 | 7,4% | 19,3% | 25,3% | 42,5% | 643 m | — | — |
| Plugin, só origem e destino | 11,01 | 0,7% | 1,7% | 2,7% | 6,8% | 1.860 m | 1.679 m | 427 m |
| Plugin + Marins | 12,45 | 16,3% | 27,4% | 48,9% | 69,6% | 256 m | 2.383 m | 924 m |
| Plugin + Marins, Marinzinho | 12,75 | 24,0% | 32,9% | 48,9% | 69,6% | 256 m | 2.383 m | 977 m |
| **Plugin + os três cumes** | 14,17 | **39,9%** | **54,2%** | **73,0%** | **97,6%** | **114 m** | 2.383 m | 1.107 m |
| Trilha real | 21,66 | — | — | — | — | — | 2.398 m | 2.180 m |

O desvio mediano cai de **1.860 m para 114 m** — dezesseis vezes — e a rota passa
a bater a linha reta com folga (73,0% contra 25,3%). **A hipótese da seção 5b.2
fica confirmada**: o modelo não errava, o objetivo é que estava subespecificado.

Implementação: `multi_leg_route()` encadeia o mesmo A* entre pontos
consecutivos, o que é ótimo dada a ordem. `optimise_waypoint_order()` resolve a
ordem por Held-Karp exato quando pedida — a matriz de custos é assimétrica no
modo de Tobler, porque subir e descer não custam o mesmo, então o problema é um
caminho hamiltoniano dirigido, e não o caixeiro-viajante simétrico. Limitado a
oito pontos intermediários, porque o custo cresce como 2ⁿn².

Na interface: camada de pontos opcional "Destinos intermediários, na ordem de
visita", e uma caixa para deixar o plugin escolher a ordem.

## 10. O que continua sem validação

Honestidade sobre o que este trabalho *não* resolveu:

- A **magnitude** de `TERRAIN_SLOWDOWN_MAX` continua indeterminada entre 2,0 e
  4,0 (§8.3). A existência do termo está validada e o padrão está justificado,
  mas separar os dois valores exige mais trajetos — o caminho é acumular
  trilhas, não refinar a estatística sobre as sete que existem.
- `CONSTRAINT_PENALTY_FACTOR = 8,0` continua sem calibração possível, porque o
  comportamento que ele modela não ocorre (§6) e impô-lo não melhora a
  geometria (§8.4). Permanece como intensidade declarada pelo usuário.
- Não há, neste conjunto, nenhuma trilha cujo objetivo declarado seja
  deslocamento eficiente ponto a ponto. Os trajetos de trabalho se aproximam
  disso e é por isso que a concordância é boa, mas são transectos de
  amostragem. A validação definitiva exige rota de acesso planejada para ser
  eficiente, percorrida e registrada.
- A amostra da Mantiqueira com estampa de tempo é pequena (17 janelas úteis) e
  não sustenta calibração própria; toda a calibração de Tobler vem da caatinga.
- Os trajetos são de uma única equipe, com um perfil de carga e de comportamento
  de busca. Generalizar para caminhada recreativa ou para carga militar não é
  legítimo a partir destes dados.

## 8. Reprodutibilidade

Os scripts de extração e ajuste estão em `validation/` (`tracks.py`,
`speed_slope.py`, `run_extract.py`, `fit_tobler.py`, `sensitivity.py`,
`classes_on_trails.py`). Dependem apenas de NumPy, SciPy, pyproj e GDAL. Os
trajetos de GPS não são redistribuídos com o repositório por conterem
localidades de ocorrência de espécies.

---

### Referências

Tobler, W. (1993) *Three presentations on geographical analysis and modeling.*
National Center for Geographic Information and Analysis, Technical Report 93‑1.
Santa Barbara.

Manly, B.F.J., McDonald, L.L., Thomas, D.L., McDonald, T.L. & Erickson, W.P.
(2002) *Resource Selection by Animals: Statistical Design and Analysis for Field
Studies.* 2ª ed. Kluwer, Dordrecht. [razões de seleção uso/disponibilidade]

Goodchild, M.F. & Hunter, G.J. (1997) A simple positional accuracy measure for
linear features. *International Journal of Geographical Information Science*
11: 299–306.
