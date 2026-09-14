# TopoTrail User Guide

For version **1.3.0**. Everything below was checked against the plugin as it
ships: the window, the Processing algorithm and the messages it actually prints.

## What it is

TopoTrail is a QGIS plugin for the technical planning of trails, access routes
and field movement in natural and protected areas. It answers one question —
*what does the relief allow?* — from a single Digital Elevation Model, and it
writes down how it got there.

It comes in two forms, which do the same thing:

* a **four-step window**, for someone who does not know the model;
* a **Processing algorithm**, `topotrail:topotrail`, with all 45 parameters
  exposed, so it can be scripted or dropped into a model.

## Requirements

* QGIS **3.22** or later, up to QGIS 4.
* Nothing to install. GDAL/OGR, NumPy and SciPy all ship with QGIS, and the
  plugin uses nothing else.
* A DEM with a defined CRS. Any CRS works — a geographic one is reprojected to
  the local UTM zone automatically — but the CRS has to be *declared*. A raster
  with none is refused, and the fix is at the data source.

## What you have to supply, and what you do not

**Required**

* A Digital Elevation Model. **That is all.** Slope, both curvatures,
  ruggedness, the wetness index and the drainage network are all derived from
  it.

**Optional**

* Your own slope and curvature rasters, if you would rather control how they
  are derived. Tick *I already have slope and curvature rasters* in step 1; you
  then have to declare the slope unit (percent or degrees) and accept that grids
  differing from the DEM are resampled onto it, which smooths local extremes.
  Leaving it unticked is the recommendation, and the default.
* Any raster as an extra weighted criterion — stoniness, vegetation cover, a
  ready-made cost surface — with a declared direction: high values good, or
  high values bad.
* A vector layer to keep away from: a fence, a closed area, private land. Either
  excluded outright or merely made expensive.
* An origin and a destination for the route, plus a point layer of intermediate
  destinations in visiting order.

If your DEM is in **feet** — still common in the United States — say so with the
DEM vertical unit. Read as metres, a Colorado scene is thrown away entirely and
the run fails with a message that never mentions elevation.

## The seven products

The first two are always produced. The rest are ticked in step 2.

| Product | File | What it is |
|---|---|---|
| Topographic suitability | `…_adequabilidade.tif` | 0–1 per cell, the weighted combination of the criteria from step 3. |
| Relative topographic risk | `…_risco_topografico.tif` | 0–1 per cell, a separate indicator of relative difficulty — not the complement of suitability. |
| Transitability classes | `…_transitabilidade.tif` | Five absolute slope classes, with the colours and the legend written into the file in the language of the run. |
| Potential access zones | `….gpkg` / `.shp` / `.kml` | Polygons with `value`, `area_m2`, `area_ha`. |
| Suggested route | `…_rota.gpkg` | `compr_m`, `tempo_h`, `tempo_hms`, `tempo_campo_h`, `ganho_m`, `perda_m`, altitudes, number of legs. |
| Access corridor | `…_corredor.gpkg` | Buffer of the route, `buffer_m` being the **radius**. |
| Watercourse crossings | `…_travessias.gpkg` | One point per crossing: basin area, class, cost factor, field-check warning. |

Plus `…_diagnostico_topotrail.log`: one JSON record per stage, with the plugin
version, the versions of Python, GDAL and the operating system, every parameter
as it was resolved and the statistics of every intermediate raster. **Attach it
to any bug report**, and keep it beside any figure you publish — it is what lets
someone else reproduce the run.

## Using the window

Open **TopoTrail** from the toolbar or the `TopoTrail` menu. The window is a
four-step wizard: *Data → Products → Criteria → Run*.

### Step 1 — Data

Choose the DEM. A chip beside the file says whether it has a CRS and what units
it is in. The vertical unit of the DEM (metres or feet) is here, and so is the
*Your own rasters* card described above, unticked by default.

