# TopoTrail — auditoria de prontidão para publicação

Avaliação contra os critérios de revisão do JOSS e os requisitos do repositório
oficial de plugins do QGIS. Auditoria adversarial: o objetivo foi encontrar o
que falta, não recapitular o que existe.

**Versão auditada:** 0.12.1 · 32 commits · **atualizado após a 0.13.1** · 5.895 linhas de código, 1.888 de
teste, 1.577 de documentação · 6 idiomas

---

## Veredito

**Atualização (0.13.1): o bloqueador técnico foi removido. Restam os três
bloqueadores administrativos — `paper.md`, ORCID e Zenodo — nenhum de código.**

*(Veredito original, 0.12.1: ainda não; quatro bloqueadores, um deles técnico e
sério.)*

A ciência está sólida e validada contra dado de campo real — essa é a parte
difícil, e está feita. O plugin agora carrega e roda numa instalação limpa de
QGIS, sem nada a instalar. O que falta é infraestrutura de publicação.

Nenhum bloqueador exige pesquisa nova. Todos são trabalho conhecido.

---

## Bloqueadores

### 1. O plugin não carrega numa instalação padrão de QGIS ⚠ CRÍTICO

`processing/algorithm.py` importa **geopandas** e **shapely** no topo do módulo.
Verificado empiricamente neste ambiente:

```
python3-qgis depende de: python3-gdal, python3-numpy, python3-scipy
python3-geopandas ........ instalação MANUAL — não é dependência do QGIS
```

E o teste direto, simulando uma instalação sem geopandas:

```
FALHOU sem geopandas: ImportError: No module named 'geopandas'
```

O QGIS garante **GDAL/OGR, NumPy e SciPy**. Não garante geopandas, shapely nem
pandas — em nenhuma plataforma. Num QGIS recém-instalado no Windows (OSGeo4W),
no macOS ou em Linux, este plugin **não carrega**: o ImportError acontece antes
de qualquer tela aparecer.

Isso é provavelmente o defeito mais consequente do projeto inteiro, e é
invisível para quem desenvolve numa máquina que tem tudo instalado.

**Correção:** trocar geopandas/shapely por OGR, que já é usado 17 vezes no mesmo
arquivo e traz o GEOS para união e buffer. São 12 pontos restantes, em três
funções.

**Estado: RESOLVIDO na 0.13.0.** Os doze pontos restantes foram migrados para
uma colecção mínima sobre `ogr.Geometry` (`FeatureSet`: reprojeção pelo OSR,
medida e buffer pelo GEOS, escrita em GPKG/SHP/KML). Verificado ponta a ponta
num QGIS headless com geopandas, shapely, pandas, fiona e pyproj **bloqueados
no import**: GeoPackage, Shapefile e KML; MDE projetado e geográfico; pontos de
passagem com ordem otimizada; camada de restrição. O ZIP de instalação foi
carregado num QGIS limpo pelo `classFactory` com os mesmos módulos bloqueados,
e a janela abriu. Um teste novo (`test_shipped_code_imports_only_what_qgis_guarantees`)
proíbe qualquer import de módulo que o QGIS não garanta, para não regredir.

Efeito colateral encontrado e corrigido: o driver clássico "KML" do OGR descarta
todos os atributos além dos dois primeiros (vão para Name/Description). A saída
KML usa agora o LIBKML, que grava todos com tipo.

### 2. `paper.md` não existe

É requisito obrigatório e não negociável do JOSS: um artigo curto (250–1.000
palavras) com resumo, *statement of need*, referências e metadados dos autores,
mais `paper.bib`.

Todo o material já existe espalhado — `docs/METODOLOGIA_TOPOtrail.md`,
`docs/VALIDACAO.md`, o README. Falta redigir na forma que o JOSS exige.

### 3. Sem ORCID

O JOSS espera ORCID do autor correspondente. Registro gratuito em orcid.org,
leva cinco minutos. O `CITATION.cff` já tem o campo comentado esperando.

### 4. Sem depósito no Zenodo e sem DOI

O JOSS exige um arquivo versionado com DOI, e que a versão depositada
corresponda à revisada. Feito ligando o repositório ao Zenodo e publicando uma
release no GitHub.

---

## Problemas sérios, não bloqueadores

### README sem seção explícita de *statement of need*

O conteúdo está lá — o README explica bem o problema —, mas o JOSS procura a
seção pelo nome. Renomear e enxugar resolve.

