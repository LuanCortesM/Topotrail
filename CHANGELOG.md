# Changelog

Mudanças relevantes do TopoTrail. Formato
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões em
[Versionamento Semântico](https://semver.org/lang/pt-BR/).

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
