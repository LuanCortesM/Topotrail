# TOPO_TRAIL_METHODOLOGICAL_AUDIT.md

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
