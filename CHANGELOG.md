# Changelog

Mudanças relevantes do TopoTrail. Formato
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões em
[Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Unreleased]

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
