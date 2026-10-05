# Tests

There are two suites, and they are two on purpose.

| Suite | Modules | Tests | Needs QGIS? |
|---|---|---|---|
| `tests/` — hermetic | 18 | 368 | no |
| `integracao/` — integration | 5 | 32 | yes, plus real GDAL |

With the Python that QGIS uses (Linux: `python3`; Windows: `python-qgis.bat`;
macOS: the Python inside `QGIS.app`):

```bash
python -m pytest                    # both suites; integracao/ skips itself without QGIS
python -m pytest tests              # hermetic only
python -m pytest integracao         # integration only
```

`pytest .` and `pytest tests integracao` work too. The hermetic suite replaces
`qgis.core`, `osgeo` and the plugin's own `processing` package with dumb stubs
**only while** `processing/algorithm.py` is imported (`nucleo_sem_qgis.py`) and
restores `sys.modules` right after, so the integration suite in the same process
sees the real QGIS and GDAL. The integration suite still refuses any module
carrying the stub marker, as a guard.

## The hermetic suite (`tests/`)

```bash
python -m pip install ruff pytest numpy scipy pyproj
ruff check .
pytest
```

It needs **no QGIS** and finishes in a few seconds on a plain interpreter,
which is the point: it runs on every push and pull request, on Python 3.9 and
3.12. `pyproj` is not a dependency of the plugin; it only backs the stub that
stands in for GDAL's OSR.

`processing/algorithm.py` imports `qgis.core` at module level, so its
mathematics could not be reached from a test process without QGIS. Rather than
refactor a very large module, `nucleo_sem_qgis.py` substitutes the modules that
are needed only for the import, and puts the originals back afterwards. The stubs are deliberately dumb — `GetDriverByName`
returns `None`, `QgsProcessingAlgorithm` is an empty class — so that a test
which actually reaches for QGIS or GDAL behaviour fails loudly instead of
passing quietly against a fake. `terrain.py`, `hydrology.py` and
`transitability.py` and `morphology.py` import only NumPy and need none of this;
they are imported directly.

| Module | Tests | Guards against |
|---|---|---|
| `test_terrain_math.py` | 30 | Slope, curvature and ruggedness drifting from their definitions: closed-form surfaces with known answers, the sign convention, one-sided differences at a NoData edge, behaviour of the curvature stencil. |
| `test_morphology.py` | 51 | The connected-component labelling and the exact Euclidean distance transform that replace SciPy where it is missing: labels identical to SciPy's, distances equal to brute force, and the algorithm giving the same zones with and without SciPy. |
| `test_alternativas.py` | 17 | The near-optimal corridor: the vectorised grid graph reproducing the A\* cost exactly (isotropic, Tobler, fords on diagonals), the Python Dijkstra matching SciPy's, the route always inside the corridor, and two equal valleys both entering it. |
| `test_routing_math.py` | 57 | The cost surface and the A\* search, compared against a plain Dijkstra written from scratch in the test file and against closed-form values of Tobler's function: the three cost models, the asymmetry, the diagonal step, and the invariance of the path to maximum walking speed. |
| `test_i18n.py` | 44 | Language files drifting apart: key parity across the six languages, placeholders surviving translation, and the five transitability class labels staying distinct and matching the published table. |
| `test_hydrology_math.py` | 19 | Depression filling, D8 flow routing, flow accumulation and the topographic wetness index, against small surfaces whose drainage is known by hand. |
| `test_qt6_compat.py` | 27 | Qt5-only constructs that would break under QGIS 4: scoped enums, `QAction`'s move between modules, stylesheet sub-controls. |
| `test_ui_contract.py` | 25 | The four-step window and the Processing algorithm falling out of step over parameter names, defaults and labels. |
| `test_audit_regressions.py` | 18 | The specific defects earlier audits found, one test each, so none of them comes back silently. |
| `test_lote_correcoes.py` | 14 | The batch of fixes that came out of the expert audit, each test reproducing the defect as it was measured, at the level that needs no QGIS. |
| `test_metadata.py` | 11 | The manifest drifting from the artefact: version agreement between `metadata.txt`, `PLUGIN_VERSION` and `CITATION.cff`, required keys, the `experimental` flag, the icon, repository links. |
| `test_source_hygiene.py` | 11 | Encoding damage (UTF-8 re-encoded as Latin-1), files that no longer parse, bare `except:`, `except: pass` — which blocks a release on plugins.qgis.org — and any module-level import of something QGIS does not ship. |
| `test_waypoints_math.py` | 11 | Multi-leg routes and the exact Held-Karp ordering of intermediate destinations. |
| `test_transitability_math.py` | 10 | The five classes, the ruggedness and wetness modifiers, the coarse-cell warning, and the rule that the labels never again claim a verdict about the walker. |
| `test_empacotamento.py` | 4 | The published ZIP containing anything but `git archive HEAD` minus the development directories, and being reproducible. |
| `test_validacao_executavel.py` | 17 | Every script in `validation/` runnable on another machine: no absolute path of the development machine, no `/tmp`, and without data each one stops with instructions instead of a traceback. |
| `test_qt6_runtime.py` | 1 | The window actually building under PyQt6, in a subprocess — PyQt5 and PyQt6 cannot share an interpreter. Skipped where PyQt6 is absent. |
| `test_vector_io.py` | 1 | The vector writer round-tripping through a real OGR, when one is available. |

