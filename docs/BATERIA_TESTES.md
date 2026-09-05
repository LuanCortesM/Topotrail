# TopoTrail — bateria de testes de ponta a ponta (1.0.0)

Corrida em QGIS 3.34 headless, plugin instalado como o usuário instala, sem geopandas/shapely. Três regiões de relevo muito diferente e casos de robustez; cada caso tem critério de aprovação automático. Script: `validation/bateria_regioes.py`.

| Região | Dado | Por quê |
|---|---|---|
| Serra da Mantiqueira — Marins × Itaguaré | MDE real de 1″ (carta 22S465, IBGE/derivado), 600–2401 m; trilha GPS real da travessia, com Pico do Marins, Marinzinho e Itaguaré marcados pelo caminhante; rasters de declividade e curvatura da própria carta | O caso de uso da dissertação: montanha, três destinos, comparação com trilha real |
| Ceará — P. E. das Carnaúbas | Copernicus GLO-90 real, 10–915 m; trajetos GPS de campo; poligonal do parque | Relevo baixo e seco, pixel de 90 m, drenagem e umidade importam, restrição por polígono |
| Himalaia | MDE sintético com a estatística do Everest (3200–8848 m, 90 m). O download do tile Copernicus real é bloqueado neste ambiente. | Regime extremo de declividade: o que acontece quando quase tudo é classe 4–5 |
| Extras | Latitude 86° N; MDE em Web Mercator; camada de restrição em memória | Limites da UTM, CRS não métrico, camada sem arquivo |

## Resultado: 14 de 14 casos aprovados

| Caso | Tempo | Critério | Resultado |
|---|---|---|---|
| **MQ-A travessia completa (3 cumes, 6 produtos)** | 6.2 s | rota passa a < 60 m dos 3 cumes, na ordem; 4 trechos; > 50 % da rota a 250 m da trilha real; zonas geradas | trechos = 4; tempo_h = 7.69; compr_m = 13828; ganho_m = 809; distancia_aos_cumes_m = Marins = 10.3; Marinzinho = 9.7; Itaguare = 18.3; concordancia_com_trilha_real = 100m = rota_no_buffer_da_trilha = 0.575; trilha_no_buffer_da_rota = 0.614; 250m = rota_no_buffer_da_trilha = 0.808; trilha_no_buffer_da_rota = 0.888; comprimento_rota_m = 13827.6; comprimento_trilha_m = 21664.8; classes_transitabilidade = 1 = 23609; 2 = 72898; 3 = 91939; 4 = 34210; 5 = 12966; zonas = 164 |
| **MQ-B cumes embaralhados + Held-Karp recupera a ordem** | 42.0 s | cumes embaralhados + Held-Karp → comprimento a < 2 % do caso A | compr_m = 13679; diferenca_relativa = 0.0108 |
| **MQ-C rasters proprios da carta vs derivados; Shapefile em EPSG:31983** | 3.1 s | notas com rasters da carta vs derivadas: r > 0,8; Shapefile com .prj em EPSG:31983 | correlacao_das_notas = 0.841 |
| **MQ-D restricao 'evitar' sobre a trilha real; KML; legenda em japones** | 4.3 s | 0 % da rota dentro da faixa proibida de 40 m; KML em 4326; legenda japonesa no GeoTIFF | rota_dentro_da_faixa_proibida = 0.0 |
| **MQ-E tres modelos de custo + restricao 'penalizar'** | — s | inverso, exponencial e Tobler rodam; só Tobler dá tempo em horas | inverso = 4899, None; exponencial = 5151, None; tobler = 5651, 3.736120688825416 |
| **CE-A Carnaubas: drenagem + umidade + faixas + zonas caminhaveis + poligonal penalizada (en)** | 4.0 s | rota + zonas caminháveis; drenagem extraída; poligonal encarecida 8×; legenda inglesa | compr_m = 16899; tempo_h = 15.93; ganho_m = 879; fracao_por_classe = 1 = 0.844; 2 = 0.094; 3 = 0.046; 4 = 0.014; 5 = 0.003; zonas = 1 |
| **CE-B rota entre os extremos do trajeto GPS real (90 m de pixel)** | 0.4 s | > 30 % da rota a 250 m do trajeto GPS real | 90m = rota_no_buffer_da_trilha = 0.431; trilha_no_buffer_da_rota = 0.335; 250m = rota_no_buffer_da_trilha = 0.991; trilha_no_buffer_da_rota = 0.965; comprimento_rota_m = 6785.6; comprimento_trilha_m = 14255.6 |
| **CE-C destino fora do MDE (GPS ate Sobral) da erro claro** | 0.3 s | destino fora do MDE → erro que diz 'fora da extensão' e dá o CRS | erro = Exception: O ponto final (350880, 9.5927e+06) esta fora da extensao do MDE (x 245481 a 288101, y 9.62258e+06 a 9.65799e+06, no CRS de trabalho). Confira o CRS dos pontos: coordenadas digitadas sao lid |
| **HI-A Himalaia sintetico: rota em relevo extremo, VRM, legenda em chines** | 30.0 s | rota existe; classes 4+5 > 30 %; legenda chinesa | compr_m = 116811; tempo_h = 100.7; alt_max_m = 7460; fracao_por_classe = 1 = 0.026; 2 = 0.054; 3 = 0.138; 4 = 0.302; 5 = 0.479; zonas = 1340 |
| **HI-B MDE em pes (unidade vertical) reproduz a rota em metros** | 29.5 s | MDE em pés reproduz a rota em metros (< 1 %) | compr_m = 116811; compr_metros = 116811 |
| **HI-C Nepal: rasters proprios em graus (fr)** | 33.2 s | rasters próprios em graus convertidos; legenda francesa | compr_m = 96211 |
| **EX-1 latitude 86 N: roda e avisa que a UTM esta fora do dominio** | 3.3 s | roda e avisa que está acima de 84° (UTM indefinida) | aviso = AVISO: O MDE esta acima de 84 graus de latitude, fora do dominio da UTM; a distorcao da zona escolhida pode ser grande. Prefira um CRS polar.; compr_m = 48595 |
| **EX-2 MDE em Web Mercator e reprojetado para UTM (rota igual a do MDE geografico)** | 1.4 s | aviso de Mercator; reprojeta; rota a < 5 % da referência | aviso = AVISO: O CRS do MDE (EPSG:3857) nao mede em metros -- projecao Mercator_1SP (escala varia com a latitude). DEM reprojetado para CRS de trabalho metrico: EPSG:32723.; compr_m = 5535; compr_ref = 5707 |
| **EX-3 camada de restricao em memoria (sem arquivo)** | 3.7 s | camada de memória rasterizada |  |

