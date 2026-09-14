# TOPO_TRAIL_METHODOLOGICAL_AUDIT.md

> ## Provenance — read this before reading the body
>
> **This document audits TopoTrail version 0.5.0.** It was written on
> **2026-05-21** (commit `d0a3212`), when `metadata.txt` declared `version=0.5.0`;
> it was moved from the repository root into `docs/` on 2026-09-03 (`f17380a`)
> and its body has not been changed since it was written.
>
> It is kept **as a record**, not as a description of the current software. Its
> statements were true of 0.5.0 and several of them are no longer true of the
> shipped version: in particular, this document describes a route algorithm that
> is isotropic and a workflow in which slope and both curvatures are mandatory
> user-supplied rasters. **Neither is the case any more.** Section 9, at the end,
> says item by item what was implemented and in which version.
>
> For what the software does **today**, read
> [`METODOLOGIA_TOPOtrail.md`](METODOLOGIA_TOPOtrail.md) (formulas and named
> constants, for version 1.3.0) and [`VALIDACAO.md`](VALIDACAO.md) (what field
> GPS tracks said about the empirical constants).

## 1. Executive Summary

The four external methodological criticisms are technically relevant, but they do not have the same severity.

Summary verdict:

| Criticism | Verdict | Severity |
|---|---|---|
| Bilinear resampling of slope and curvature rasters | Partially true | Medium |
| Isotropy of the least-cost route algorithm | True | Medium |
| Fixed or insufficiently explained mathematical constants | True | Medium |
| Dead, incomplete or experimental code in `utils.py` | Confirmed and removed | Resolved for the active plugin tree |

TopoTrail is suitable for experimental testing and can be described as a preliminary topographic planning tool, provided that its methodological limitations are explicit. For scientific publication, the documentation and manuscript should clearly state that the current workflow uses user-supplied derivative rasters, that the route algorithm is isotropic, and that some constants are empirical normalization or stabilization choices. Deeper changes, such as automatically recalculating slope and curvature or implementing anisotropic movement cost, should be treated as future-version work rather than silent changes to the current version.

## 2. Resampling of Topographic Derivatives

### Diagnosis

The criticism is partially true.

The function `align_raster_to_reference` is implemented in `processing/algorithm.py` and uses bilinear resampling by default. Its resampling map includes `gdal.GRA_Bilinear`.

In the main workflow, the slope, horizontal-curvature and vertical-curvature rasters are validated against the working DEM. When they are not compatible, they are aligned to the DEM grid through `align_raster_to_reference(..., resampling="bilinear")`.

The DEM itself is not aligned through that function in the main workflow. It is first prepared through `ensure_projected_working_crs`, which may reproject the DEM to a metric working CRS. The bilinear alignment step is applied to user-supplied derivative rasters when CRS, extent, resolution, dimensions or GeoTransform differ from the reference DEM.

### Files and Functions Involved

| File | Function or section | Role |
|---|---|---|
| `processing/algorithm.py` | `align_raster_to_reference` | Aligns a candidate raster to the DEM grid |
| `processing/algorithm.py` | `resampling_map` | Defines bilinear as the default resampling method |
| `processing/algorithm.py` | `calculate_slope_degrees` | Calculates slope in degrees from a DEM |
| `processing/algorithm.py` | `calculate_curvature_arrays` | Calculates curvature proxies from a DEM |
| `processing/algorithm.py` | main `processAlgorithm` flow | Aligns user-supplied slope and curvature rasters |

### Code Evidence

- The algorithm requires four raster inputs: DEM, slope, horizontal curvature and vertical curvature.
- `calculate_slope_degrees` and `calculate_curvature_arrays` exist, but they are not used in the main processing flow.
- The plugin currently preserves compatibility with derivative rasters produced outside TopoTrail.

### Methodological Impact