`apoio.py` holds the synthetic surfaces the numeric tests share, and
`qt6/harness.py` is the subprocess harness used by `test_qt6_runtime.py`.

## The integration suite (`integracao/`)

```bash
python -m pytest integracao -q
```

It runs the plugin against the **real** GDAL and a real headless QGIS, started
in-process. It exists because of what the stubs cannot see: the worst defect the
1.2.0 audit found — writing output into an existing GeoPackage deleted the
user's layers — was invisible to every unit test, because in the stub
`GetDriverByName` returns `None`. Its `conftest.py` refuses any module carrying
the stub marker and skips rather than test against a double.

| Module | Tests | Covers |
|---|---|---|
| `test_lote_correcoes_integracao.py` | 15 | The 1.3.0 fixes that only show up in a full run: the legend written beside the raster, warnings that were never actually emitted, keys missing from the result dictionary. |
| `test_exemplo.py` | 5 | `exemplo/` still runs and still produces the values `exemplo/README.md` publishes, and still declares every one of the algorithm's 52 parameters. |
| `test_janela.py` | 3 | The four-step window as a user drives it: fill the steps, click Run, wait for the background task; the log written only from the interface thread; Cancel ending without an error box; no label clipped in any of the six languages. |
| `test_saidas_novas.py` | 6 | The alternatives corridor containing the route, fixed normalisation limits reproducing the automatic run, two clips of a geographic DEM giving the same route with a fixed working cell, the field pace, and the advanced-parameter flags. |
| `test_saidas_gpkg.py` | 3 | Writing into an existing GeoPackage without destroying what is already in it, and the transitability legend surviving inside a `.tif` sent on its own. |

The whole suite skips itself where QGIS or GDAL is missing, so it is safe to run
anywhere; it just will not tell you much without them.

Continuous integration runs this suite inside the official QGIS 3.22, 3.44 LTR
and 4.2 Docker images, followed by the reproducible example and
`tools/instalar_e_carregar.py`, which installs the packaged zip in an empty
profile and loads it through `qgis.utils` the way the Plugin Manager does.

## What is still checked by hand

Anything that needs a real QGIS 4 desktop session is verified against the
checklist in
[`../docs/qgis4/CHECKLIST_QGIS4.md`](../docs/qgis4/CHECKLIST_QGIS4.md). The Qt6
tests cover the Qt half of that move; they do not cover changes in the QGIS API
itself between 3 and 4.
