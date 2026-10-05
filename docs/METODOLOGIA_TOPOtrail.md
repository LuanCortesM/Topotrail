# TopoTrail Methodology

Formulas, named empirical constants and normalisation rules, as implemented in
version **1.4.0**. Every statement here was checked against `processing/` in
this repository; where a constant is named, the name is the one used in the
code, so it can be found and read in context.

A critical review of these modelling choices — what they assume, and where they
are known to be weak — is a separate document,
[`METHODOLOGICAL_AUDIT.md`](METHODOLOGICAL_AUDIT.md). Note that it audited
**version 0.5.0** and is kept as a dated record, not as a description of the
current model; its closing section says which of its recommendations were
implemented and in which version. The empirical calibration of the constants
against field GPS tracks is in [`VALIDACAO.md`](VALIDACAO.md), which likewise
carries the plugin version behind each figure.

## What the model is for, and what it is not

TopoTrail models **topographic** suitability for movement on foot and for the
preliminary planning of trails and access routes. The unit of analysis is the
relief, represented by a Digital Elevation Model. The DEM is the only required
input; every other terrain attribute is derived from it.

The plugin does not model complete territorial walkability. It does not
recognise roads, existing trails, pastures, land cover, land tenure or legal
restrictions, and the hydrography it knows is the one it extracts from the DEM.
Those themes are complementary and belong on top of these outputs in QGIS. A
visually walkable pasture may therefore score poorly if, topographically, its
slope, curvature or threshold behaviour is unfavourable. That is a difference
between topographic suitability and observed walkability, not automatically a
bug.

## The seven products

| Product | What it is |
|---|---|
| Topographic suitability | Continuous 0–1 raster, the weighted combination below. |
| Relative topographic risk | Continuous 0–1 raster, a separate indicator — **not** `1 − S`. |
| Transitability classes | Five absolute slope classes with a written legend. |
| Potential access zones | Polygons above a suitability threshold, with area. |
| Suggested route | Least-cost line between an origin and one or more destinations. |
| Access corridor | Metric buffer around the route. |
| Watercourse crossings | One point per crossing the route makes, graded and flagged. |

Plus a **JSON diagnostic log**, one record per stage, described at the end.

## Working CRS and preparation of the DEM

Slope, curvature, area, distance and movement cost only mean anything in metric
units, which is a condition on the CRS the computation happens in. The plugin
checks it and corrects it:

* a DEM in a geographic CRS is reprojected to the UTM zone of the scene's
  geometric centre, the hemisphere chosen from the sign of the latitude. Above
  84° of latitude, outside UTM's domain, the run continues with a warning that
  distortion may be large and that a polar system is preferable;
* a DEM in a projected but non-metric CRS — feet, or a Mercator whose scale
  varies with latitude — is likewise reprojected, with an explicit warning;
* rotated grids, or grids with non-square cells, are resampled to a square,
  north-up grid, because finite-difference gradients assume that;
* with `STRICT_CRS_MODE` on, which is the shipped default, a DEM with **no**
  CRS stops the run: the CRS must be fixed at the data source.

**Working cell (since 1.4.0).** By default the reprojection lets GDAL choose the
cell size and the grid origin from the extent of the input, so two clips of the
same geographic DEM are resampled onto different cells (measured: 29.6084,
29.6098 and 29.6142 m, with origins offset by 3 to 21 m, for clip margins of
3.4–3.6 km around the same trail). Every derived attribute then differs cell by
cell, and where two corridors have almost the same cost the route can switch
between them. `WORKING_CELL_M > 0` fixes the cell and aligns the grid to its own
multiples (`gdal.Warp(..., xRes=c, yRes=c, targetAlignedPixels=True)`); a
projected DEM is then also resampled to that cell. Any clip of the same DEM
lands on the same cells, and the interior of the analysis no longer depends on
the extent of the clip.

