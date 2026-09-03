# CHECKLIST_QGIS4

## Validado nesta preparacao

- [x] Nao ha imports diretos de `PyQt5` ou `PyQt6` nos arquivos principais do plugin.
- [x] Imports Qt passam por `qgis.PyQt`.
- [x] `metadata.txt` mantem `qgisMinimumVersion=3.22`.
- [x] `metadata.txt` contem `qgisMaximumVersion=4.99`.
- [x] `supportsQt6=True` nao esta presente.
- [x] `QAction` recebeu import compativel Qt5/Qt6.
- [x] `exec_()` foi removido dos arquivos principais.
- [x] Usos antigos conhecidos de enums Qt/QGIS nao foram encontrados na auditoria final.
- [x] HUD recebeu breakpoints `compact`, `normal` e `wide`.
- [x] HUD usa `QSizePolicy`, scroll area e medidas derivadas de DPI.
- [x] Textos longos em labels/botoes receberam elide/tooltip onde ha risco de estouro.
- [x] QSS usa a paleta do Qt/QGIS em vez de depender de fundo claro fixo.
- [x] Pasta final exclui `.git`, `__pycache__`, backups, pacotes antigos, caches e dados de teste.
- [x] Compilacao Python (`compileall`) dos arquivos principais passou.

## Requer teste manual no QGIS 4

- [ ] Abrir o plugin no QGIS 4 / Qt6 e confirmar carregamento do dialogo principal.
- [ ] Testar HUD em janela estreita, Full HD, 2K, 4K e escala 125%, 150% e 200%.
- [ ] Confirmar contraste visual em tema claro e escuro do QGIS.
- [ ] Confirmar fluxo de selecao de CRS com `QgsProjectionSelectionDialog`.
- [ ] Executar um processamento completo com DEM, declividade e curvaturas reais.
- [ ] Validar carregamento das camadas de saida no canvas do QGIS 4.
- [ ] Confirmar disponibilidade das dependencias externas no Python do QGIS 4: NumPy, SciPy, Pandas, GeoPandas, Shapely e GDAL.
- [ ] Validar instalacao do ZIP pelo gerenciador de plugins do QGIS.

## Requer teste manual no QGIS 3

- [ ] Abrir o plugin no QGIS 3.22+ apos as mudancas de compatibilidade.
- [ ] Confirmar o fallback de `QAction` no Qt5.
- [ ] Confirmar que o helper de execucao de dialogo usa `exec_()` quando `exec()` nao estiver disponivel.

