# Guia do usuário — TopoTrail

Para a versão **1.3.0**. Tudo o que segue foi conferido contra o plugin como ele
é publicado: a janela, o algoritmo de Processing e as mensagens que ele de fato
emite.

## O que é

O TopoTrail é um plugin do QGIS para planejamento técnico de trilhas, acessos e
deslocamento de campo em áreas naturais e unidades de conservação. Ele responde a
uma pergunta — *o que o relevo permite?* — a partir de um único Modelo Digital de
Elevação, e deixa registrado como chegou lá.

Ele tem duas formas, que fazem a mesma coisa:

* uma **janela em quatro etapas**, para quem não conhece o modelo;
* um **algoritmo de Processing**, `topotrail:topotrail`, com todos os 45
  parâmetros expostos, para roteirizar ou colocar num modelo.

## Requisitos

* QGIS **3.22** ou superior, até o QGIS 4.
* Nada a instalar. GDAL/OGR, NumPy e SciPy já vêm com o QGIS, e o plugin não usa
  mais nada.
* Um MDE com sistema de referência definido. Qualquer CRS serve — um CRS
  geográfico é reprojetado automaticamente para a zona UTM local —, mas o CRS
  precisa estar *declarado*. Um raster sem CRS é recusado, e a correção é na
  origem do dado.

## O que você precisa fornecer, e o que não precisa

**Obrigatório**

* Um Modelo Digital de Elevação. **Só isso.** Declividade, as duas curvaturas,
  rugosidade, índice de umidade e a rede de drenagem são todos derivados dele.

**Opcional**

* Seus próprios rasters de declividade e curvatura, se preferir controlar como
  são derivados. Marque *Já tenho rasters de declividade e curvatura* na etapa 1;
  você passa então a ter de declarar a unidade da declividade (porcentagem ou
  graus) e a aceitar que grades diferentes da do MDE sejam reamostradas sobre
  ela, o que suaviza extremos locais. Deixar desmarcado é a recomendação, e é o
  padrão.
* Qualquer raster como critério adicional ponderado — pedregosidade, cobertura
  vegetal, uma superfície de custo pronta — com o sentido declarado: valores
  altos bons, ou valores altos ruins.
* Uma camada vetorial da qual se afastar: uma cerca, uma área vedada, uma
  propriedade privada. Ou excluída de vez, ou apenas encarecida.
* Origem e destino da rota, mais uma camada de pontos com destinos
  intermediários, na ordem de visita.

Se o seu MDE estiver em **pés** — ainda comum nos Estados Unidos —, diga isso na
unidade vertical do MDE. Lido como metros, uma cena do Colorado é inteiramente
descartada e a execução falha com uma mensagem que nunca menciona altitude.

## Os sete produtos

Os dois primeiros saem sempre. Os demais são marcados na etapa 2.

| Produto | Arquivo | O que é |
|---|---|---|
| Adequabilidade topográfica | `…_adequabilidade.tif` | 0 a 1 por célula, a combinação ponderada dos critérios da etapa 3. |
| Risco topográfico relativo | `…_risco_topografico.tif` | 0 a 1 por célula, indicador próprio de dificuldade relativa — não é o complemento da adequabilidade. |
| Classes de transitabilidade | `…_transitabilidade.tif` | Cinco classes absolutas de declividade, com as cores e a legenda gravadas no arquivo, no idioma da execução. |
| Zonas de acesso potencial | `….gpkg` / `.shp` / `.kml` | Polígonos com `value`, `area_m2`, `area_ha`. |
| Rota sugerida | `…_rota.gpkg` | `compr_m`, `tempo_h`, `tempo_hms`, `tempo_campo_h`, `ganho_m`, `perda_m`, altitudes, número de trechos. |
| Corredor de acesso | `…_corredor.gpkg` | Buffer da rota; `buffer_m` é o **raio**. |
| Travessias de cursos d'água | `…_travessias.gpkg` | Um ponto por travessia: área de bacia, classe, fator de custo, aviso de conferência em campo. |

Mais o `…_diagnostico_topotrail.log`: um registro JSON por etapa, com a versão do
plugin, as versões do Python, do GDAL e do sistema operacional, cada parâmetro
como foi resolvido e as estatísticas de cada raster intermediário. **Anexe-o a
qualquer relato de problema**, e guarde-o ao lado de qualquer figura que você
publicar — é o que permite a outra pessoa reproduzir a execução.

## Usando a janela

Abra **TopoTrail** pela barra de ferramentas ou pelo menu `TopoTrail`. A janela é
um assistente de quatro etapas: *Dados → Produtos → Critérios → Executar*.

### Etapa 1 — Dados

Escolha o MDE. Uma etiqueta ao lado do arquivo diz se ele tem CRS e em que
unidades está. A unidade vertical do MDE (metros ou pés) fica aqui, e o cartão
*Seus próprios rasters* descrito acima também, desmarcado por padrão.