### `requirements.txt` e `metadata.txt` declaram o que não se usa

Ambos listavam **pandas**, que o código nunca importava diretamente.
**Resolvido na 0.13.0:** `requirements.txt`, `metadata.txt`, README,
CONTRIBUTING e o guia do usuário declaram agora apenas NumPy, SciPy e GDAL/OGR
— o que o QGIS já traz.

### Código morto removido nesta auditoria

`processing/route_scenarios.py` — 902 linhas que módulo nenhum importava, e que
também dependiam de geopandas. Removido.

---

## Limitações conhecidas — declaradas, e aceitáveis

Estas **não** impedem publicação. Estão documentadas em `docs/VALIDACAO.md`, e
declará-las é melhor que omiti-las: um revisor do JOSS respeita limitação
assumida e reprova limitação escondida.

| Limitação | Situação |
|---|---|
| Magnitude de `TERRAIN_SLOWDOWN_MAX` indeterminada entre 2,0 e 4,0 | Validação cruzada mostrou que sete trilhas não sustentam a escolha. Precisa de mais trajetos, não de mais análise. |
| `CONSTRAINT_PENALTY_FACTOR` sem calibração | O comportamento que ele modela — evitar drenagem — não ocorre nos dados. |
| Espanhol, francês, chinês e japonês sem revisão nativa | A interface avisa; o `CONTRIBUTING` convida à correção. |
| Sem teste de fumaça em QGIS 4 real | A janela foi construída e exercitada sob Qt 6.11 real, o que cobre o Qt; não cobre mudanças na API do próprio QGIS. |
| Legenda do raster mora em `.aux.xml` ao lado do `.tif` | Limitação do formato GeoTIFF, documentada no código. |

---

## O que está genuinamente forte

Vale registrar, porque é o que sustenta a submissão:

- **Validação contra campo real.** 110 h e 224 km de GPS em dois biomas. A
  função de Tobler foi confrontada com o dado, três controles descartaram
  artefatos, e a conclusão desconfortável — R² de 0,04, a topografia não explica
  o ritmo — está publicada em vez de escondida.
- **Constantes calibradas contra o objetivo certo.** O `SLOWDOWN` foi medido
  contra velocidade, reprovou, e foi remedido contra geometria de rota, que é o
  que ele de fato governa. A validação cruzada impediu adotar um valor que
  parecia melhor e não generalizava.
- **Uma limitação virou funcionalidade.** A travessia Marins–Itaguaré em que o
  plugin perdia para a linha reta levou aos destinos intermediários; declarados
  os cumes, o desvio mediano caiu de 1.860 m para 114 m.
- **203 testes**, quase todos de forma fechada — comparam com resultado
  conhecido no papel, não com execução anterior do próprio código. Dois deles já
  falsificaram afirmações da documentação.
- **Seis idiomas**, com detecção automática e textos em arquivos de dados que um
  falante nativo corrige sem tocar em Python.
- **Integração contínua** com lint, compilação em duas versões de Python e a
  suíte completa, incluindo o teste sob Qt6.

---

## Plano, em ordem

1. ~~**Terminar a migração para OGR**~~ — **feito (0.13.0).**
2. **Escrever `paper.md` e `paper.bib`** — material já existe, falta a forma.
3. **Registrar ORCID** — cinco minutos, é seu.
4. **Assinar os commits** (`assinar.sh`), publicar release, ligar ao Zenodo,
   pegar o DOI.
5. ~~**Ajustar README, `requirements.txt` e `metadata.txt`**~~ — **feito (0.13.0).**
6. **Teste de fumaça num QGIS 4 real** antes de anunciar suporte à versão 4
   (aqui a janela foi construída sob PyQt6 6.11 nos seis idiomas, sem problemas;
   falta só a confirmação num QGIS 4 instalado).

O item 2 é redação. Os itens 3, 4 e 6 dependem de você e de contas suas.

### Interface (0.13.1)

Achado da passagem visual: o Qt ignora em silêncio `font-size` com meio pixel
(`12.5px`), e dezessete regras da janela usavam isso — quase todo o texto saía
no tamanho padrão do QGIS, não no desenhado. Corrigido (pixel inteiro, base de
13 px) e protegido por teste. Também corrigidos: cinco textos que ficavam em
português depois de trocar o idioma (o harness Qt6 agora verifica isso), o
cabeçalho uma linha mais baixo, e os produtos "incluídos" que pareciam
desligados.
