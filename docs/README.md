# TopoTrail Documentation

Technical documentation for TopoTrail. The English files are the primary
documentation for publication, repository submission and external review.

## Primary documentation

- [Methodology](METODOLOGIA_TOPOtrail.md) — formulas, empirical constants,
  normalisation rules and the CRS/alignment procedure.
- [User Guide](USUARIO_TOPOtrail.md) — step-by-step use, common errors and how
  to read the outputs.
- [Methodological Audit](METHODOLOGICAL_AUDIT.md) — critical review of the
  modelling choices, with their known limitations. It audits **version 0.5.0**
  and is kept as a record: a provenance header at the top says so, and a closing
  section says item by item which of its recommendations were implemented and in
  which version.
- [Empirical validation](VALIDACAO.md) — what field GPS tracks said about the
  empirical constants, and which plugin version produced each figure.
- [Worked example](../exemplo/README.md) — a small synthetic DEM, three points,
  one script, and the output values to check against.
- [QGIS 4 migration](qgis4/) — migration notes and the manual verification
  checklist for things that cannot be tested without QGIS.

## Portuguese reference copies

Portuguese versions are preserved in [`pt_BR`](pt_BR). They are kept for
continuity with the original development and research notes.

> Known issue: the body of `AUDITORIA_METODOLOGICA_pt_BR.md` was written without
> diacritics, and is left as it was written — it is a dated record, not living
> documentation. The other three Portuguese documents have been rewritten for
> 1.3.0, with correct accentuation.