### Etapa 2 — Produtos

Adequabilidade e risco saem sempre. Outros quatro são opcionais:

* **zonas de acesso potencial**, as melhores áreas como polígonos, para recorte e
  medição de área;
* **o mapa de transitabilidade**, o mapa do "onde dá para andar";
* **cursos d'água extraídos do MDE**, que habilita as travessias graduadas e é o
  que faz a camada de travessias existir. Atenção em paisagem sazonalmente seca:
  ali o leito seco costuma ser a melhor superfície de caminhada;
* **a rota**, com o seu corredor.

Para a rota, informe origem e destino — por arquivo, digitando X, Y no CRS do
projeto, ou clicando no mapa — e, se quiser, uma camada de pontos com destinos
intermediários. **A ordem das feições é a ordem da travessia**, ou você pode
deixar o plugin escolher a ordem mais barata, exatamente, para até oito pontos.

Destinos intermediários são a forma de encadear objetivos: subir um cume, depois
outro, passar numa nascente. Sem eles o algoritmo contorna a parte alta — e faz
certo, porque passar por cima de um cume não é o jeito mais barato de passar por
ele.

### Etapa 3 — Critérios e limites

**Os padrões são pontos de partida conservadores, não valores calibrados, e a
janela diz isso.** Ajuste-os ao seu terreno e informe os que usou.

* **Pesos** dos seis critérios. Zero desliga o critério. A altitude é zero de
  propósito: ela entra como *faixa*, não como preferência, e qualquer peso acima
  de zero significa "quanto mais alto, melhor para uma trilha". Umidade e
  rugosidade também são zero por padrão, para que resultados existentes não se
  movam sem que ninguém peça; a umidade exige a drenagem do MDE ligada.
* **Limites do terreno**: a faixa altimétrica, a declividade máxima admitida
  (acima dela a célula é inutilizável — 100% são 45°) e a declividade em que a
  nota de declividade chega a zero. Se a maior parte da sua área ultrapassa essa
  última, o critério deixa de distinguir uma encosta de outra, e o plugin avisa
  quando isso acontece.
* **Como cortar as zonas**: o percentil de corte (75 mantém o melhor quarto da
  área; menor é mais permissivo), a área mínima de fragmento e se o percentil é
  tomado dentro de cada faixa altimétrica — o que vem ligado, e impede que uma
  cena alta selecione só os seus fundos de vale.
* **Os limiares de transitabilidade**: quatro porcentagens crescentes separando
  as cinco classes; 20, 35, 60 e 100 por padrão.
* **A rota**: o modelo de custo, o raio do corredor e a margem lateral de busca.
  Margem pequena demais força uma rota reta; grande demais deixa o cálculo lento.
* **Restrições** e o **critério adicional**, ambos opcionais.

A faixa altimétrica merece uma segunda olhada fora da Serra da Mantiqueira, para
a qual os padrões de 0 a 2.600 m foram escritos. Em outros lugares eles apagam a
área de estudo em silêncio: 52% de uma cena alpina, 85% de uma andina, 87% de uma
himalaia. O plugin informa quanto descartou, em que direção, e qual é a faixa real
do MDE — leia essa linha.

### Etapa 4 — Revisar e executar

Escolha o arquivo de saída e o formato vetorial, confira o resumo do que será
produzido e execute. O cálculo roda em segundo plano e o QGIS continua usável; o
painel de progresso mostra as mensagens à medida que saem. Os resultados são
carregados no projeto, já estilizados.

## Lendo a rota

A rota traz **duas durações para a mesma linha**. `tempo_h` é o ritmo de Tobler —
um caminhante sem carga sobre trilha existente, máximo de 6 km/h numa descida
suave. `tempo_campo_h` é a mesma rota reescalada para 2,4 km/h, o ritmo mediano
medido em trajetos de levantamento com marcação de tempo. O traçado é idêntico
nos dois casos: a velocidade máxima altera a duração, não o alinhamento. Nenhuma
das duas é previsão de horário.

`ganho_m` e `perda_m` são a subida e a descida acumuladas ao longo da linha;
`desnivel_max_m` é a grandeza antiga, a amplitude até o ponto mais alto, mantida
porque não é a mesma coisa.

Comprimentos de rota carregam um viés conhecido de até 8,2%, por o roteamento
usar vizinhança de oito células, e diferenças dessa ordem entre dois traçados não
são interpretáveis como diferença de terreno.

## Usando por script

```python
import processing

processing.run("topotrail:topotrail", {
    "INPUT_DEM": "/caminho/para/mde.tif",
    "DERIVE_FROM_DEM": True,
    "START_POINT_FILE": "/caminho/para/origem.geojson",
    "END_POINT_FILE": "/caminho/para/destino.geojson",
    "ROUTE_COST_MODEL": 2,          # 2 = tempo de caminhada (Tobler), o padrao
    "STREAMS_FROM_DEM": True,       # desligado por padrao; necessario p/ travessias
    "OUTPUT_FILE": "/caminho/para/saida.gpkg",
    "OUTPUT_FORMAT": 1,             # 1 = GeoPackage
    # …
})
```

