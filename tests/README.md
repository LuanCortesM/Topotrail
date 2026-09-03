# Tests

Run from the repository root:

```bash
python -m pip install ruff pytest
ruff check .
pytest
```

These tests **do not require QGIS**, which is the point: they run in continuous
integration on a plain Python interpreter, on every push and pull request.

## What is covered today

| Module | Guards against |
|---|---|
| `test_metadata.py` | The plugin manifest drifting away from the released artefact — version mismatches between `metadata.txt`, `PLUGIN_VERSION` in `processing/algorithm.py` and `CITATION.cff`; missing required keys; a stale `experimental` flag; a missing icon; repository links pointing elsewhere. |
| `test_source_hygiene.py` | Text encoding damage (UTF-8 re-encoded as Latin-1), files that no longer parse, bare `except:` clauses, and a missing `classFactory` entry point. |

## What is not covered yet, and why

The numerical core lives in `processing/algorithm.py`, which imports
`qgis.core` at module level. That import makes the pure NumPy functions —
normalisation, the weighted linear combination, the risk model, the A* search,
elevation-band binarisation — unreachable from a test process that has no QGIS.

The planned fix is to extract those functions into a `processing/core.py` that
imports only NumPy, SciPy and GDAL, and have `algorithm.py` import from it. Once
that is done, each of them can be tested directly against small synthetic
elevation surfaces with analytically known answers.

`processing/route_scenarios.py` already contains a synthetic-dataset generator
and an output validator written for exactly this purpose
(`create_synthetic_route_dataset`, `create_contrasting_route_dataset`,
`validate_route_scenario_outputs`). They are currently unreachable — nothing
imports that module — and are the natural starting point for the integration
tests.

Anything that genuinely needs QGIS is verified by hand against the checklist in
[`../docs/qgis4/CHECKLIST_QGIS4.md`](../docs/qgis4/CHECKLIST_QGIS4.md).