Optional slope and curvature rasters of your own are validated against the DEM
and aligned to its grid, resolution, extent and CRS where necessary. Alignment
resamples, and resampling smooths local extremes, curvature most of all — so for
strict scientific use, generate them beforehand on the working grid, or let the
plugin derive them, which is the default and guarantees the grid by
construction.

## NoData

NoData becomes NaN and propagates as NaN through the whole chain, instead of
entering the arithmetic as if it were a valid elevation. The gradient at the
edge of a NoData region uses only the neighbours that exist — one-sided where
that is the case. Without that care, the difference between a real elevation and
a fill value produces spurious slopes of hundreds of percent exactly at the
boundaries of the scene, which is where a route usually enters and leaves.

## Derived terrain attributes

### Slope

Slope is expressed **in percent** — 100 times the tangent of the angle of
steepest descent, so 100% is 45°, not in degrees:

```text
D = 100 * sqrt( (dz/dx)^2 + (dz/dy)^2 )
```

Percent is the plugin's internal unit throughout. A slope raster supplied by the
user is declared in percent or degrees with the `SLOPE_UNIT` parameter and
converted; the unit cannot be inferred, because below 45 the two occupy the same
numeric range.

### Curvatures

The two curvatures are the **tangential** (`Ch`, called horizontal in the
interface) and **profile** (`Cv`, vertical) normal curvatures, in m⁻¹, in the
forms of Mitášová & Hofierka (1993), with `p = (dz/dx)^2 + (dz/dy)^2`:

```text
Ch = (zxx*zy^2 - 2*zxy*zx*zy + zyy*zx^2) / ( p * (1 + p)^(1/2) )
Cv = (zxx*zx^2 + 2*zxy*zx*zy + zyy*zy^2) / ( p * (1 + p)^(3/2) )
```

Two implementation decisions change these numbers and have to be declared.

**Tangential, not contour curvature.** Up to version 1.2.0 the plan curvature
was the geometric contour curvature of Moore, Grayson & Ladson (1991), which has
`p^(3/2)` in the denominator and therefore diverges as the gradient goes to
zero: on flat ground the contour closes ever tighter, so a perfectly gentle cell
gets an extreme value even though the surface there is not abrupt at all. Since
the model scores shape by proximity to zero, the effect was perverse — the
gentlest terrain, which is what the model means to reward, received the worst
shape score. Measured on the Mantiqueira scene of the dissertation, the
correlation between log-slope and the shape score was +0.58; with the tangential
curvature it falls to +0.06. Corrected in 1.3.0.

**One operator for all three second derivatives.** The central-difference
gradient operator is applied twice, so `zxx`, `zyy` and `zxy` all come from the
same operator. The cost is attenuation — the derivatives are evaluated over a
two-cell step, preserving 40.5% of the amplitude of four-cell forms and 81.1% of
eight-cell forms, which is real attenuation at the scale of the spurs and
saddles that decide where a trail goes. The benefit is that the discrete Hessian
stays near rank one over surfaces with straight contours, so the tangential
curvature of a smooth hillside stays small at any orientation. Replacing only
the pure derivatives with a three-point stencil improves short-form resolution
and makes that second property more than twenty times worse. The choice was to
measure both and keep the declared attenuation rather than trade it for an
orientation-dependent artefact.

Sign convention, verified against surfaces of known shape in
`tests/test_terrain_math.py`: **convex** forms — domes, ridges, spurs — are
negative; **concave** forms — basins, hollows, channels — are positive; the
tangential curvature is exactly zero on a cylindrical ridge, whose contours are
straight. Where the gradient is zero the curvature is undefined and the model
assigns zero, which is the criterion's best score — a choice that favours flat
terrain and is worth remembering in low relief.

### Ruggedness

Ruggedness is the **Vector Ruggedness Measure** of Sappington, Longshore &
Thompson (2007), `vector_ruggedness()`: each cell becomes the unit vector normal
to the surface, the 3×3 neighbourhood's vectors are summed, and the index is one
minus the modulus of the resultant divided by the number of normals. It is
**dimensionless, in [0, 1]**, and it is zero on a plane however steep that plane
is. That decoupling from slope is the whole point: it is what separates a smooth
grassy hillside from a boulder field at the same average inclination.