Dois detalhes que não são óbvios: `START_POINT_FILE` e `END_POINT_FILE` são
**caminhos de arquivo**, não camadas, e `ROUTE_COST_MODEL` é um enum cujo padrão,
2, é o de Tobler.

Uma chamada completa e executável, com **os 45 parâmetros escritos por extenso e
comentados**, um MDE pequeno para rodá-la e os valores de saída para conferência,
está em [`../../exemplo/`](../../exemplo/README.md).

## Erros comuns, e o que eles querem dizer

| Mensagem | O que fazer |
|---|---|
| *Este raster não tem CRS definido* | Atribua o sistema de coordenadas na origem do dado. O modo estrito interrompe de propósito. |
| *Uma rota precisa de origem e destino* | Falta um dos dois pontos. |
| *Você marcou que vai usar rasters próprios…* | Desmarque a caixa, ou forneça declividade **e** as duas curvaturas. |
| *Pelo menos um peso precisa ser maior que zero* | Os seis pesos estão em zero; não há o que combinar. |
| *Os limiares de transitabilidade precisam ser quatro números crescentes* | Quatro valores, crescentes, separados por vírgula. |
| *A altitude mínima precisa ser menor que a máxima* | A faixa altimétrica está invertida. |
| *Nenhum pixel navegável atende às restrições de rota* | A declividade máxima está excluindo tudo entre os dois pontos. Aumente-a. |
| *Não foi possível conectar os pontos da rota* | Não existe caminho de células viáveis. A mensagem lista as quatro causas usuais e o ajuste de cada uma: aumentar a declividade máxima, trocar a restrição para "encarecer", elevar o teto vadeável ou ampliar a margem. |
| *Os dois pontos só se ligam por um contato de vértice* | Problema diferente, e aumentar a declividade não resolve: em algum lugar do caminho duas células intransponíveis se tocam na diagonal e a passagem fica com largura zero. Reduza a área mínima de fragmento, amplie o afastamento da restrição, ou use um MDE de maior resolução. |
| *O MDE tem N células; derivar o relevo exigiria cerca de X GB* | Recorte o MDE para a área de interesse, ou reamostre para uma célula maior. |
| O arquivo de saída não pode ser gravado | O arquivo está aberto no QGIS, ou a pasta não permite escrita. |

O plugin também emite avisos que não são erros e que vale ler: células
descartadas pela faixa altimétrica, a fração da cena em que os pesos precisaram
ser renormalizados, célula grande demais para as classes de transitabilidade, um
raster de critério com sentinela de NoData não declarada, e a cena ter perdido
poder de discriminação.

## Limites do que o resultado significa

* O resultado depende diretamente da qualidade, da resolução e da data do MDE.
  Sobre floresta, a maioria dos MDEs globais dá o dossel, não o solo.
* A distribuição das classes do mapa de transitabilidade depende fortemente do
  tamanho da célula. Informe o tamanho da célula ao lado de qualquer número
  tirado dele.
* O raster de risco é relativo **à cena analisada**. Não é mapa absoluto de
  perigo, e os valores de duas cenas não se comparam.
* Os pesos, o limite de declividade e o percentil de corte são juízo seu, e a
  rota depende apreciavelmente deles. Informe os valores usados — o registro de
  diagnóstico traz todos.
* O plugin não conhece vegetação, estradas, trilhas existentes, pastos,
  propriedade nem restrição legal, e a única hidrografia que ele conhece é a que
  deriva do MDE. Cruze estas saídas com essas camadas no QGIS.
* Uma rota sugerida é uma hipótese topográfica. Deve ser avaliada por quem
  conhece o terreno, e percorrida, antes de uso operacional.
* Toda travessia de curso d'água é estimada só pelo relevo. Profundidade e
  corrente mudam com a estação e a chuva: confira em campo.

## Para onde ir depois

* [`METODOLOGIA_TOPOtrail_pt_BR.md`](METODOLOGIA_TOPOtrail_pt_BR.md) — fórmulas,
  constantes nomeadas, regras de normalização.
* [`AUDITORIA_METODOLOGICA_pt_BR.md`](AUDITORIA_METODOLOGICA_pt_BR.md) — revisão
  crítica dessas escolhas, inclusive onde são frágeis. Audita a versão 0.5.0 e é
  mantida como registro datado; a seção final dela diz o que mudou desde então.
* [`../VALIDACAO.md`](../VALIDACAO.md) — o que os trajetos de GPS de campo
  disseram sobre as constantes empíricas, inclusive onde contrariaram o plugin.
* [`../../exemplo/README.md`](../../exemplo/README.md) — um exemplo pronto para
  rodar e conferir.