### Step 2 — Products

Suitability and risk are always produced. Four more are optional:

* **potential access zones**, the best areas as polygons, for clipping and area
  measurement;
* **the transitability map**, the "where can I walk" map;
* **watercourses extracted from the DEM**, which enables the graded crossings
  and is what makes the crossings layer exist. Be careful in seasonally dry
  landscapes: a dry bed is often the best walking surface there;
* **the route**, with its corridor.

For a route, give an origin and a destination — by file, by typing X, Y in the
project CRS, or by clicking on the map — and, if you like, a point layer of
intermediate destinations. **Feature order is the order of the traverse**, or you
can let the plugin choose the cheapest order, exactly, for up to eight points.

Intermediate destinations are how you chain objectives: climb one summit, then
another, call at a spring. Without them the algorithm skirts the high ground, and
it is right to — going over a summit is not the cheapest way to get past it.

### Step 3 — Criteria and limits

**The defaults are conservative starting points, not calibrated values, and the
window says so.** Tune them to your terrain and report the ones you use.

* **Weights** of the six criteria. Zero switches a criterion off. Altitude is
  zero on purpose: elevation enters as a *range*, not as a preference, and any
  weight above zero means "the higher, the better for a trail". Wetness and
  ruggedness are also zero by default, so that existing results do not move
  under anyone; wetness requires the DEM drainage to be enabled.
* **Terrain limits**: the elevation range, the maximum admissible slope (above
  it a cell is unusable — 100% is 45°), and the slope at which the slope score
  reaches zero. If most of your area exceeds that last one, the criterion stops
  telling one hillside from another, and the plugin warns you when that happens.
* **How the zones are cut**: the cut percentile (75 keeps the best quarter of the
  area; lower is more permissive), the minimum patch area, and whether the
  percentile is taken within each elevation band — which is on by default, and
  stops a high scene selecting only its valley floors.
* **The transitability breaks**: four increasing percentages separating the five
  classes, 20, 35, 60 and 100 by default.
* **The route**: the cost model, the corridor radius and the lateral search
  margin. Too small a margin forces a straight route; too large is slow.
* **Constraints** and the **additional criterion**, both optional.

The elevation range deserves a second look outside the Serra da Mantiqueira, for
which the 0–2600 m defaults were written. Elsewhere they quietly delete the study
area: 52% of an Alpine scene, 85% of an Andean one, 87% of a Himalayan one. The
plugin now reports how much it discarded, in which direction, and the DEM's
actual range — read that line.

### Step 4 — Review and run

Choose the output file and the vector format, check the summary of what will be
produced, and run. The computation happens in the background and QGIS stays
usable; the progress panel shows the messages as they come. The results are
loaded into the project, styled.

## Reading the route

The route carries **two durations, for the same line**. `tempo_h` is Tobler
pace — an unburdened walker on an existing path, maximum 6 km/h on a gentle
descent. `tempo_campo_h` is the same route rescaled to 2.4 km/h, the median pace
measured on timed field-survey tracks. The path is identical in both
cases: maximum speed changes the duration, not the alignment. Neither is a
schedule.

`ganho_m` and `perda_m` are accumulated ascent and descent along the line;
`desnivel_max_m` is the older quantity, the range up to the highest point, kept
because it is not the same thing.

Route lengths carry a known bias of up to 8.2%, from routing over an eight-cell
neighbourhood, and differences of that order between two alignments are not
interpretable as differences in terrain.

## Using it from a script

```python
import processing

processing.run("topotrail:topotrail", {
    "INPUT_DEM": "/path/to/dem.tif",
    "DERIVE_FROM_DEM": True,
    "START_POINT_FILE": "/path/to/origin.geojson",
    "END_POINT_FILE": "/path/to/destination.geojson",
    "ROUTE_COST_MODEL": 2,          # 2 = walking time (Tobler), the default
    "STREAMS_FROM_DEM": True,       # off by default; needed for the crossings
    "OUTPUT_FILE": "/path/to/out.gpkg",
    "OUTPUT_FORMAT": 1,             # 1 = GeoPackage
    # …
})
```