Bilinear resampling of slope and curvature can smooth extremes, reduce local peaks and alter abrupt terrain features. The impact is usually stronger for curvature because it is more sensitive to resolution, kernel size and grid alignment. This is not necessarily a functional error, but it is a methodological limitation that must be documented.

### Recommendation

The most rigorous correction would be to reproject or align the DEM first and then recalculate slope and curvature on the final working grid using a documented and reproducible method. This would require defining the derivative algorithm, slope unit, edge treatment, kernel or scale, and compatibility with existing test data.

The minimum safe correction for the current version is to keep compatibility with the four user-supplied rasters, document the limitation, and recommend that users generate slope and curvature rasters in the same CRS, resolution, extent and grid as the DEM before running TopoTrail.

## 3. Isotropy of the Route Algorithm

### Diagnosis

The criticism is true.

The function `least_cost_path` computes transition cost using the mean of the current-cell and next-cell costs multiplied by the step length:

```python
move_cost = ((current_cost + next_cost) / 2.0) * step_length
```

### Formula Interpretation

The transition cost uses:

- the cost of the current cell;
- the cost of the next cell;
- the step length, with orthogonal and diagonal movement distances.

It does not use elevation difference between neighboring cells during the transition calculation. The route-export function may use elevation values for final attributes, such as start elevation, end elevation and approximate elevation gain, but not for directional movement cost.

### Isotropic or Anisotropic?

The current route algorithm is isotropic. If two cells have the same surface cost, moving uphill and downhill between them has the same transition cost. Direction only affects distance, not the elevation gain or loss between cells.

### Impact on Route Interpretation

This does not invalidate the plugin. It defines the route as a least-cost path over a topographic suitability surface, not as a full physiological model of human walking effort. Since slope contributes to the cost surface, steep areas are penalized, but the same slope is not directionally distinguished as ascent or descent.

### Recommendation for the Current Version

Document the isotropic nature of the algorithm and preserve the current behavior for stability. Replacing the algorithm directly with an anisotropic model would change results, validation history, parameters and scientific interpretation.

### Recommendation for a Future Version

Add an optional anisotropic route mode while preserving the current isotropic mode as a compatible or legacy option. The anisotropic mode could use cell-to-cell elevation difference divided by horizontal distance and apply a directional cost function inspired by Tobler's Hiking Function or by a calibrated field-access model.

Expected impacts:

- a new route-mode parameter;
- possible uphill/downhill penalty parameters;
- clear handling of steep descents;
- different route outputs;
- additional tests comparing origin-to-destination and destination-to-origin results.

## 4. Mathematical Constants

| File | Function | Constant | Use | Methodological impact | Documented? | Recommendation |
|---|---|---:|---|---|---|---|
| `processing/algorithm.py` | `save_access_route` | `0.05` | Epsilon in `1 / (suitability + epsilon)` | Medium: limits maximum cost and avoids division by zero | Partially | Keep as named constant and explain as empirical stabilization |
| `processing/algorithm.py` | `compute_topographic_risk` | `1.35` | Exponent applied to slope risk | Medium: changes risk response to slope | Partially | Keep as named constant; explain in documentation and manuscript |
| `processing/algorithm.py` | `compute_topographic_risk` | `0.75 / 0.25` | Slope and curvature weights in relative risk | Medium: defines relative importance | Partially | Keep as named constants; describe as empirical weighting |
| `processing/algorithm.py` | `robust_abs_norm` | `95.0` | Robust percentile for curvature normalization | Medium: controls sensitivity to extremes | Partially | Keep as named constant or expose in a future advanced mode |
| `processing/algorithm.py` | `normalize_curvature_preference` | `0.2` | Curvature-score floor | Medium: prevents extreme curvature from forcing zero suitability | Partially | Keep as named constant; document |
| `processing/algorithm.py` | `normalize_curvature_preference` | `99` | Percentile used for curvature-deviation scaling | Medium | Partially | Keep as named constant; document |
| `processing/algorithm.py` | `save_access_route` | `8000000` | Maximum route crop size | Low/medium: computational safety limit | Partially | Keep as technical constant |
| `processing/algorithm.py` | `nearest_valid_cell` | `30` | Search radius for nearest valid cell | Low/medium | Partially | Keep as named constant or document |
| `processing/algorithm.py` | `binarize_by_altitude_bands` | `50.0` | Minimum altitude-band size | Medium | Partially | Keep as documented lower bound |
| `processing/algorithm.py` | QGIS parameters | several defaults | Default thresholds, weights, corridor width and search margin | Medium: configurable and user-facing | Partially | Keep configurable; justify in study cases |
| `processing/route_scenarios.py` | scenario presets | several values | Experimental route scenarios | Medium/high inside scenario workflows | Partially | Document as presets, not universal thresholds |

