# TopoTrail — bateria de testes de ponta a ponta (1.0.0 → 1.1.0)

Corrida em QGIS 3.34 headless, plugin instalado como o usuário instala, sem geopandas/shapely. Três regiões de relevo muito diferente e casos de robustez; cada caso tem critério de aprovação automático. Script: `validation/bateria_regioes.py`.

| Região | Dado | Por quê |
|---|---|---|
| Serra da Mantiqueira — Marins × Itaguaré | MDE real de 1″ (folha 22S465 do TOPODATA/INPE, refinamento do SRTM; Valeriano & Rossetti 2012), 600–2401 m; trilha GPS real da travessia, com Pico do Marins, Marinzinho e Itaguaré marcados pelo caminhante; rasters de declividade e curvatura da própria carta | O caso de uso da dissertação: montanha, três destinos, comparação com trilha real |
| Ceará — P. E. das Carnaúbas | Copernicus GLO-90 real, 10–915 m; trajetos GPS de campo; poligonal do parque | Relevo baixo e seco, pixel de 90 m, drenagem e umidade importam, restrição por polígono |
| Himalaia | MDE sintético escalado para a faixa de altitude do Everest (3200–8848 m, 90 m); o download do tile Copernicus real é bloqueado neste ambiente. Não reproduz o relevo do Khumbu: medido contra um transecto SRTM real, é cerca de duas vezes mais íngreme e tem autocorrelação de desnível negativa, isto é, ruído e não forma de relevo. | Regime extremo de declividade: o que acontece quando quase tudo é classe 4–5 |
| Extras | Latitude 86° N; MDE em Web Mercator; camada de restrição em memória | Limites da UTM, CRS não métrico, camada sem arquivo |

## Resultado: 15 de 15 casos aprovados

Reexecutada na versao 1.2.0. Cada caso tem criterio de aprovacao automatico; a
coluna de resultado traz o que o caso mediu.

| Caso | Tempo | Resultado |
|---|---|---|
| **MQ-A travessia completa (3 cumes, 7 produtos)** | 4.0 s | travessias = 1; primeira_travessia = classe = córrego de cabeceira (< 2 km²); bacia_km2 = 1.489; fator_custo = 2; trechos = 4; tempo_h = 7.6; compr_m = 13616; ganho_m = 1110; distancia_aos_cumes_m = Marins = 10.3; Marinzinho = 9.7; Itaguare = 18.3; concordancia_com_trilha_real = 100m = rota_no_buffer_da_trilha = 0.592; trilha_no_buffer_da_rota = 0.626; 250m = rota_no_buffer_da_trilha = 0.835; trilha_no_buffer_da_r… |
| **MQ-A2 nenhum curso vadeavel: a drenagem vira barreira e o erro explica** | 3.0 s | erro = Exception: Nao foi possivel conectar os pontos da rota: nao existe caminho de celulas viaveis entre eles. Causas comuns: declividade maxima admitida baixa demais para o relevo (celulas acima dela sao intransponiveis), ca |
| **MQ-B cumes embaralhados + Held-Karp recupera a ordem** | 19.0 s | compr_m = 13679; compr_A = 13616; diferenca_relativa = 0.005; log = Otimizando a ordem de 3 pontos intermediarios (20 trechos a calcular).;   ordem informada: custo 10.8329; melhor ordem: custo 7.3154 (-32.5%) |
| **MQ-C rasters proprios da carta vs derivados; Shapefile em EPSG:31983** | 2.1 s | correlacao_das_notas = 0.841; formas = [434, 543]; [434, 543]; zonas_shp = 210; crs_zonas = 31983; unidade_declividade = Declividade do raster de entrada em porcentagem; Declividade máxima: 100.0% |
| **MQ-D restricao 'evitar' sobre a trilha real; KML; legenda em japones** | 2.9 s | rota_dentro_da_faixa_proibida = 0; legenda_ja = True; kml_crs = 4326; restricao = Camada de restricao: 1 feicoes, buffer de 0 m, 1,396 celulas atingidas (0.59% da grade).; Restricoes: 1,396 celulas atingidas (0.59% da area valida), excluidas das zonas; para a rota: camada excluida, drenagem graduada pelo tamanho do curso. |
| **MQ-E tres modelos de custo + restricao 'penalizar'** | — | inverso = 4899; None; exponencial = 5151; None; tobler = 5651; 3.736120688825416 |
| **CE-A Carnaubas: drenagem + umidade + faixas + zonas caminhaveis + poligonal penalizada (en)** | 3.0 s | compr_m = 17068; tempo_h = 15.79; ganho_m = 940; fracao_por_classe = 1 = 0.844; 2 = 0.087; 3 = 0.046; 4 = 0.014; 5 = 0.009; zonas = 1; drenagem = Drenagem extraida do MDE: limiar 0.50 km2, 1,407 km de rede em 1,508 km2, densidade 0.93 km/km2.; Travessia de cursos d'agua por classe de bacia (celulas): headwater stream (< 2 km²) = 6,175; stream (2–10 km²) = 3,747; small river — fording depends on the season = 1,819;… |
| **CE-B rota entre os extremos do trajeto GPS real (90 m de pixel)** | 0.3 s | 90m = rota_no_buffer_da_trilha = 0.431; trilha_no_buffer_da_rota = 0.335; 250m = rota_no_buffer_da_trilha = 0.991; trilha_no_buffer_da_rota = 0.965; comprimento_rota_m = 6785.6; comprimento_trilha_m = 14255.6 |
| **CE-C destino fora do MDE (GPS ate Sobral) da erro claro** | 0.2 s | ponto = -40.3427383333333; -3.68390666666667; erro = Exception: O ponto final (350880, 9.5927e+06) esta fora da extensao do MDE (x 245481 a 288101, y 9.62258e+06 a 9.65799e+06, no CRS de trabalho). Confira o CRS dos pontos: coordenadas digitadas sao lid |
| **HI-A Himalaia sintetico: rota em relevo extremo, VRM, legenda em chines** | 20.4 s | compr_m = 116811; tempo_h = 100.7; alt_max_m = 7460; fracao_por_classe = 1 = 0.026; 2 = 0.054; 3 = 0.138; 4 = 0.302; 5 = 0.479; zonas = 1340; crs = DEM reprojetado para CRS de trabalho metrico: EPSG:32645. |
| **HI-B MDE em pes (unidade vertical) reproduz a rota em metros** | 19.4 s | compr_m = 116811; compr_metros = 116811 |
| **HI-C Nepal: rasters proprios em graus (fr)** | 20.7 s | compr_m = 96211; conversao = Declividade do raster de entrada em graus (sera convertida para porcentagem) |
| **EX-1 latitude 86 N: roda e avisa que a UTM esta fora do dominio** | 2.1 s | aviso = AVISO: O MDE esta acima de 84 graus de latitude, fora do dominio da UTM; a distorcao da zona escolhida pode ser grande. Prefira um CRS polar.; compr_m = 48595 |
| **EX-2 MDE em Web Mercator e reprojetado para UTM (rota igual a do MDE geografico)** | 1.1 s | aviso = AVISO: O CRS do MDE (EPSG:3857) nao mede em metros -- projecao Mercator_1SP (escala varia com a latitude). DEM reprojetado para CRS de trabalho metrico: EPSG:32723.; compr_m = 5535; compr_ref = 5707 |
| **EX-3 camada de restricao em memoria (sem arquivo)** | 2.4 s | log = Camada de restricao: 1 feicoes, buffer de 30 m, 2,297 celulas atingidas (0.97% da grade). |