Two details that are not obvious: `START_POINT_FILE` and `END_POINT_FILE` are
**file paths**, not layers, and `ROUTE_COST_MODEL` is an enum whose default, 2,
is Tobler.

A complete, runnable call with **all 45 parameters written out and commented**,
a small DEM to run it on and the output values to check against, is in
[`../exemplo/`](../exemplo/README.md).

## Common errors, and what they mean

| Message | What to do |
|---|---|
| *This raster has no CRS defined* | Assign the coordinate system at the data source. Strict mode blocks the run on purpose. |
| *A route needs both an origin and a destination* | One of the two points is missing. |
| *You ticked that you will use your own rasters…* | Untick the box, or supply slope **and** both curvatures. |
| *At least one weight must be greater than zero* | All six weights are zero; there is nothing to combine. |
| *Transitability breaks must be four increasing numbers* | Four values, increasing, separated by commas. |
| *Minimum altitude must be lower than maximum* | The elevation range is inverted. |
| *No navigable pixel meets the route constraints* | The maximum slope is excluding everything between the two points. Raise it. |
| *Could not connect the route points* | No path of usable cells exists. The message lists the four usual causes and the adjustment for each: raise the maximum slope, switch the constraint to "penalise", raise the fordable ceiling, or widen the search margin. |
| *The two points connect only through a vertex contact* | Different problem, and raising the slope limit will not fix it: somewhere on the way two impassable cells touch diagonally and the gap has zero width. Reduce the minimum patch area, increase the distance kept from constraints, or use a higher-resolution DEM in which the real gap is more than one cell wide. |
| *The DEM has N cells; deriving terrain would need about X GB* | Clip the DEM to the area of interest, or resample to a larger cell. |
| The output file cannot be written | The file is open in QGIS, or the folder is not writable. |

The plugin also emits warnings that are not errors and are worth reading: cells
discarded by the elevation range, the fraction of the scene where weights had to
be renormalised, a cell size too coarse for the transitability classes, a
criterion raster carrying undeclared NoData sentinels, and the scene having lost
its discriminating power.

## Limits of what the result means

* Results depend directly on the DEM's quality, resolution and acquisition date.
  Over forest, most global DEMs give the canopy, not the ground.
* The class distribution of the transitability map depends strongly on cell size.
  Quote the cell size beside any number taken from it.
* The risk raster is relative **to the scene analysed**. It is not an absolute
  hazard map and two scenes' values are not comparable.
* The weights, the slope limit and the cut percentile are your judgement, and
  the route depends appreciably on them. Report the values you used — the
  diagnostic log has them all.
* The plugin does not know about vegetation, roads, existing trails, pastures,
  land tenure or legal restrictions, and the only hydrography it knows is what
  it derives from the DEM. Cross these outputs with those layers in QGIS.
* A suggested route is a topographic hypothesis. It should be assessed by
  someone who knows the ground, and walked, before operational use.
* Every watercourse crossing is estimated from relief alone. Depth and current
  change with the season and the rain: check them in the field.

## Where to go next

* [`METODOLOGIA_TOPOtrail.md`](METODOLOGIA_TOPOtrail.md) — formulas, named
  constants, normalisation rules.
* [`METHODOLOGICAL_AUDIT.md`](METHODOLOGICAL_AUDIT.md) — a critical review of
  those choices, including where they are weak. It audits version 0.5.0 and is
  kept as a dated record; read its closing section for what changed since.
* [`VALIDACAO.md`](VALIDACAO.md) — what field GPS tracks said about the
  empirical constants, including where they contradicted the plugin.
* [`../exemplo/README.md`](../exemplo/README.md) — a worked example you can run
  and check.