### Justifiable Constants

Conversion factors, diagonal movement distance, NoData values, EPSG identifiers and computational guardrails are technical constants. They are acceptable if named or clearly explained.

### Constants That May Need Future Parameters

The route-cost epsilon, risk weights and slope-risk exponent could become advanced parameters in a future version. They should not be exposed casually in the main interface before a stable calibration strategy exists.

### Constants That Must Be Explained in the Scientific Article

The manuscript should explain the route-cost epsilon, risk weights, slope-risk exponent, curvature-normalization percentiles, default slope thresholds, minimum mapping area and automatic-threshold strategy.

## 5. Dead or Experimental Code

The legacy `processing/utils.py` module was audited and removed from the active plugin tree after confirming that it was not imported by the production workflow. The removed module contained old helper functions and incomplete experimental stubs such as `find_saddle_points`, `generate_drainage_lines`, `simplify_lines` and `generate_statistics_report`.

| Function | Previous file | Implemented? | Called by active plugin? | Action | Removal risk | Status |
|---|---|---|---|---|---|---|
| `reproject_raster` | `processing/utils.py` | Simple legacy implementation | No | Removed with module | Low | Resolved |
| `calculate_centerline` | `processing/utils.py` | Partial | No | Removed with module | Low/medium | Resolved |
| `find_saddle_points` | `processing/utils.py` | No, returned empty list | No | Removed with module | Low | Resolved |
| `generate_drainage_lines` | `processing/utils.py` | No, returned empty list | No | Removed with module | Low | Resolved |
| `simplify_lines` | `processing/utils.py` | No, returned empty list | No | Removed with module | Low | Resolved |
| `sanitize_geometries` | `processing/utils.py` | Yes, legacy export support | No | Removed with module | Low | Resolved |
| `export_to_format` | `processing/utils.py` | Legacy export helper | No | Removed with module | Low | Resolved |
| `generate_statistics_report` | `processing/utils.py` | No, TODO behavior | No | Removed with module | Low | Resolved |

This cleanup reduces ambiguity for external reviewers and avoids exposing unfinished public functions in a scientific software repository.

## 6. Recommended Corrections

### Urgent Corrections Before Publication

- Keep methodological constants as named constants rather than unexplained inline numbers.
- Document that user-supplied derivative rasters may be aligned to the working grid and that rigorous workflows should generate them on the final DEM grid.
- Document that the least-cost route is isotropic.
- Keep the active plugin tree free of legacy helper modules with TODO stubs. The previous `processing/utils.py` module has been removed after confirming that it was not imported by the production workflow.
- Build publication packages without test folders, backups, bridge logs, cache folders or restore directories.

### Recommended Improvements for the Scientific Article

- Present TopoTrail as a preliminary topographic suitability and route-planning tool, not as a complete walkability model.
- Explicitly describe DEM dependence, scale dependence and sensitivity to derivative rasters.
- Justify study-case thresholds and default parameters.
- Distinguish potential access zones, suitability raster, least-cost route and corridor outputs.
- State that the current least-cost route is isotropic and based on a topographic suitability surface.

