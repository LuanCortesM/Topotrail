# Changelog

Mudanças relevantes do TopoTrail. Formato
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões em
[Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [1.5.5] - 2026-10-27

### Corrigido

- **O andamento, os avisos e os erros do cálculo saem no idioma escolhido.** Até a 1.5.4, as cerca de 170 frases do algoritmo saíam em português sem acento, qualquer que fosse o idioma da janela. Agora são 288 mensagens nos seis idiomas, nos arquivos `i18n/<código>.json` (chaves `msg_*`), e o idioma é o mesmo dos rótulos: o escolhido na janela ou, sem escolha, o do QGIS.
  - Os números saem no formato da língua: 1.234,5 em português e espanhol, 1 234,5 em francês, 1,234.5 em inglês, chinês e japonês.
  - As opções citadas nas mensagens ("Considerar cursos d'água extraídos do MDE", "Equilibrar zonas por faixa altimétrica") vêm com o nome que a janela mostra naquele idioma.
  - Na camada de travessias, os valores de texto (`tipo` e `aviso`) também saem no idioma escolhido; os nomes dos campos não mudam.
  - Testes novos: um roda o cálculo nos seis idiomas e barra palavra que só exista em português; outro barra frase escrita direto no código, fora do catálogo.
  - As frases em espanhol, francês, japonês e chinês ainda não passaram por revisão de falantes nativos.
- **Coordenadas do ponto deslocado:** o aviso do ponto movido para a célula viável mais próxima escrevia "7.49525e+06"; agora sai em metros, com uma casa decimal.

## [1.5.4] - 2026-10-27

### Adicionado

- **Aviso de desvio pela declividade máxima.** Com o limite padrão de 85%, a rota existe mas pode contornar por quilômetros um terreno que o MDE vê mais íngreme, onde a trilha real sobe por cabo, escada ou zigue-zague que a grade de 30 m não resolve.
  - **O que faz.** Depois da rota, o plugin traça a rota sem o limite de declividade; os rios acima do teto vadeável e as restrições no modo evitar continuam barrando. Avisa quando a rota é ao menos 25% e 500 m mais longa e a rota sem limite passa de fato por terreno acima dele. A mensagem dá os dois comprimentos e a declividade máxima que permitiria a rota curta.
  - **A rota não muda.** Se a comparação falhar, isso fica só no registro técnico, no evento `desvio_pela_declividade`.
  - **O teste.** 101 trilhas reais: o aviso saiu em 10, as de trecho com cabo ou escalaminhada (Angels Landing, Bright Angel, Mist Trail, Masada, Madeira PR1, entre outras). Nas 10, a rota com o limite relaxado fica mais perto da trilha real. Rota idêntica à da 1.5.3 nas 101.
  - **O custo.** Nas rotas longas de montanha, o cálculo da rota leva até o dobro do tempo. Quando a rota já está perto da distância mínima entre os pontos, a segunda rota não é feita.

## [1.5.3] - 2026-10-27

### Alterado

- **Área mínima do fragmento das zonas automática por padrão:** 0,05% da área analisada, entre 1 e 50 ha. Dá 5 ha numa área de 10 mil ha e 50 ha a partir de 100 mil ha; até a 1.5.2 eram 50 ha fixos.
  - **Por quê.** Com 50 ha, as zonas de uma UC de ~10 mil ha deixavam as encostas de fora: nas Carnaúbas, 4 de 10 faixas de altitude; no MONA Mantiqueira Paulista, 6 de 10. Com a regra nova, cobrem 9 e 10.
  - **O teste.** 15 UCs de proteção integral sorteadas do Cadastro Nacional, de 500 a 300 mil ha, com pelo menos 300 m de desnível.
    - Com 50 ha, as zonas deixavam faixas de fora em 7.
    - A regra proporcional resolveu 4 delas, não criou aviso em nenhuma e, nas UCs grandes, dá o mesmo que os 50 ha.
    - Os 5 ha fixos resolviam as mesmas 4, mas picotavam as zonas das UCs grandes em 4 a 9 vezes mais fragmentos.
  - **Na janela.** O campo mostra "Automática". Um valor digitado fixa a área, e 0 continua desligando o filtro. No Processing, o automático é −1.
  - **No log.** O registro mostra a área usada e a área analisada.

## [1.5.2] - 2026-10-25

### Corrigido

- O zip do plugin não leva mais o `.flake8` (nem `.bandit` ou `.secrets.baseline`, se um dia existirem): com ele, o plugins.qgis.org marcava a 1.5.0 e a 1.5.1 como "Validated (configured)", em laranja, e não como "Validated". O arquivo continua no repositório, onde dá ao CI o limite de linha. O plugin é o mesmo da 1.5.1.
- Testes que importavam `ui` pelo nome só funcionavam com o pytest rodando da raiz do repositório; no trabalho do CI sem QGIS, que roda `pytest` puro, quebravam. Agora carregam o arquivo pelo caminho, e um teste impede que o padrão volte.

## [1.5.1] - 2026-10-25

### Adicionado

- Botão **Relatar problema**, no canto inferior direito da janela, em todos os passos. A pessoa escreve o que aconteceu e o plugin junta as versões (TopoTrail, QGIS, Qt, Python, GDAL, NumPy, SciPy, sistema), o último erro, o registro técnico e as últimas linhas do andamento, com a pasta pessoal trocada por `~`. *Enviar por e-mail* abre o programa de e-mail endereçado ao `email` do `metadata.txt` e copia o texto, para quem usa webmail; *Abrir no GitHub* abre o formulário de bug já preenchido; *Copiar texto* serve a qualquer outro canal. A caixa de falha aponta para o botão.

### Alterado

- A janela se ajusta à tela: o piso de 940 × 720 continua onde cabe e encolhe até a área útil onde não cabe (os passos rolam), e ela abre centralizada sobre o QGIS. Num notebook 1366 × 768 a 125% o botão Continuar ficava embaixo da barra de tarefas; a 150% num 1920 × 1080 sumia a faixa de baixo.
- O Sobre diz o que o plugin gera hoje (inclusive os cursos d'água), traz como citar com o DOI de conceito do Zenodo e tem links para o manual, o código-fonte e o relato de problema.
- O campo do tamanho da faixa altimétrica ganhou rótulo e só fica ativo com as faixas ligadas; o aviso de representatividade usa o nome da opção que aparece na janela ("Equilibrar zonas por faixa altimétrica").
- A ajuda do teto vadeável não repete mais a frase do cartão da drenagem: diz o que o teto faz.
- No `metadata.txt`, a descrição deixa de dizer que o plugin não detecta hidrografia: a drenagem vem do próprio MDE.

## [1.5.0] - 2026-10-25

### Adicionado

- Relatório de representatividade das zonas, no log, sem parâmetro novo: em quantas de 10 faixas da área as zonas estão, para altitude (faixas de mesma largura em metros), face norte/sul e umidade do terreno. Avisa quando falta parte do gradiente de altitude e sugere ligar as faixas de altitude; lembra que a cobertura do solo precisa ser conferida fora do plugin. Nas Carnaúbas, sem as faixas, as zonas ficavam em 2 de 10 faixas de 90 m; com elas, em 10 de 10.

### Alterado

- Declividade máxima padrão de 55% para **85%**. Em 35 trilhas reais (17 de caminhada, 6 exigentes, 8 alpinas, Copernicus 30 m), 55% ligava só 18 — e só 13 das 17 de caminhada —; 85% liga 33, todas as de caminhada, com a melhor concordância. Ficam de fora, por padrão, rotas de cabo e via ferrata (Half Dome pede 118%, Triglav 94%); a mensagem diz o valor que liga. A 100% ligava uma a mais e havia mais rotas por terreno mais íngreme que o da própria trilha (6 contra 4). Como o risco topográfico relativo é escalado pela declividade máxima, os valores do mapa de risco ficam menores no mesmo terreno.
- Drenagem extraída do MDE ligada por padrão (Processing e janela), e ela passa a **informar** a rota, não a desviar: abaixo do teto vadeável as travessias são listadas com a classe de tamanho e não mudam o custo (até a 1.4.1 custavam 2×, 4× e 8× em toda a faixa de 30 m, o que tirava a rota dos fundos de vale; em 62 trilhas reais isso piorou a concordância em 32 e melhorou em 15). A travessia é contada no eixo do canal, e contatos a menos de 150 m um do outro viram um evento só: travessia, ou trecho em que a rota segue junto ao curso (campo `tipo`, com `extensao_m`). No Batedor, 14 "travessias" eram a rota subindo o vale do córrego: viram 3 trechos junto ao curso. O campo `fator_custo` saiu da camada. Com MDE de 30 m ela achou 80% dos rios do OpenStreetMap e 23 de 27 travessias de rio em 51 trilhas consagradas. Em célula acima de 45 m, um aviso pede para conferir com a hidrografia oficial.
- As zonas mantêm as margens dos cursos d'água, que são hábitat de amostragem; no modo "evitar" elas excluem só a camada de restrição do usuário. O rio acima do teto vadeável, que a rota não cruza, continua fora das zonas. No exemplo, 11 zonas viram 12.
- Com a drenagem ligada por padrão, as superfícies exatamente planas de 0,5 km² ou mais (lagos e represas achatados no MDE) saem da área válida também por padrão, como já acontecia na 1.4.1 quando a drenagem era ligada. Em MDE de valores inteiros, uma planície pode ter patamares exatamente planos: confira o aviso de superfícies d'água no log.

- `tempo_h` e `tempo_campo_h` passam a ser o tempo de Tobler ao longo da rota, sem o retardo por terreno e sem os fatores de vau, que exprimem preferência e não ritmo. O custo acumulado continua em `custo`. Em 51 trilhas consagradas o valor antigo inflava a duração de 1,10 a 1,91 vez (mediana 1,39). No exemplo, a duração passa de 6,48 h a 3,96 h, já com a rota da drenagem que só informa.

### Corrigido

- Revisão de código antes da versão: contatos de cursos diferentes (bacias que diferem mais de 2×) não se fundem mais num evento; a distância de fusão acompanha a célula (pelo menos 3,5 células), para o MDE de 90 m não voltar a contar dezenas de "travessias"; a extensão junto ao curso não infla mais 41% nos passos diagonais; a mensagem de restrições não mostra mais "None"; na janela, o campo do teto de vau aparece com a drenagem ligada; a rota que falha não termina mais com a caixa "Pronto" (aviso com o erro) e apaga a rota velha de mesmo nome; o conselho de representatividade segue o modo das zonas; a face norte/sul não vira "plano" na borda sem dado; o aviso de célula grossa diferencia MDE grosso de reamostragem por memória.
- Rota impossível com zonas pedidas: a falha da rota abortava o algoritmo e levava junto as zonas e os mapas. Agora a falha vira erro no log e o resto é entregue. Só a rota, ou cancelamento, continua interrompendo.

## [1.4.1] - 2026-10-06

### Corrigido

- Mar e lagos achatados no MDE (Copernicus, SRTM) pareciam terreno ideal e levavam a rota para dentro d'água: superfícies planas de 0,5 km² ou mais passam a ser água (o mar sai sempre; os lagos saem com a drenagem ligada e, sem ela, a rota avisa quando cruza um).
- Sem ligação entre os pontos, o erro diz a declividade máxima que os liga, em vez de só pedir para aumentá-la.
- Sem nenhuma célula para as zonas (faixa de altitude fora do MDE), as zonas são puladas com aviso; rasters e rota seguem.
- O diagnóstico de contato de vértice escondia a sugestão de declividade.
- Aviso `Ring Self-intersection` do GEOS no stderr a cada polígono vetorizado.

## [1.4.0] - 2026-10-06

### Adicionado

- Corredor de alternativas (`ROUTE_ALTERNATIVES_PCT`): células em caminhos até x% mais caros que a rota, com raster de folga.
- Célula de trabalho fixa e alinhada (`WORKING_CELL_M`): a rota deixa de depender do recorte do MDE.
- Limites de normalização fixáveis (`CURVH_LIMIT`, `CURVV_LIMIT`, `WETNESS_LIMIT`, `ROUGHNESS_LIMIT`), registrados no log.
- Velocidade de levantamento em campo como parâmetro (`FIELD_SPEED_KMH`).
- `initProcessing`: o algoritmo funciona no `qgis_process` e no QGIS Server.
- Parâmetros de especialista agrupados em "Avançado" no Processing.
- CI dentro do QGIS 3.22, 3.44 e 4.2 reais: testes, exemplo, zip instalado e `qgis_process`.
- `tools/instalar_e_carregar.py`: instala o zip num perfil limpo e o carrega como o Gerenciador de Plugins.

### Alterado

- SciPy passa a ser opcional, com implementação em NumPy de resultado idêntico.
- `pytest`, `pytest .` e `pytest tests integracao` rodam as duas suítes no mesmo processo.
- Scripts de `validation/` recebem os dados por argumento ou variável de ambiente.
- Janela: rótulo acima das caixas de sentido do critério extra e de tratamento da restrição.
- Item de menu do plugin no idioma do usuário.

### Corrigido

- Tempo de caminhada gravado como "4h60" em vez de "5h00".
- Log da janela escrito fora da thread da interface.
- Cancelar terminava em caixa de erro e podia deixar o botão travado.
- Descarregar o plugin deixava a janela aberta.
- Escolher o MDE na janela ligava as exceções do GDAL para o QGIS inteiro.
- Com GDAL anterior à 3.7, as exceções do GDAL ficavam ligadas depois de cada execução.
- Exemplo reproduzível não rodava no Windows nem no macOS.
- Rótulo "Produtos" cortado no QGIS 3 do Windows.
- Driver `Memory` do GDAL trocado por `MEM` no GDAL 3.11+.

## 1.3.0 e anteriores

Ver o `changelog` do [`metadata.txt`](metadata.txt) e a seção *Changelog* do [`README.md`](README.md).

[1.4.1]: https://github.com/LuanCortesM/Topotrail/releases/tag/v1.4.1
[1.4.0]: https://github.com/LuanCortesM/Topotrail/releases/tag/v1.4.0
