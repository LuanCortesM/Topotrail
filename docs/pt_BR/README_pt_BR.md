# TopoTrail

**Um plugin do QGIS para planejamento preliminar de trilhas, acessos e
deslocamento de campo em áreas naturais e unidades de conservação — a partir de
um único MDE.**

Dê ao TopoTrail um Modelo Digital de Elevação e ele deriva declividade,
curvaturas, rugosidade, umidade e a própria rede de drenagem, e então produz sete
produtos numa execução só:

- um raster contínuo de **adequabilidade topográfica** e o seu complemento, um
  raster de **risco topográfico relativo**;
- um **mapa de transitabilidade** em cinco classes absolutas de declividade, com
  significado em campo e com a legenda gravada no próprio GeoTIFF;
- **zonas de acesso potencial** como polígonos, com área;
- uma **rota sugerida** entre origem e destino — opcionalmente passando por
  vários destinos intermediários, na ordem informada ou na ordem ótima exata —,
  custeada como **tempo de caminhada** (função anisotrópica de Tobler, validada
  contra 224 km de trajetos de GPS de campo);
- um **corredor de acesso** em torno dessa rota;
- as **travessias de cursos d'água** que a rota faz, um ponto para cada uma, com
  o porte do curso e um aviso de conferência em campo.

A versão 1.x instala sem nada para `pip install`, roda do QGIS 3.22 ao QGIS 4 e
funciona em qualquer lugar: o CRS de trabalho é escolhido automaticamente, os
padrões foram calibrados contra trilhas reais, e cada constante está documentada
com a sua evidência.

> Esta é a cópia de referência em português. O [README em inglês](../../README.md)
> é a documentação primária e está mais completa.

A interface e os parâmetros do Processing estão disponíveis em seis idiomas —
português, inglês, espanhol, francês, chinês simplificado e japonês —,
escolhidos num seletor da janela; português e inglês são revisados, os outros
quatro são rascunhos da comunidade. O registro de execução no painel do
Processing e o arquivo `.log` de diagnóstico estão apenas em português.

---

## Sumário