### Future Improvements for Version 1.0.0 or Later

- Optional recalculation of slope and curvature from the prepared DEM.
- Optional anisotropic route mode with directional movement cost.
- Advanced methodological presets for risk weighting and route-cost stabilization.
- Keep experimental helper code in a separate development branch until it is fully implemented and tested.
- Automated tests for reversed origin/destination routes.

## 7. Suggested Methodological-Limitations Text

### English

TopoTrail should be interpreted as a preliminary topographic assessment tool for trail and access planning. The current version uses user-supplied DEM, slope and curvature rasters; when these rasters do not share the same grid, CRS, resolution and extent, the plugin may align them to the working grid, which can introduce smoothing in topographic derivatives. The least-cost route is computed over an isotropic cost surface derived from suitability, and therefore does not explicitly distinguish directional uphill and downhill movement costs between cells. Some normalization, numerical-stabilization and risk-weighting constants are empirical modelling choices and should be interpreted as methodological parameters, not universal thresholds of walkability or hazard.

### Portuguese

O TopoTrail deve ser interpretado como uma ferramenta preliminar de avaliacao topografica para planejamento de trilhas e acessos. A versao atual utiliza MDE, declividade e curvaturas fornecidos pelo usuario; quando esses rasters nao compartilham exatamente a mesma grade, CRS, resolucao e extensao, o plugin pode alinha-los ao grid de trabalho, o que pode introduzir suavizacao em derivados topograficos. A rota de menor custo e calculada sobre uma superficie de custo isotropica derivada da adequabilidade, portanto nao diferencia explicitamente o custo direcional de subida e descida entre celulas. Algumas constantes de normalizacao, estabilizacao numerica e ponderacao de risco sao empiricas e devem ser interpretadas como parametros metodologicos do modelo, nao como limiares universais de caminhabilidade ou perigo.

## 8. Final Verdict

Current methodological status: suitable for publication as a preliminary tool with explicit limitations.

Rationale: the main workflow is coherent for topographic multicriteria analysis. It validates and aligns rasters, generates suitability, relative risk, potential access zones, routes and corridors, and includes diagnostic logging for traceability. The external criticisms do not reveal a fatal bug, but they identify real limitations that should be explicit in the manuscript, README and methodology documentation. The previously identified legacy helper module with incomplete stubs has been removed from the active plugin tree. A stable or stronger scientific claim about human movement cost would still require derivative recalculation on the final grid and optional anisotropic movement cost.

---

## 9. What happened since (added 2026-09-14, current version 1.3.0)

Everything above is the 0.5.0 record and is left untouched. This section is the
follow-up: what became of each recommendation, and in which version. The version
of each item was read from `metadata.txt` at the relevant commit, not from
memory.

The two closing sentences of section 8 are the ones to revisit first — **both of
the "would still require" items were done**, in 0.6.0 and 0.6.1 respectively.

