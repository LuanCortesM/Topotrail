# Contributing to TopoTrail

Thanks for taking the time to contribute. TopoTrail is a QGIS plugin for
preliminary topographic planning of trails, access routes and field corridors in
natural and protected areas. It is maintained as part of academic research, and
contributions from GIS practitioners, protected-area staff and developers are
welcome.

Portuguese speakers: issues, pull requests and discussion in Portuguese are
fine. The code, commit messages and primary documentation are kept in English so
the project stays reviewable by an international audience.

## Ways to contribute

- **Report a bug** — open an issue with the bug template. The single most useful
  attachment is the `*_diagnostico_topotrail.log` file the plugin writes next to
  your output; it records the plugin version, dependency versions, every
  parameter and the distribution statistics of each intermediate raster.
- **Report a methodological problem** — if a result looks wrong rather than
  broken, say so explicitly. Modelling choices are documented in
  [`docs/METODOLOGIA_TOPOtrail.md`](docs/METODOLOGIA_TOPOtrail.md) and audited in
  [`docs/METHODOLOGICAL_AUDIT.md`](docs/METHODOLOGICAL_AUDIT.md); disagreement
  with a documented choice is a legitimate issue.
- **Suggest a feature** — use the feature template and describe the planning
  problem you are trying to solve, not only the control you would like to see.
- **Improve documentation or translations** — the English documentation is
  primary; `docs/pt_BR/` holds the Portuguese reference copies. Both should stay
  in sync.
- **Send code** — see below.

## Reporting a bug well

Include:

1. QGIS version and operating system.
2. TopoTrail version (shown in the diagnostic log, and in
   `Plugins > Manage and Install Plugins`).
3. The diagnostic log file, or the traceback shown in the error dialog.
4. Source, resolution and CRS of the DEM, and how slope and curvature rasters
   were produced.
5. The parameters you used.

Please do not attach large rasters to an issue. A description of their extent,
resolution and CRS is usually enough; if a dataset is genuinely needed we will
ask for a link.

## Development setup

TopoTrail runs inside the QGIS Python environment. It is not installed with pip.

1. Clone the repository.
2. Symlink or copy the repository into your QGIS plugin directory as a folder
   named `TopoTrail`:
   - Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\TopoTrail`
   - Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/TopoTrail`
   - macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/TopoTrail`
3. Restart QGIS and enable the plugin.
4. The [Plugin Reloader](https://plugins.qgis.org/plugins/plugin_reloader/)
   plugin saves a great deal of time while iterating.

Runtime dependencies (NumPy, SciPy, Pandas, GeoPandas, Shapely, GDAL) must be
available to the QGIS Python interpreter. On Windows, install them through the
OSGeo4W shell rather than a system Python. See the README for details.

## Checks that run on every pull request

Continuous integration runs on GitHub Actions and does not require QGIS:

```bash
python -m pip install ruff pytest
ruff check .                 # error-level lint only, see pyproject.toml
python -m compileall -q processing ui topotrail.py __init__.py
pytest -q
```

Run these locally before opening a pull request. Anything that needs QGIS itself
has to be verified by hand — see `docs/qgis4/CHECKLIST_QGIS4.md` for the manual
checklist.

## Pull requests

- Branch from `main`, one topic per branch.
- Keep the change focused. A pull request that fixes a bug and reorganises the
  interface at the same time is hard to review and hard to revert.
- Write commit messages in English, present tense, explaining *why*:
  `Validate slope raster units before normalisation`, not `fix`.
- **If your change alters numerical results, say so in the pull request
  description and explain the methodological reasoning.** This is a scientific
  tool; a silent change in output is worse than a visible one.
- Update the documentation in the same pull request. If you change a modelling
  constant, update `docs/METODOLOGIA_TOPOtrail.md` and the Portuguese copy.
- Add or update a test when the change touches logic that can be tested without
  QGIS.

## Code style

- Python 3, four-space indentation, roughly 100 columns.
- Follow the surrounding style rather than reformatting untouched code.
- Empirical constants get a **name and a comment**, at module level, next to the
  existing block in `processing/algorithm.py`. Do not introduce new magic numbers
  inline.
- User-facing strings go through the translation mechanism. Do not hardcode a
  new Portuguese-only string in the interface.

## Getting help

Open an issue with the question template, or write to the project address,
herpetomantiqueira@gmail.com. There is no separate support channel;
issues are the record.

## Using AI assistance in a contribution

Using a language model to help write a patch is fine, and it does not need to be
hidden. State it in the pull request description, in one line, and say what you
verified yourself.

Do not add a model as `Co-Authored-By`. Authorship means accountability for the
work, and a tool cannot answer for it. If a change alters numerical results,
the reasoning in the pull request has to be yours — a model's confidence is not
evidence, and neither is mine.

## Code of conduct

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

## Licence

By contributing you agree that your contribution is licensed under the MIT
Licence, the same terms as the rest of the project.

## Traduções

O TopoTrail fala seis idiomas: português, inglês, espanhol, francês, chinês e
japonês. Os textos ficam em `i18n/<código>.json` — um arquivo por idioma, com as
mesmas chaves em todos.

**Português e inglês foram escritos pelo autor. Espanhol, francês, chinês e
japonês são traduções de partida e ainda não foram revisadas por falantes
nativos.** A interface diz isso a quem as usa. Se você fala uma dessas línguas,
corrigir um termo é provavelmente a contribuição mais fácil e mais útil que dá
para fazer aqui.

### Corrigir uma tradução

1. Abra `i18n/<código>.json` e edite o valor. Não mexa nas chaves.
2. Preserve os marcadores entre chaves — `{n}`, `{path}`, `{version}` — e a
   quantidade deles. `tests/test_i18n.py` reprova se um sumir, porque um
   marcador perdido só estoura em tempo de execução, no idioma que ninguém da
   equipe testa.
3. Rode `python -m pytest tests/test_i18n.py` antes de abrir o pull request.

Terminologia geomorfométrica tem convenções estabelecidas em cada língua, e é
justamente aí que uma tradução automática erra: em francês usamos MNT e não DEM,
*courbure planaire* e não *courbure de plan*. Se você discordar de um termo, diga
o porquê no pull request — a discussão vale mais que a troca.

### Acrescentar um idioma

1. Copie `i18n/en.json` para `i18n/<código>.json` (código ISO 639-1 de duas
   letras).
2. Traduza os valores.
3. Acrescente `("<código>", "<Nome do idioma na própria língua>")` a `LANGUAGES`
   em `ui/i18n.py`. O nome vai escrito na própria língua de propósito: quem
   precisa do japonês normalmente não lê a palavra "japonês".
4. Atualize a lista esperada em `tests/test_i18n.py`.

Não há nada para compilar. O plugin não usa `.ts`/`.qm`: o `.qm` é um binário
gerado com `lrelease`, o que obrigaria a um passo de build antes de empacotar e
poria no repositório um arquivo que ninguém consegue revisar num pull request.