## Leituras

**Mantiqueira.** A rota de Tobler passa a 10, 10 e 18 m dos três cumes marcados pelo caminhante e 81 % dela fica a 250 m da trilha real (58 % a 100 m) — a trilha GPS tem 21,7 km porque inclui os desvios de acampamento e água; a rota tem 13,8 km e 7,7 h de caminhada contínua. Com os cumes embaralhados, o Held-Karp recupera a ordem (custo −32,5 %) e o comprimento fica a 1,1 % do caso ordenado. A restrição 'evitar' sobre a faixa de 40 m da trilha real tira a rota completamente da trilha, como pedido.

**Ceará.** Pixel de 90 m e relevo baixo: 84 % da área em classe 1. A rota entre os extremos do trajeto GPS real fica 99 % a 250 m dele. A drenagem extraída (1.407 km, 0,93 km/km²) e a poligonal do parque (13,4 % da área, encarecida 8×) entram sem erro. O ponto do GPS esquecido ligado até Sobral dá a mensagem certa.

**Himalaia.** 78 % da área em classes 4–5, ainda assim a rota existe (117 km, 101 h — o número é o que se espera do Tobler em 78 % de terreno escarpado). Pés e metros dão a mesma rota.

## O que a bateria encontrou e foi corrigido antes da 1.0.0

Ao percorrer a janela como um usuário (não só o algoritmo), com **os padrões da interface**, a travessia Marins → Marinzinho → Itaguaré **falhava**: 'não foi possível conectar'. Causa: com 'cursos d'água' marcado, a drenagem entrava como **barreira absoluta** (modo 'evitar', faixa de 30 m). Um rio é uma linha — toda rota de um vale ao vizinho tem de cruzar um — e uma rede linear virada parede retalha a paisagem em ilhas. Correção (1.0.0): para a **rota**, a drenagem é sempre custo (8×), cruzável; para as **zonas**, continua excluída no modo 'evitar'; a camada de restrição do usuário segue o modo escolhido (cerca é cerca). Teste de regressão adicionado; a mensagem de 'sem caminho' agora lista as causas prováveis. Depois disso, a janela completa roda a travessia nos seis idiomas e carrega as seis camadas no projeto.
