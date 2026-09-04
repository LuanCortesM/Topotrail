# TopoTrail — auditoria de prontidão para publicação

Avaliação contra os critérios de revisão do JOSS e os requisitos do repositório
oficial de plugins do QGIS. Auditoria adversarial: o objetivo foi encontrar o
que falta, não recapitular o que existe.

**Versão auditada:** 0.12.1 · 32 commits · 5.895 linhas de código, 1.888 de
teste, 1.577 de documentação · 6 idiomas

---

## Veredito

**Ainda não. Faltam quatro bloqueadores, e um deles é técnico e sério.**

A ciência está sólida e validada contra dado de campo real — essa é a parte
difícil, e está feita. O que falta é infraestrutura de publicação e uma
dependência que impede o plugin de carregar na maioria das instalações de QGIS.

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

**Estado:** parcialmente feito. A camada de restrição já foi migrada e verificada
(2 feições, buffer de 60 m, 2.025 células — resultado idêntico ao anterior).
Faltam a vetorização das zonas, a gravação do vetor de saída e a rota/corredor.

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

Ambos listam **pandas**, que o código nunca importa diretamente. Depois da
migração para OGR, geopandas e shapely também saem. Uma lista de dependências
que não corresponde ao código é o tipo de coisa que um revisor testa e reporta.

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

1. **Terminar a migração para OGR** — remove o bloqueador crítico. É o único
   item que exige código.
2. **Escrever `paper.md` e `paper.bib`** — material já existe, falta a forma.
3. **Registrar ORCID** — cinco minutos, é seu.
4. **Assinar os commits** (`assinar.sh`), publicar release, ligar ao Zenodo,
   pegar o DOI.
5. **Ajustar README, `requirements.txt` e `metadata.txt`** às dependências reais.
6. **Teste de fumaça num QGIS 4 real** antes de anunciar suporte à versão 4.

Os itens 1, 2 e 5 são trabalho de código e redação. Os itens 3, 4 e 6 dependem
de você e de contas suas.
