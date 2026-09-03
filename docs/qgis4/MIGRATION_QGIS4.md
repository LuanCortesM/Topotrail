# TopoTrail - Migracao QGIS 4 / Qt6

## Resultado

O plugin foi preparado para permanecer compativel com QGIS 3.22+ e para testes em QGIS 4 / Qt6. A migracao nao foi feita de forma cega: as mudancas automaticas foram evitadas porque o ambiente local nao possui PyQt6 para executar o script auxiliar.

## Auditoria realizada

- Estrutura principal revisada: `topotrail.py`, `ui/topotrail_dialog.py`, `ui/topotrail_dialog.ui`, `processing/algorithm.py`, `processing/route_scenarios.py`, `metadata.txt`, `assets`, `docs` e arquivos de entrada do plugin.
- Imports PyQt revisados: o plugin usa `qgis.PyQt`; nao foram mantidos imports diretos de `PyQt5` ou `PyQt6`.
- APIs e enums revisados: nao foram encontrados usos ativos de `QVariant`, `QRegExp`, `QDesktopWidget`, `Qt.UserRole`, `Qt.WaitCursor`, `Qt.blue`, `Qgis.Critical`, `QgsMapLayer.VectorLayer`, `QgsWkbTypes.PolygonGeometry`, `activated[str]`, `resources_rc` ou `QFontMetrics.width()`.
- HUD auditada: havia tamanhos fixos para botoes, logos, janela minima, campos e QSS com cores absolutas que podiam prejudicar DPI alto, telas pequenas e tema escuro.

## Dry-run do script auxiliar

Comando solicitado:

```powershell
python pyqt5_to_pyqt6.py "<PLUGIN_DIRECTORY>" --dry_run --logfile qgis4_migration_dryrun.log
```

Resultado: o script nao iniciou porque este ambiente nao possui `PyQt6` instalado. A falha foi registrada em `qgis4_migration_dryrun.log`. Nenhuma alteracao automatica foi aplicada.

## Mudancas aplicadas

- `metadata.txt`: adicionado `qgisMaximumVersion=4.99`; `qgisMinimumVersion=3.22` foi mantido; `supportsQt6=True` nao existe no arquivo.
- `topotrail.py`: `QAction` agora e importado de `qgis.PyQt.QtGui` quando disponivel, com fallback para `qgis.PyQt.QtWidgets` no Qt5.
- `ui/topotrail_dialog.py`: adicionados helpers de enum para Qt5/Qt6, evitando chamadas antigas diretas em pontos migrados.
- `ui/topotrail_dialog.py`: `exec_()` foi substituido por helper compativel com `exec()` e fallback Qt5.
- `ui/topotrail_dialog.py`: botoes e campos passaram a usar `QSizePolicy`, larguras flexiveis, scrollbars e breakpoints `compact`, `normal` e `wide`.
- `ui/topotrail_dialog.py`: escalas de fonte, margens, espacamentos e logos agora derivam do DPI informado pelo Qt.
- `ui/topotrail_dialog.py`: textos longos de labels usam elide com tooltip para reduzir risco de estouro.
- `ui/topotrail_dialog.py`: QSS foi reduzido para usar `palette(...)`, respeitando melhor temas claro/escuro do QGIS.
- `ui/topotrail_dialog.ui`: removidos tamanhos fixos e estilos de cor que eram substituidos pela HUD em Python.

## Observacoes de empacotamento

A pasta `Topotrail V0.5.1` contem a raiz instalavel `TopoTrail` com apenas os arquivos necessarios para teste/publicacao do plugin, sem `.git`, `__pycache__`, backups, pacotes antigos, logs pessoais, caches ou dados de teste.
