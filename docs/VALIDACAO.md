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

## 6. Resultado: dependência de resolução

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

## 7. O que continua sem validação

Honestidade sobre o que este trabalho *não* resolveu:

- `CONSTRAINT_PENALTY_FACTOR = 8,0` e `TERRAIN_SLOWDOWN_MAX = 2,0` continuam
  empíricos e sem contraparte medida. Nenhum dado disponível os testa.
- A **geometria** das rotas ainda não foi comparada com as trilhas reais
  (concordância por buffer de Goodchild–Hunter contra um controle em linha
  reta). A travessia Marins–Itaguaré permite fazê‑lo e é o próximo passo.
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