## Leituras

**Mantiqueira.** A rota de Tobler passa a 10, 10 e 18 m dos três cumes marcados pelo caminhante e 81 % dela fica a 250 m da trilha real (58 % a 100 m) — a trilha GPS tem 21,7 km porque inclui os desvios de acampamento e água; a rota tem 13,8 km e 7,7 h de caminhada contínua. Com os cumes embaralhados, o Held-Karp recupera a ordem (custo −32,5 %) e o comprimento fica a 1,1 % do caso ordenado. A restrição 'evitar' sobre a faixa de 40 m da trilha real tira a rota completamente da trilha, como pedido.

**Ceará.** Pixel de 90 m e relevo baixo: 84 % da área em classe 1. A rota entre os extremos do trajeto GPS real fica 99 % a 250 m dele. A drenagem extraída (1.407 km, 0,93 km/km²) e a poligonal do parque (13,4 % da área, encarecida 8×) entram sem erro. O ponto do GPS esquecido ligado até Sobral dá a mensagem certa.

**Himalaia.** 78 % da área em classes 4–5, ainda assim a rota existe (117 km, 101 h — o número é o que se espera do Tobler em 78 % de terreno escarpado). Pés e metros dão a mesma rota.

## O que a bateria encontrou e foi corrigido antes da 1.0.0

Ao percorrer a janela como um usuário (não só o algoritmo), com **os padrões da interface**, a travessia Marins → Marinzinho → Itaguaré **falhava**: 'não foi possível conectar'. Causa: com 'cursos d'água' marcado, a drenagem entrava como **barreira absoluta** (modo 'evitar', faixa de 30 m). Um rio é uma linha — toda rota de um vale ao vizinho tem de cruzar um — e uma rede linear virada parede retalha a paisagem em ilhas. Correção (1.0.0): para a **rota**, a drenagem é sempre custo (8×), cruzável; para as **zonas**, continua excluída no modo 'evitar'; a camada de restrição do usuário segue o modo escolhido (cerca é cerca). Teste de regressão adicionado; a mensagem de 'sem caminho' agora lista as causas prováveis. Depois disso, a janela completa roda a travessia nos seis idiomas e carrega as seis camadas no projeto.

## 1.1.0 — travessias graduadas

Depois da 1.0.0, a regra "drenagem sempre custa 8×" foi refinada: nem todo curso d'água é intransponível, e muitas trilhas atravessam rios rasos ou por pedras. A rota passou a pagar um custo que cresce com o **tamanho do curso**, medido pela área de contribuição do canal — o proxy que a geometria hidráulica oferece (Leopold & Maddock 1953; Faustini et al. 2009): córrego < 2 km² → 2×, riacho 2–10 km² → 4×, rio pequeno até o teto → 8×, acima do teto vadeável (padrão 50 km², parâmetro do usuário) → barreira. **Cada travessia sai num arquivo próprio** (`_travessias.gpkg`) com área, classe, fator e aviso de conferência em campo.

Na travessia Marins → Itaguaré com os padrões da janela, a rota cruza 1–3 cursos, todos córregos/riachos de 1,5–3,7 km²; com o teto em 3 km² ela troca a travessia de um riacho de 3,7 km² por um córrego de 1,5 km²; com o teto em 0,5 km² (nada vadeável) ela não existe e o erro cita o teto. Bateria: 15/15 (caso MQ-A2 novo).