| # | Recommendation (section) | Status | Version | Evidence |
|---|---|---|---|---|
| 1 | Optionally recalculate slope and curvature from the prepared DEM (§2, §6) | **Done, and it is now the default** | **0.6.0** | `DERIVE_FROM_DEM` defaults to true; `processing/terrain.py` derives slope and both curvatures on the projected metric working grid, so they are aligned by construction. User-supplied rasters became *optional* inputs. Bilinear alignment still exists, but only for the user who chooses to supply his own. |
| 2 | Optional anisotropic route mode, Tobler-inspired, keeping the isotropic mode (§3, §6) | **Done** | model added in **0.6.1**; default of the four-step window since **0.9.0**; default of the Processing toolbox since **1.2.0** | `ROUTE_COST_TOBLER`; the step cost is Tobler's hiking function and the accumulated cost is in hours. The two isotropic models (inverse, exponential) remain selectable. Section 3 of this document therefore no longer describes the default path. |
| 3 | Keep the mathematical constants as named constants and document them (§4, §6) | **Done** | named by **0.6.x**, documented in **1.3.0** | All of them are module constants: `ROUTE_COST_EPSILON`, `SLOPE_RISK_EXPONENT`, `RISK_SLOPE_WEIGHT`, `RISK_CURVATURE_WEIGHT`, `CURVATURE_RISK_PERCENTILE`, `CURVATURE_SCORE_FLOOR`, `CURVATURE_DEVIATION_PERCENTILE`, `MAX_ROUTE_CROP_CELLS`, `NEAREST_VALID_CELL_RADIUS`, `MIN_ALTITUDE_BAND_SIZE_M`. Each is listed with its value and its role in `METODOLOGIA_TOPOtrail.md`. |
| 4 | `processing/route_scenarios.py` presets should be documented as presets, not thresholds (§4) | **Moot — the module was removed** | **0.12.2** | Commit `cc52ecb`: 902 lines no import ever reached. That row of the §4 table no longer refers to anything. |
| 5 | Document that the least-cost route is isotropic (§6) | **Superseded by item 2** | — | The documentation now describes the anisotropic default. The claim survived in this document, in the Portuguese README and in the user guide until 2026-09; those were corrected, and this document was given the header above instead of being rewritten. |
| 6 | Keep the active tree free of legacy modules with TODO stubs (§5, §6) | **Done, and now enforced** | `tests/test_source_hygiene.py` from **0.5.1**, and its checks grew since | That file fails the build on orphan interface files, on module-level imports of anything QGIS does not ship (added in **0.13.0**) and on `except: pass` (added in **1.1.1**, because the QGIS plugin repository's Bandit scan blocks a release on it). |
| 7 | Build publication packages without test folders, backups, logs, caches (§6) | **Done** | **1.3.0** | `tools/empacotar.py` builds the ZIP from `git archive HEAD` minus the development directories; `tests/test_empacotamento.py` fails if a cache or a test folder reappears, and checks the package is byte-reproducible. |
| 8 | Automated tests for reversed origin/destination routes (§6) | **Done** | **0.7.0** | `tests/test_routing_math.py::test_anisotropic_route_is_direction_dependent` asserts uphill costs more than downhill on the same terrain, and pins the ratio to the closed-form `exp(2·3.5·0.05)`. |
| 9 | Advanced presets for risk weighting and route-cost stabilisation (§6) | **Partly** | **0.6.0–0.6.1** | The cost model and its contrast `k` are user parameters (`ROUTE_COST_MODEL`, `ROUTE_CONTRAST`). The risk weights and the slope-risk exponent are still internal named constants — documented, but deliberately not exposed, for the reason §4 gives. |
| 10 | Explain the constants in the scientific article (§4, §6) | **Done, and they were also measured** | **0.7.0**, **0.8.0** | Five of them were confronted with 224 km of field GPS tracks; `VALIDACAO.md` records what held, what did not, and what remains undetermined — including that the maximum walking speed does not change the route at all, and that the terrain-slowdown magnitude is not resolvable with seven tracks. |
| 11 | Suggested methodological-limitations text (§7) | **Superseded** | — | The current text lives in the README, in `METODOLOGIA_TOPOtrail.md` and in `USUARIO_TOPOtrail.md`. The §7 paragraph describes 0.5.0 and should not be quoted for the current version. |

Two further things in the body are now factually out of date, and are recorded
here rather than edited above:

* §2 says the algorithm **requires** four raster inputs. Since 0.6.0 it requires
  one, the DEM.
* §2 refers to `calculate_slope_degrees` and `calculate_curvature_arrays`. Those
  functions are gone; `processing/terrain.py` has `slope_percent_from_dem` and
  `curvatures_from_dem`, and **slope is expressed in percent, not degrees**.
  The plan curvature also changed in 1.3.0, from the contour curvature of Moore
  et al. (1991) to the tangential curvature of Mitášová & Hofierka (1993).