- [Para quem é](#para-quem-é)
- [Como se relaciona com as ferramentas existentes](#como-se-relaciona-com-as-ferramentas-existentes)
- [Instalação](#instalação)
- [Primeiros passos](#primeiros-passos)
- [Entradas e saídas](#entradas-e-saídas)
- [O mapa de transitabilidade](#o-mapa-de-transitabilidade)
- [Como o modelo funciona](#como-o-modelo-funciona)
- [Limitações metodológicas](#limitações-metodológicas)
- [Leitura cartográfica](#leitura-cartográfica)
- [Documentação](#documentação)
- [Suporte](#suporte)
- [Como citar](#como-citar)
- [Créditos](#créditos)
- [Changelog](#changelog)

---

## Para quem é

Equipes de unidades de conservação, pesquisadores de campo e equipes técnicas que
precisam planejar como chegar a um ponto em terreno montanhoso, ou por onde uma
trilha nova poderia plausivelmente passar, **antes** de uma expedição — e que
trabalham no QGIS, não num ambiente de programação.

O problema concreto: em relevo acidentado, decidir um trajeto significa pesar
declividade, altitude e forma do terreno ao mesmo tempo, sobre uma área grande
demais para inspecionar a olho. Fazer isso no QGIS à mão significa encadear
expressões da calculadora raster, reclassificações e execuções de custo-distância,
e repetir a cadeia inteira sempre que um limiar muda. Cada execução é difícil de
documentar e mais difícil ainda de reproduzir, de modo que o raciocínio por trás
de um trajeto escolhido raramente sobrevive até o relatório.

O TopoTrail empacota essa cadeia numa única operação parametrizada e registrada.
Toda execução grava um registro de diagnóstico com a versão do plugin, as versões
das suas dependências, cada parâmetro e as estatísticas de distribuição de cada
raster intermediário — de modo que uma rota apresentada num relatório possa ser
rastreada até a análise que a produziu.

**O que o TopoTrail deliberadamente não faz:** ele não detecta estradas, pastos,
trilhas existentes, uso do solo, propriedade nem restrições legais, e a única
hidrografia que conhece é a que deriva do MDE. Essas são camadas complementares
para sobrepor no QGIS quando o objetivo do planejamento exigir uma análise
territorial mais ampla. Uma área visualmente aberta pode não aparecer como zona
potencial se o relevo naquele pixel for penalizado.

## Como se relaciona com as ferramentas existentes

Caminho de menor custo sobre superfícies raster é um campo maduro, e o TopoTrail
não tenta substituir as implementações de uso geral:

| Ferramenta | O que faz | Por que o TopoTrail existe ao lado dela |
|---|---|---|
| GRASS `r.walk` / `r.drain` | Custo de caminhada anisotrópico com funções do tipo Langmuir/Tobler, expostas no QGIS pelo provedor GRASS | Mais rigoroso como modelo de deslocamento, mas recebe uma superfície de custo **já pronta** e não opina sobre como derivar adequabilidade topográfica de um MDE. A contribuição do TopoTrail é a etapa multicritério *a montante*, e a documentação dela. |
| GRASS `r.cost`, caminho de menor custo do SAGA | Custo acumulado isotrópico a partir de um raster de custo fornecido | O mesmo: a superfície de custo é problema do usuário. |
| Plugins de Least-Cost Path do QGIS | Rota entre pontos sobre um raster de custo | Só a rota; sem modelo de adequabilidade, sem zonas, sem corredor, sem registro de proveniência. |
| `leastcostpath` / `gdistance` (R) | Modelagem de deslocamento rica, inclusive anisotropia | Exige R e um fluxo de trabalho roteirizado; o usuário-alvo aqui trabalha dentro do QGIS. |

A busca de rota padrão do TopoTrail é **anisotrópica**: no modelo de custo por
tempo de caminhada, o custo do passo vem da função de Tobler, então subir 100 m e
descer os mesmos 100 m não custam o mesmo. Dois modelos isotrópicos continuam
disponíveis para comparação. Onde um modelo fisiológico de caminhada importa mais
que o modelo de adequabilidade, o `r.walk` é a ferramenta melhor — e o raster de
adequabilidade do TopoTrail pode ser entregue a ele como superfície de custo.

## Instalação

### Pelo repositório de plugins do QGIS (recomendado)

1. No QGIS, abra `Complementos > Gerenciar e Instalar Complementos`.
2. Procure por **TopoTrail**.
3. Instale e ative.

### A partir de um ZIP

Baixe o ZIP de uma versão na
[página de releases](https://github.com/LuanCortesM/Topotrail/releases) e use
`Complementos > Gerenciar e Instalar Complementos > Instalar a partir do ZIP`.

### Requisitos

- QGIS **3.22** ou superior (QGIS 4 / Qt6 suportado).
- Os rasters de entrada precisam ter CRS definido.

É só isso. O TopoTrail usa apenas o que toda instalação do QGIS já traz —
**GDAL/OGR, NumPy e SciPy** —, então não há nada para `pip install` no Windows,
no Linux ou no macOS. (`requirements.txt` documenta os pisos de versão dessas
bibliotecas empacotadas, para referência; não é um alvo de instalação.)

## Primeiros passos

1. Prepare um **MDE** da sua área de interesse. Qualquer CRS serve — MDEs
   geográficos são reprojetados automaticamente para a zona UTM local; um CRS
   projetado em metros é mantido.
2. Abra o **TopoTrail** pela barra de ferramentas ou pelo menu `TopoTrail`. A
   janela é um assistente de quatro etapas: *Dados → Produtos → Critérios →
   Executar*.
3. **Dados**: escolha o MDE. Declividade e curvaturas são derivadas dele; só
   marque *rasters próprios* se tiver um motivo para fornecê-los.
4. **Produtos**: adequabilidade e risco saem sempre; marque as zonas, o mapa de
   transitabilidade, os cursos d'água e a rota conforme a necessidade. Para a
   rota, informe origem e destino por arquivo, por coordenadas no CRS do projeto
   ou clicando no mapa — e, se quiser, uma camada de pontos com destinos
   intermediários.
5. **Critérios**: os padrões são pontos de partida conservadores. Confira a faixa
   altimétrica da sua área e declare os valores que usar.
6. **Executar**: escolha arquivo e formato de saída. Os resultados são carregados
   no projeto, já estilizados.

O plugin também está disponível como algoritmo de Processing
(`topotrail:topotrail`), então pode ser roteirizado ou colocado num modelo.

**Se você não tem um MDE à mão, comece pelo [`exemplo/`](../../exemplo/README.md).**
Ele traz um MDE sintético pequeno, a origem, o destino e um ponto intermediário,
um script que roda a cadeia inteira em QGIS sem interface com os 52 parâmetros
escritos por extenso, e os valores de saída para comparação — comprimento da
rota, tempo de caminhada, ganho acumulado e número de travessias.

## Entradas e saídas

**Entradas**

- Um Modelo Digital de Elevação. **É o único requisito.**
- Opcionalmente, seus próprios rasters de declividade e curvatura, se preferir
  controlar como são derivados (declare a unidade da declividade; grades
  diferentes da do MDE são alinhadas a ela).
- Opcionalmente, qualquer raster como critério adicional ponderado —
  pedregosidade, cobertura vegetal, uma superfície de custo pronta.
- Opcionalmente, uma camada vetorial da qual se afastar — hidrografia, estradas,
  limites de propriedade, o que for —, excluída de vez ou encarecida.
- Opcionalmente, origem e destino (camadas de pontos, coordenadas no CRS do
  projeto, ou capturados no mapa) e uma camada de destinos intermediários.

**Saídas**

| Produto | Arquivo | Observações |
|---|---|---|
| Adequabilidade topográfica contínua | `…_adequabilidade.tif` | 0 a 1 por célula |
| Risco topográfico relativo | `…_risco_topografico.tif` | 0 a 1 por célula |
| Classes de transitabilidade | `…_transitabilidade.tif` | 5 classes, legenda e cores gravadas no arquivo, no idioma ativo |
| Zonas de acesso potencial | `….gpkg` / `.shp` / `.kml` | polígonos com `area_m2`, `area_ha` |
| Rota sugerida | `…_rota.gpkg` | `compr_m`, `tempo_h` (Tobler), `tempo_campo_h`, altitudes, número de trechos |
| Corredor de acesso | `…_corredor.gpkg` | buffer da rota; `buffer_m` é o raio |
| Travessias de cursos d'água | `…_travessias.gpkg` | um ponto por travessia: área de bacia, classe, fator de custo, aviso |
| Registro de diagnóstico | `…_diagnostico_topotrail.log` | um registro JSON por etapa, para reprodutibilidade |

## O mapa de transitabilidade

O raster de adequabilidade é contínuo e relativo; o vetor de zonas potenciais é
binário e depende de um percentil da cena. Nenhum dos dois responde à pergunta
que um pesquisador de fato faz diante de um mapa, antes de ir a campo: **dá para
andar aqui, ou não?**

O `*_transitabilidade.tif` responde com cinco classes absolutas:

| | classe | declividade | o que o terreno faz |
|---|---|---|---|
| 1 | Suave | < 20% | caminhada comum |
| 2 | Moderada | 20–35% | caminhada em rampa forte |
| 3 | Forte | 35–60% | uso ocasional das mãos |
| 4 | Muito forte | 60–100% | mais escalonamento que caminhada |
| 5 | Escarpada | > 100%, ou bloqueada | um paredão, ou uma restrição no modo "evitar" |

**Os rótulos descrevem a declividade, não um veredito sobre quem passa.** Uma
versão anterior chamava a classe 5 de "intransponível", e 25.113 fixos de GPS
sobre terreno comprovadamente percorrido a pé falsificaram isso: 5,2% e 6,9% dos
fixos das duas campanhas caem na classe 4, e a maior declividade efetivamente
caminhada foi de 115,8%, dentro da classe 5. Os limiares foram mantidos — são
estratos de declividade defensáveis, e a classe 5 é de fato rara em trilhas reais
— mas os rótulos foram reescritos para descrever inclinação, e um teste impede
que a afirmação antiga volte. A tabela completa está em
[`../VALIDACAO.md`](../VALIDACAO.md).

Estes cinco nomes, e só eles, são os que o software usa: vivem em `i18n/*.json`,
nos seis idiomas, e essa é a fonte única. São o que a legenda do raster de saída
diz e o que o registro de diagnóstico anota.

Ser absoluto é o ponto: uma classe tem de significar a mesma coisa na Mantiqueira
e nos Andes, ou dois mapas não se comparam. Os limiares são um parâmetro, e são
decisões empíricas de modelagem como toda constante daqui — declare-os.

Dois modificadores rebaixam a célula uma classe, nunca melhoram e nunca criam
classe 5: **rugosidade** acima do percentil 90 da cena, porque um campo de blocos
e uma encosta lisa na mesma inclinação não são a mesma caminhada; e **umidade**
acima do percentil 95, porque um fundo de vale encharcado a 5% pode ser menos
passável que uma encosta seca a 30%.

A paleta e os rótulos das classes são gravados na saída no idioma ativo, e são
gravados **duas vezes**, de propósito. O GeoTIFF não tem lugar padrão para nomes
de categoria, então o GDAL os grava no `*.tif.aux.xml` ao lado do raster — e é
essa cópia que o QGIS lê para montar a legenda. Os mesmos cinco rótulos vão
também como metadados GDAL, `TOPOTRAIL_CLASSE_1` a `TOPOTRAIL_CLASSE_5`, que
ficam na etiqueta `GDAL_METADATA` **dentro** do `.tif`, junto com a paleta de
cores. Assim o par abre com legenda completa no QGIS, e um `.tif` enviado sozinho
ainda chega com as suas cores e ainda diz o que cada uma significa.

## Como o modelo funciona

O TopoTrail combina restrições booleanas — faixa altimétrica e declividade máxima
— com uma combinação linear ponderada de critérios topográficos. A declividade é
tratada como critério de custo; as curvaturas são pontuadas pela proximidade de
formas menos extremas do relevo.

Antes de qualquer cálculo espacial o plugin prepara um CRS de trabalho projetado
em metros. Se o MDE estiver em CRS geográfico, o centro do raster é usado para
escolher automaticamente a zona UTM adequada. Se o MDE estiver sem CRS, o modo
científico estrito bloqueia o processamento: o CRS tem de ser definido na fonte
do dado.

**A declividade é expressa em porcentagem**, não em graus — 100% correspondem a
45°. As duas curvaturas são a tangencial (horizontal) e a de perfil (vertical),
nas formas de Mitášová & Hofierka (1993). A rugosidade é a Vector Ruggedness
Measure (Sappington et al. 2007), adimensional e desacoplada da declividade, e a
umidade é o índice topográfico `ln(a / tan β)` (Beven & Kirkby 1979).

A adequabilidade topográfica é calculada como:

```text
S = (w_alt·A + w_slope·D + w_curv_h·CH + w_curv_v·CV + w_wet·W + w_rough·R) / Σw
```

onde `S` é a adequabilidade final, `A` é a altitude normalizada, `D` é a
declividade normalizada e invertida, `CH` e `CV` são as notas das curvaturas, e
`W` e `R` são as notas opcionais de umidade e rugosidade (ambas invertidas — mais
seco e mais liso é melhor, ambas com peso zero até que se peça). Pesos negativos
são rejeitados e a soma dos pesos tem de ser maior que zero. **A soma dos pesos é
calculada célula a célula**, para que uma célula não coberta por um critério seja
pontuada só pelos que ela tem, em vez de receber nota zero pela ausência.

> **Sobre o peso da altitude.** Ele vale `0` de propósito. A altitude entra no
> modelo como *restrição* — a faixa altimétrica —, não como preferência. Como a
> altitude normalizada cresce monotonicamente, qualquer peso acima de zero
> significa literalmente "quanto mais alto, melhor para uma trilha", o que
> raramente é a intenção.

O raster de risco topográfico relativo **não** é simplesmente `1 - S`. Ele combina
um termo de declividade com um termo de curvatura, em 0,75 e 0,25, usando a
declividade em relação ao limite máximo e as curvaturas normalizadas por um
percentil robusto. Leia-o como camada complementar de dificuldade topográfica
relativa.

Para planejar trilhas novas, o produto mais direto é o fluxo de planejamento de
acesso: o raster de adequabilidade vira superfície de custo e o plugin procura a
rota de menor custo entre origem e destino. As zonas potenciais são contexto
espacial; a rota e o corredor são os produtos operacionais. Quando o objetivo é
apenas chegar a um ponto, desligar a geração de zonas vetoriais acelera bastante
o processamento.

As fórmulas completas, as constantes empíricas nomeadas e as regras de
normalização estão em
[`METODOLOGIA_TOPOtrail_pt_BR.md`](METODOLOGIA_TOPOtrail_pt_BR.md), e a revisão
crítica dessas escolhas está em
[`AUDITORIA_METODOLOGICA_pt_BR.md`](AUDITORIA_METODOLOGICA_pt_BR.md).

## Limitações metodológicas

- O resultado depende diretamente da qualidade, da resolução e da data do MDE.
- Declividade e curvatura mudam com a resolução espacial.
- Reamostrar declividade e curvatura pode suavizar extremos do terreno; prefira
  derivados já alinhados ao MDE, ou deixe o plugin derivá-los.
- A busca de rota usa vizinhança de oito células, então um trajeto a 22,5° dos
  eixos da grade sai até 8,2% mais longo que a distância que representa. Compare
  comprimentos de rota com essa margem em mente.
- O modelo de custo inverso, `1 / (S + 0,05)`, está disponível mas não é o
  padrão: o contraste que ele aparenta oferecer pressupõe que a adequabilidade
  percorra [0, 1], e numa cena real ela não percorre. Na cena da Mantiqueira os
  percentis 5 e 95 da adequabilidade foram 0,49 e 0,77, de modo que o custo entre
  eles varia por um fator de 1,5 — plano demais para valer o desvio. O modelo
  exponencial, `exp(k(1 − S))`, preserva o contraste independentemente de quão
  comprimida esteja a distribuição. O modelo de tempo de caminhada, que é o
  padrão, tira a maior parte do seu poder de discriminação do termo de gradiente,
  e não da adequabilidade.
- A rede de drenagem é calculada numa grade limitada por responsividade, então um
  canal nunca é mais estreito que essa célula de trabalho.
- A busca de rota fica confinada a um retângulo em torno de origem e destino,
  ampliado pela margem de busca. Um caminho globalmente mais barato que saia desse
  retângulo não é encontrado.
- Algumas constantes de custo, risco e normalização são decisões empíricas de
  modelagem e devem ser declaradas quando os resultados forem publicados.
- Os pesos definidos pelo usuário exigem justificativa metodológica.
- A duração em ritmo de Tobler é estimativa de esforço relativo, não previsão de
  horário: contra GPS de campo ela é otimista por um fator de 1,7 a 3,1.
- Adequabilidade topográfica não substitui validação de campo.
- Vegetação, hidrografia externa, propriedade, restrições legais, estradas,
  trilhas existentes, pastos e restrições ambientais não são considerados.
- KML é formato de visualização; prefira GeoPackage para análise.

## Leitura cartográfica

Use o raster de adequabilidade como camada semitransparente sobre imagem de
satélite ou carta base. As zonas vetoriais são uma generalização do raster acima
do limiar escolhido, e por isso podem ficar fragmentadas quando o filtro de área
mínima é baixo demais. Para mapas de apresentação, aumente a área mínima e
prefira GeoPackage. Para planejamento de acesso em campo, priorize a rota
sugerida e o corredor.

Em montanha alta, mantenha ligado o equilíbrio por faixa altimétrica. Ele impede
que um limiar global único selecione apenas terreno baixo e suave, preservando as
melhores células relativas dentro de cada faixa.

## Documentação

| Documento | Conteúdo |
|---|---|
| [`../../exemplo/README.md`](../../exemplo/README.md) | Um exemplo pronto para rodar: MDE sintético pequeno, três pontos, um script e os valores de saída para conferência |
| [`USUARIO_TOPOtrail_pt_BR.md`](USUARIO_TOPOtrail_pt_BR.md) | Guia do usuário, passo a passo |
| [`METODOLOGIA_TOPOtrail_pt_BR.md`](METODOLOGIA_TOPOtrail_pt_BR.md) | Fórmulas, constantes, normalização |
| [`AUDITORIA_METODOLOGICA_pt_BR.md`](AUDITORIA_METODOLOGICA_pt_BR.md) | Revisão crítica das escolhas de modelagem (auditoria da 0.5, com nota de proveniência) |
| [`../VALIDACAO.md`](../VALIDACAO.md) | O que os trajetos de GPS de campo disseram sobre as constantes empíricas, com a versão do plugin por trás de cada número |
| [`../../tests/README.md`](../../tests/README.md) | As duas suítes de teste, por que são duas e como rodar cada uma |

## Suporte

Abra uma [issue](https://github.com/LuanCortesM/Topotrail/issues). Há modelos
para relato de defeito, dúvida metodológica e pedido de funcionalidade.

Quando alguma coisa falhar, anexe o arquivo `*_diagnostico_topotrail.log` que o
plugin grava ao lado da sua saída. É de longe a coisa mais útil que você pode
enviar.

## Como citar

Cada versão é arquivada no Zenodo. Cite a versão que você usou:

> Maciel, L. S. C. (2026). *TopoTrail: a QGIS plugin for DEM-based topographic
> suitability and least-cost route planning* (versão 1.4.0) [Software]. Zenodo.
> https://doi.org/10.5281/zenodo.23174766

O DOI de conceito
[10.5281/zenodo.20295565](https://doi.org/10.5281/zenodo.20295565) sempre resolve
para a versão arquivada mais recente. Os metadados legíveis por máquina estão em
[`CITATION.cff`](../../CITATION.cff).

## Créditos

**Desenvolvedor:** Luan da Silva Cortes Maciel — citado como MACIEL, L. S. C.

**Orientador:** Leandro Freitas

**Contexto:** desenvolvido como produto da pesquisa de mestrado do autor em
Biodiversidade em Unidades de Conservação, vinculada à Escola Nacional de
Botânica Tropical e ao Instituto de Pesquisas Jardim Botânico do Rio de Janeiro.

**Projeto associado:** Herpeto Mantiqueira.

**Dados de campo:** os trajetos de GPS da caatinga que sustentam a calibração
empírica descrita em [`../VALIDACAO.md`](../VALIDACAO.md) foram registrados por
**Sabrina Barros da Silva** durante o inventário botânico da dissertação dela, a
quem pertencem, e cedidos para análise e teste deste plugin; os da Serra da
Mantiqueira são de campanhas do próprio autor. Nenhum dos dois conjuntos é
redistribuído com o código, por conterem localidades de ocorrência de espécies.

**Contato:** herpetomantiqueira@gmail.com — o endereço do projeto, e não um
pessoal, para que sobreviva a mudanças de instituição.

## Uso de assistência de IA

Parte deste software foi escrita com assistência de um modelo de linguagem
(Claude, Anthropic), usado como ferramenta de programação. Toda alteração foi
revisada, testada e aceita pelo autor, responsável pelas decisões metodológicas e
pela correção do resultado. Nenhum modelo de linguagem consta como autor, e
nenhum componente de IA roda dentro do plugin: nada na cadeia de análise chama um
modelo, exige conexão de rede ou se comporta de forma não determinística.

## Changelog

O changelog completo, versão a versão, está em
[`metadata.txt`](../../metadata.txt) e é o que o repositório de plugins do QGIS
mostra. Em resumo:

- **1.3.0** — Correções vindas de seis auditorias independentes do código e do
  capítulo que o descreve: o passo diagonal do A* passa a exigir passagem por
  fora dele (a rota escapava pelo vértice entre duas células intransponíveis, e
  travessias de drenagem na diagonal saíam de graça e fora da lista); a curvatura
  horizontal passa da curvatura de contorno de Moore et al. para a tangencial de
  Mitášová & Hofierka, que não diverge em terreno plano; gravar a saída num
  GeoPackage existente deixa de apagar o arquivo; e uma série de silêncios do
  plugin passa a ser falada.
- **1.2.0** — Ganho acumulado passa a somar as subidas, e não a amplitude até o
  ponto mais alto; o registro de diagnóstico passa a anotar o modelo de custo
  correto e os sete pesos; teto de memória para MDEs grandes; a caixa de
  ferramentas do Processing passa a abrir no modelo de tempo de caminhada.
- **1.1.x** — Travessias graduadas por área de contribuição, com camada de
  travessias; higiene para os scanners do repositório (Bandit, Flake8, Qt6).
- **1.0.0** — Primeira versão estável, após uma bateria de ponta a ponta em três
  regiões; cursos d'água deixam de ser parede absoluta para a rota.
- **0.14** — Auditoria adversarial de matemática, geografia e idiomas: 26 achados
  corrigidos.
- **0.13** — Zero dependências externas (GDAL/OGR no lugar de geopandas/shapely).
- **0.12** — QGIS 4 / Qt6 verificado construindo a janela sobre PyQt6.
- **0.10–0.11** — Seis idiomas; assistente de quatro etapas redesenhado.
- **0.8** — Múltiplos destinos, com ordenação ótima exata.
- **0.7** — Primeira validação empírica contra 224 km de trajetos de GPS de
  campo; constantes de rota calibradas contra a geometria.
- **0.6** — Só o MDE é obrigatório; cursos d'água, umidade, rugosidade e
  transitabilidade derivados dele; tempo de caminhada de Tobler.
- **0.5** — Documentação em inglês; preparação para o QGIS 4.
- **0.4** — Beta pública inicial.

## Licença

MIT — ver [`LICENSE`](../../LICENSE).