`roughness_index()` — the Terrain Ruggedness Index of Riley, DeGloria & Elliot
(1999), the mean absolute elevation difference to the eight neighbours, in
metres — is also implemented and is **not** what the model uses. TRI is not
independent of slope: on a perfectly smooth 80% ramp it reads 6.00 m against
3.36 m on a noisy surface averaging 27%. It is kept as the citable standard and
as a measure of local amplitude.

### Hydrology

Depressions are filled by **Priority-Flood with epsilon**, which imposes a
strictly descending surface and is exact (Barnes, Lehman & Mulla 2014). Flow is
routed by **D8** (O'Callaghan & Mark 1984): each cell drains to its steepest
downslope neighbour, diagonal steps weighted by √2 so a diagonal is not treated
as an orthogonal one. Accumulation is propagated in descending elevation order
and gives the contributing area of each cell; cells above the basin-area
threshold (`STREAM_MIN_BASIN_KM2`, default 1 km²) are the channel network. The
threshold is a real methodological choice and should be reported; drainage
density is the useful check on it, and it falls as the working cell grows, so
the plugin reports both together.

The **topographic wetness index** is `ln(a / tan β)` (Beven & Kirkby 1979),
computed from the same accumulation, so it costs almost nothing once the
drainage has been extracted.

## Suitability: the multicriteria combination

Every criterion becomes a score between 0 and 1 before being combined.

| Criterion | How it is scored | Default weight |
|---|---|---|
| Slope `D` | Linear between 0 and `SLOPE_SCORE_MAX`, then **inverted**: flat is 1, at the limit is 0. | 1.0 |
| Elevation `A` | Linear between `ALT_MIN` and `ALT_MAX`. | **0.0** |
| Tangential curvature `CH` | Proximity to zero, see below. | 1.0 |
| Profile curvature `CV` | Proximity to zero, see below. | 1.0 |
| Wetness `W` | Robust normalisation of the TWI, inverted — drier is better. | **0.0** |
| Ruggedness `R` | Robust normalisation of the VRM, inverted — smoother is better. | **0.0** |
| Any extra raster | Normalised, with a declared direction (higher is better, or worse). | **0.0** |

Curvature scoring: the score is `floor + (1 - floor) * (1 - min(|C - 0| / L, 1))`
where the floor is `CURVATURE_SCORE_FLOOR = 0.2` and the tolerated deviation `L`
is the 99th percentile (`CURVATURE_DEVIATION_PERCENTILE`) of the scene's own
deviations, unless fixed with `CURVH_LIMIT` / `CURVV_LIMIT`. Wetness and
ruggedness are normalised by the 95th percentile of their absolute values
(`CURVATURE_RISK_PERCENTILE`), unless fixed with `WETNESS_LIMIT` /
`ROUGHNESS_LIMIT`. These four values depend on the extent of the scene; every
run records the ones it used in the log (`limites_normalizacao`), so that a
study can fix them across clips of the same area. The preferred terrain is the gently shaped one, neither strongly
concave nor strongly convex, and the most extreme forms still score 0.2 rather
than 0.

The suitability `S` of a cell is the weighted mean of the scores available for
it:

```text
S = sum( w_i * N_i ) / sum( w_i )
```

**The sum of weights is computed cell by cell, not once for the scene.** That
matters where a criterion does not cover the whole grid — an extra raster of
smaller extent, or the wetness index at the edges: the uncovered cell is scored
by the criteria it actually has, with the weights renormalised, instead of
receiving zero for the absence, which would be to penalise it with the worst
possible score. Where renormalisation affects an appreciable part of the scene,
the plugin warns and advises caution in comparing cells. Negative weights are
rejected and the sum of weights must be greater than zero.

**On the elevation weight.** It defaults to 0 on purpose. Elevation enters the
model as a *constraint* — the elevation range — not as a preference. Because
normalised elevation increases monotonically, any weight above zero means
literally "the higher, the better for a trail", which is rarely the intent.

Two Boolean constraints act before the score is used: the elevation range
(`ALT_MIN`, `ALT_MAX`) and the maximum slope (`SLOPE_MAX`). Cells outside them
are excluded from the zones, and cells above `SLOPE_MAX` are not navigable by
the route.

## Relative topographic risk

A separate indicator built from the same criteria, and not the complement of
suitability:

```text
risk = 0.75 * clip(D / SLOPE_MAX, 0, 1)^1.35  +  0.25 * (Ch' + Cv') / 2
```

where `Ch'` and `Cv'` are the curvature magnitudes normalised by the 95th
percentile of their own absolute values (`CURVATURE_RISK_PERCENTILE`). The
exponent `SLOPE_RISK_EXPONENT = 1.35` makes slopes close to the limit weigh
disproportionately. The weights are `RISK_SLOPE_WEIGHT = 0.75` and
`RISK_CURVATURE_WEIGHT = 0.25`. It is by construction **relative to the scene
analysed**, not an absolute measure of danger, and the exponents and weights are
empirical constants of the model that should be declared whenever the values are
quoted.

## Transitability classes

Different in nature from suitability, which is continuous and relative. The base
is five classes set by four **absolute** slope thresholds,
`DEFAULT_SLOPE_BREAKS = (20, 35, 60, 100)` percent, exposed as the
`TRANSITABILITY_BREAKS` parameter:

| Class | Slope | Label (pt / en) |
|---|---|---|
| 1 | < 20% | Suave / Gentle |
| 2 | 20–35% | Moderada / Moderate |
| 3 | 35–60% | Forte / Steep |
| 4 | 60–100% | Muito forte / Very steep |
| 5 | > 100%, or blocked | Escarpada / Escarpment |

Absolute is the point: a class must mean the same thing in the Mantiqueira and
in the Andes, or two maps cannot be compared. **The labels describe the slope,
not a verdict on the walker.** An earlier version called class 5 impassable, and
25 113 GPS fixes on ground demonstrably walked falsified that: the steepest
ground actually walked was 115.8%, inside class 5. The thresholds were kept and
the wording rewritten; a test stops the old claim coming back. The labels live in
`i18n/*.json` in all six languages — that is their single source — and are
filled in with the thresholds actually used by the run, so the legend cannot
contradict the data it describes.

Three modifiers act on the base class, and have to be declared alongside any
number taken from the map:

* ruggedness above the scene's 90th percentile (`ROUGHNESS_PERCENTILE`) demotes
  a cell one class;
* wetness above the 95th (`WETNESS_PERCENTILE`) demotes a cell one class;
* a cell blocked by a constraint goes straight to class 5.

The first two never create class 5 — rough or waterlogged ground is worse to
walk on, but it is not a rock face — and they are scene-relative on purpose:
absolute ruggedness depends on DEM resolution and TWI on basin size, so a fixed
threshold for them would not transfer. The consequence is that strict
comparability between scenes holds for the slope classification, not for the
final map.

Above `COARSE_CELL_WARNING_M = 60 m` of cell size, the plugin warns that the
classification is describing the average landscape rather than the terrain a
person meets: on the same ground, going from 30 m to 250 m moves 27 percentage
points of area into class 1.

The legend is written into the output raster, in the language of the run, and it
is written twice because GeoTIFF has no standard place for category names. GDAL
puts the category names in the `*.tif.aux.xml` beside the raster, which is what
QGIS reads to build the legend; the same five labels also go in as the GDAL
metadata items `TOPOTRAIL_CLASSE_1` to `TOPOTRAIL_CLASSE_5`, which the GTiff
driver stores in the `GDAL_METADATA` tag **inside** the `.tif`, together with the
colour table. A `.tif` separated from its sidecar therefore keeps both its
colours and the meaning of each one.

## Potential access zones

Cells whose suitability is above a threshold, vectorised into polygons carrying
`value`, `area_m2` and `area_ha`. The threshold is either declared
(`THRESHOLD`) or, when that is zero, taken from a percentile of the scene's own
suitability (`AUTO_PERCENTILE`, default 75). With `ALTITUDE_BAND_THRESHOLD` on —
which is the default, and applies only to the automatic threshold — the
percentile is taken **within each elevation band** of `ALTITUDE_BAND_SIZE_M`
(default 200 m, minimum 50 m), so that a high scene does not select only its
valley floors. Patches smaller than `MIN_PATCH_AREA_HA` (default 50 ha) are
dropped.

## Cost surface, route and corridor

The route can be computed under **three cost models**. `ROUTE_COST_MODEL`
selects them and the shipped default, in both the window and the Processing
toolbox, is Tobler.

**Inverse**, `1 / (S + 0.05)` (`ROUTE_COST_EPSILON`). The model of the 0.5.x
versions, kept for continuity and with a diagnosed defect: the contrast it
appears to offer assumes `S` spanning the whole of [0, 1], whereas in a real
scene the distribution is concentrated in the middle. On the Mantiqueira scene
the 5th percentile of suitability is 0.49 and the 95th is 0.77, so the cost
between those percentiles varies by a factor of only 1.5 — too flat to be worth
a detour.

**Exponential**, `exp(k * (1 - S))`, with `k = ROUTE_CONTRAST`, default
`DEFAULT_ROUTE_CONTRAST = 6.0`. Preserves contrast however compressed the
distribution is, and makes `k` an explicit control of how much a detour is
worth.

**Walking time (Tobler), the default and the recommended model.** Here the cost
stops being dimensionless and becomes hours. The time of a step of horizontal
length `L` and elevation change `Δz` is Tobler's (1993) hiking function times a
terrain slowdown:

```text
t = (L/1000) / ( 6.0 * exp(-3.5 * |Δz/L + 0.05|) )  *  slowdown
slowdown(cell) = 1 + 2.0 * (1 - S)
```

with `TOBLER_MAX_SPEED_KMH = 6.0`, `TOBLER_DECAY = 3.5`,
`TOBLER_OPTIMUM_SLOPE = 0.05` and `TERRAIN_SLOWDOWN_MAX = 2.0`. The slowdown
actually charged for a step is the **mean of the two cells'** slowdowns, so
perfect terrain walks at Tobler speed and the worst terrain takes three times as
long. The first factor is anisotropic — maximum speed is on a gentle descent, at
`Δz/L = −0.05`, not on the flat — and that asymmetry is exactly what an
isotropic surface cannot express.

Two things follow from the structure and are worth stating. Multiplying the
maximum speed by a constant divides every cost by the same constant, so **the
chosen path is bit-for-bit identical**; only the estimated duration scales. The
route therefore also carries `tempo_campo_h`, the same route rescaled to
`FIELD_SURVEY_SPEED_KMH = 2.4`, the median pace measured in field survey work.
And Tobler describes an unburdened walker on an existing path: it estimates
relative effort, not a schedule.

### The search

The path is found by **A\*** over the eight-cell neighbourhood, with a heuristic
built from the minimum time per metre in the scene, which keeps it admissible
and consistent and therefore keeps the result optimal. An eight-cell
neighbourhood imposes a known directional bias: a path at 22.5° to the grid axes
comes out up to 8.2% longer than the distance it represents (Rees 2004; Medrano
2021). Route lengths should be read with that margin, and differences of that
order between two alignments are not interpretable as differences in terrain.

**The diagonal step rule (since 1.3.0).** A diagonal step crosses the vertex
shared by four cells, and two of them are neither the step's origin nor its
destination: they are the cells it goes around. Looking only at the destination
cell — what the implementation did up to 1.2.0, as do many eight-neighbour
implementations — lets the route escape through a passage of zero width between
two cells declared impassable, and lets it cross a channel without landing on
any channel cell, so the ford factor is not charged and the crossing never
reaches the list checked in the field. Since 1.3.0 a diagonal step exists only
where there is a way round it: both flanking orthogonal cells must be passable,
and where the higher of their crossing factors exceeds the factor the step's own
two cells already charge, the step pays the difference as well. A cell
outside the search window is not a barrier — it is terrain the window does not
cover. When two points stop connecting because of this, the error message says
that what is missing is width, and not admitted slope.

### Several destinations

With intermediate destinations the route is the concatenation of consecutive
legs, which is optimal given the order. Asked to optimise the order
(`OPTIMISE_ORDER`), it is solved **exactly** by the dynamic programming of Held
& Karp (1962), treated as a directed Hamiltonian path, because the cost matrix
is asymmetric in the time model — going up and coming down do not cost the same.
The limit of `MAX_OPTIMISED_WAYPOINTS = 8` intermediate points does not come
from the dynamic programme, which takes microseconds at eight, but from building
the cost matrix, which needs of the order of n² complete A\* runs.

### Corridor

A metric buffer around the route, with the radius declared by the user
(`ROUTE_BUFFER_M`, default 100 m) — a radius of 100 m therefore produces a
corridor 200 m wide.

### Alternatives corridor (since 1.4.0)

The route is the single cheapest path, and nothing in it says how much cheaper
it is than the next one. With `ROUTE_ALTERNATIVES_PCT = p > 0` the plugin
computes, on the same graph as the A\* (same eight steps, same corner rule, same
anisotropic Tobler time and ford factors), the accumulated cost from the origin
`d_o(x)` and the accumulated cost to the destination `d_d(x)` — a complete
Dijkstra each way, the second on the reversed graph, because walking time
depends on direction. With `C*` the optimal cost:

```text
slack(x) = (d_o(x) + d_d(x)) / C* - 1
corridor = { x : slack(x) <= p / 100 }
```

`slack(x)` is how much costlier the best path *through x* is than the route. The
corridor is a union of origin–destination paths, hence connected, and always
contains the route; for several legs it is the union per leg. It is the
least-cost corridor of connectivity planning (Beier et al. 2008), here on the
anisotropic walking-time graph. Outputs: `…_alternativas.gpkg`, with `area_ha`
and `afastamento_max_m` (the largest distance from the route to a corridor
cell), and `…_folga.tif`, `slack` in percent up to `3p`. When
`afastamento_max_m > max(4 · ROUTE_BUFFER_M, 10 cells)` the run warns that the
route is ill-determined. With SciPy the two Dijkstras run in
`scipy.sparse.csgraph`; without it, in Python on the same edge list. The grid is
capped at `MAX_ALTERNATIVES_CELLS = 4 000 000` cells.

## Graded watercourse crossings

Where drainage extraction is on, each channel cell receives a cost multiplier as
a function of the contributing area of the basin upstream. The DEM knows neither
discharge nor season; it knows contributing area, and hydraulic geometry ties one
to the other — channel width and discharge grow with drainage area as a power law
(Leopold & Maddock 1953; Faustini, Kaufmann & Herlihy 2009, bankfull width
W ~ A^0.5 in wadeable US rivers).

| Class | Contributing area | Treatment |
|---|---|---|
| Headwater channel | < 2 km² | cost × 2 |
| Stream | 2–10 km² | cost × 4 |
| Small river | 10 km² up to the fordable ceiling | cost × 8 |
| River | above the ceiling (`STREAM_FORD_MAX_KM2`, default 50 km²) | barrier; the crossing is not presumed |

`FORD_CLASSES` holds the first three. The classes are a **declared proxy, not a
safety measurement**: every crossing the route actually makes comes out in its
own vector layer with the contributing area, the class, the factor applied and a
field-check warning, so the decision goes back to whoever is going to walk it
instead of staying hidden inside the cost.

A user-supplied constraint layer is separate from this. It is buffered by
`CONSTRAINT_BUFFER_M` (default 30 m) and then either excluded outright
(`CONSTRAINT_AVOID`, the default) or made expensive by
`CONSTRAINT_PENALTY_FACTOR = 8.0` (`CONSTRAINT_PENALISE`). Drainage as a
constraint is **off** by default, and that is an evidential decision, not an
oversight: on the caatinga field tracks the real routes crossed 1.37 channels per
km against 0.68 for the straight line between the same endpoints. There is no
revealed avoidance to calibrate — see [`VALIDACAO.md`](VALIDACAO.md), §6 and
§8.4.

## The diagnostic log

Every run writes `*_diagnostico_topotrail.log`: one JSON record per stage,
carrying the plugin version, the versions of Python, GDAL and the operating
system, **all 45 parameters as they were resolved**, and the distribution
statistics of every intermediate raster — including the cost model actually used
and the seven weights. It is what lets a route shown in a report be traced back
to the analysis that produced it, and it is the intended way for a third party to
reproduce a run. `exemplo/` contains a complete worked example with the expected
output values.

## Named empirical constants

All of them live in `processing/algorithm.py` unless marked otherwise. They are
modelling decisions, not measurements, except where
[`VALIDACAO.md`](VALIDACAO.md) says otherwise — and they should be reported
alongside any result taken from the plugin.

| Constant | Value | What it sets |
|---|---|---|
| `CURVATURE_SCORE_FLOOR` | 0.2 | Lowest score an extreme curvature can get. |
| `CURVATURE_DEVIATION_PERCENTILE` | 99.0 | Curvature deviation tolerated in the suitability score. |
| `CURVATURE_RISK_PERCENTILE` | 95.0 | Curvature normalisation in the risk indicator. |
| `SLOPE_RISK_EXPONENT` | 1.35 | Convexity of the slope term of the risk indicator. |
| `RISK_SLOPE_WEIGHT` / `RISK_CURVATURE_WEIGHT` | 0.75 / 0.25 | Split of the risk indicator. |
| `ROUTE_COST_EPSILON` | 0.05 | The `eps` of the inverse cost model. |
| `DEFAULT_ROUTE_CONTRAST` | 6.0 | Default `k` of the exponential cost model. |
| `TOBLER_MAX_SPEED_KMH` | 6.0 | Tobler's maximum speed. Does not change the path. |
| `TOBLER_DECAY` | 3.5 | Tobler's decay. Confirmed against seven real tracks. |
| `TOBLER_OPTIMUM_SLOPE` | 0.05 | Gradient of maximum speed, a gentle descent. |
| `FIELD_SURVEY_SPEED_KMH` | 2.4 | Measured field-survey pace, for the second duration. |
| `TERRAIN_SLOWDOWN_MAX` | 2.0 | Maximum terrain slowdown. Existence validated; magnitude not resolvable between 2.0 and 4.0. |
| `CONSTRAINT_PENALTY_FACTOR` | 8.0 | Cost factor of a penalised constraint. Not calibrated; see `VALIDACAO.md` §8.4. |
| `FORD_CLASSES` | 2 / 10 km², ×2 ×4 ×8 | Crossing classes by contributing area. |
| `DEFAULT_STREAM_FORD_MAX_KM2` | 50.0 | Default fordable ceiling; above it, a barrier. |
| `MAX_OPTIMISED_WAYPOINTS` | 8 | Ceiling for exact visiting-order optimisation. |
| `DEFAULT_SLOPE_BREAKS` (`transitability.py`) | 20, 35, 60, 100 % | The four transitability thresholds. |
| `ROUGHNESS_PERCENTILE` (`transitability.py`) | 90.0 | Ruggedness above which a cell is demoted one class. |
| `WETNESS_PERCENTILE` (`transitability.py`) | 95.0 | Wetness above which a cell is demoted one class. |
| `COARSE_CELL_WARNING_M` (`transitability.py`) | 60.0 | Cell size above which the classification is warned about. |
| `SATURATION_WARNING_FRACTION` / `MIN_SCORE_AMPLITUDE` | 0.40 / 0.05 | When the plugin warns that the model has stopped discriminating. |
| `NEAREST_VALID_CELL_RADIUS` / `NEAREST_VALID_CELL_WARN_M` | 30 cells / 100.0 m | How far a route endpoint may be moved to a valid cell, and when that is warned about. |
| `WARN_TERRAIN_CELLS` / `MAX_TERRAIN_CELLS` (`terrain.py`) | 8e6 / 1e8 | Grid sizes at which deriving terrain is warned about, then refused. |

## Limitations

* A poor DEM produces a poor result; nothing downstream repairs it.
* Slope, curvature and ruggedness change with spatial resolution, and the
  transitability distribution changes a great deal. Quote the cell size beside
  any number taken from these maps.
* Over forest, most global DEMs give the canopy, not the ground. Attributes
  computed in a 3×3 window partly sample the interpolator, not the microrelief.
* The eight-cell neighbourhood biases route length by up to 8.2%.
* The curvature operator attenuates short forms, by the amounts stated above.
* Where the gradient is zero the curvature is undefined and scored as the best
  possible value, which favours flat ground in low relief.
* The risk indicator is relative to the scene, never an absolute hazard map.
* The weights, the slope limit and the cut-off percentile are the user's
  judgement, not calibrated defaults, and require justification. What *was*
  calibrated against real tracks is two internal constants of the cost model —
  the decay of the walking function and the maximum terrain slowdown — which do
  not appear among the weights.
* Duration in Tobler pace is an estimate of relative effort, not a schedule:
  against field GPS it is optimistic by a factor of 1.7 to 3.1.
* Hydrography, existing trails, roads, land cover, tenure, vegetation and legal
  restrictions are complementary to this topographic core, and belong on top of
  it in QGIS.
* None of this replaces field validation.

## References

Barnes, R., Lehman, C. & Mulla, D. (2014) Priority-flood: an optimal
depression-filling and watershed-labeling algorithm for digital elevation models.
*Computers & Geosciences* 62: 117–127.

Beier, P., Majka, D.R. & Spencer, W.D. (2008) Forks in the road: choices in
procedures for designing wildland linkages. *Conservation Biology* 22: 836–851.
https://doi.org/10.1111/j.1523-1739.2008.00942.x

Beven, K.J. & Kirkby, M.J. (1979) A physically based, variable contributing area
model of basin hydrology. *Hydrological Sciences Bulletin* 24: 43–69.

Faustini, J.M., Kaufmann, P.R. & Herlihy, A.T. (2009) Downstream variation in
bankfull width of wadeable streams across the conterminous United States.
*Geomorphology* 108: 292–311.

Held, M. & Karp, R.M. (1962) A dynamic programming approach to sequencing
problems. *Journal of the SIAM* 10: 196–210.

Leopold, L.B. & Maddock, T. (1953) *The hydraulic geometry of stream channels and
some physiographic implications*. USGS Professional Paper 252.

Medrano, F.A. (2021) Effects of raster terrain representation on GIS shortest
path analysis. *PLOS ONE* 16: e0250106.

Mitášová, H. & Hofierka, J. (1993) Interpolation by regularized spline with
tension: II. Application to terrain modeling and surface geometry analysis.
*Mathematical Geology* 25: 657–669.

Moore, I.D., Grayson, R.B. & Ladson, A.R. (1991) Digital terrain modelling.
*Hydrological Processes* 5: 3–30.

O'Callaghan, J.F. & Mark, D.M. (1984) The extraction of drainage networks from
digital elevation data. *Computer Vision, Graphics, and Image Processing* 28:
323–344.

Rees, W.G. (2004) Least-cost paths in mountainous terrain. *Computers &
Geosciences* 30: 203–209.

Riley, S.J., DeGloria, S.D. & Elliot, R. (1999) A terrain ruggedness index that
quantifies topographic heterogeneity. *Intermountain Journal of Sciences* 5:
23–27.

Sappington, J.M., Longshore, K.M. & Thompson, D.B. (2007) Quantifying landscape
ruggedness for animal habitat analysis. *Journal of Wildlife Management* 71:
1419–1426.

Tobler, W. (1993) *Three presentations on geographical analysis and modeling*.
NCGIA Technical Report 93-1.
