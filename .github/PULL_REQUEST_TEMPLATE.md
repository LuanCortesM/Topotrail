<!-- Thanks for contributing. Keep one topic per pull request. -->

## What this changes

<!-- One or two sentences. Link the issue it closes, if any. -->

## Why

<!-- The reasoning. For methodological changes, cite the section of
     docs/METODOLOGIA_TOPOtrail.md or the literature the change follows. -->

## Does this change numerical results?

- [ ] No — refactoring, interface, documentation or tooling only.
- [ ] Yes — and the reasoning is explained above.

<!-- If yes: which outputs change (suitability raster, zones, risk, route,
     corridor), and roughly by how much on a test area. A silent change in
     output is worse than a visible one. -->

## Checks

- [ ] `ruff check .` passes
- [ ] `python -m compileall -q processing ui topotrail.py __init__.py` passes
- [ ] `pytest -q` passes
- [ ] Loaded in QGIS and exercised the affected path by hand
- [ ] Documentation updated (English and, where it applies, `docs/pt_BR/`)
- [ ] New empirical constants are named and commented, not inline
