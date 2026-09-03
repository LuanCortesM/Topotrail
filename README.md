<h1>TopoTrail</h1>

<p>
  <a href="https://github.com/LuanCortesM/Topotrail/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/LuanCortesM/Topotrail/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://plugins.qgis.org/plugins/TopoTrail/"><img alt="QGIS plugin repository" src="https://img.shields.io/badge/QGIS%20plugins-TopoTrail-589632"></a>
  <a href="LICENSE"><img alt="Licence: MIT" src="https://img.shields.io/badge/licence-MIT-blue"></a>
  <img alt="QGIS 3.22+" src="https://img.shields.io/badge/QGIS-3.22%2B-589632">
</p>

**A QGIS plugin for preliminary planning of trails, access routes and field
movement in natural and protected areas.**

TopoTrail models *topographic suitability* from a Digital Elevation Model (DEM),
slope and terrain curvatures using multicriteria GIS analysis. Its primary
output is a continuous suitability raster. From that raster it also derives
potential access zones, a suggested least-cost route between an origin and a
destination, and an access corridor around that route.

Portuguese documentation is kept in [`docs/pt_BR`](docs/pt_BR). A `PT-BR | ENG`
switch in the interface changes the language of the dialog.

---

## Contents

- [Who this is for](#who-this-is-for)
- [How it relates to existing tools](#how-it-relates-to-existing-tools)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Inputs and outputs](#inputs-and-outputs)
- [How the model works](#how-the-model-works)
- [Methodological limitations](#methodological-limitations)
- [Cartographic interpretation](#cartographic-interpretation)
- [Documentation](#documentation)
- [Support](#support)
- [Contributing](#contributing)
- [Citing TopoTrail](#citing-topotrail)
- [Credits](#credits)
- [Changelog](#changelog)

---

## Who this is for

Protected-area staff, field researchers and technical teams who need to plan how
to reach a point in mountainous terrain, or where a new trail could plausibly
run, **before** a field expedition — and who work in QGIS rather than in a
programming environment.

The concrete problem: in rugged terrain, deciding a route means weighing slope,
elevation and terrain form at once, over an area too large to inspect by eye.
Doing that in QGIS by hand means chaining raster calculator expressions,
reclassifications and cost-distance runs, and repeating the whole chain whenever
a threshold changes. Each run is hard to document and harder to reproduce, so
the reasoning behind a chosen route rarely survives into a report.

TopoTrail packages that chain into a single, parameterised, logged operation.
Every run writes a diagnostic log recording the plugin version, the versions of
its dependencies, every parameter and the distribution statistics of each
intermediate raster — so a route in a report can be traced back to the analysis
that produced it.

**What TopoTrail deliberately does not do:** it does not detect roads, pastures,
existing trails, land cover, watercourses, land tenure or legal restrictions.
Those are complementary layers to overlay in QGIS when the planning objective
requires a broader territorial analysis. A visually open area may not appear as
a potential zone if the relief at that pixel is penalised.

## How it relates to existing tools

Least-cost path analysis on raster surfaces is a mature field, and TopoTrail
does not attempt to replace the general-purpose implementations:

| Tool | What it does | Why TopoTrail exists alongside it |
|---|---|---|
| GRASS `r.walk` / `r.drain` | Anisotropic walking cost with Langmuir/Tobler-type functions, exposed in QGIS through the GRASS provider | More rigorous as a movement model, but it takes an already-built cost surface as input and offers no opinion on how topographic suitability should be derived from a DEM. TopoTrail's contribution is the *upstream* multicriteria step and its documentation. |
| GRASS `r.cost`, SAGA least-cost path | Isotropic accumulated cost from a supplied cost raster | Same: the cost surface is the user's problem. |
| QGIS Least-Cost Path plugins | Route between points on a cost raster | Route only; no suitability model, no zones, no corridor, no provenance log. |
| `leastcostpath` / `gdistance` (R) | Rich movement modelling, including anisotropy | Requires R and a scripting workflow; the target user here works inside QGIS. |

TopoTrail's route search is **isotropic** — cost depends on the cost surface and
step length, and does not distinguish uphill from downhill movement between
adjacent cells. Where a physiological hiking model matters more than the
suitability model, `r.walk` is the better tool, and TopoTrail's suitability
raster can be fed to it as a cost surface.

## Installation

### From the QGIS plugin repository (recommended)

1. In QGIS, open `Plugins > Manage and Install Plugins`.
2. Search for **TopoTrail**.
3. Install and enable it.

### From a ZIP

Download a release ZIP from the
[releases page](https://github.com/LuanCortesM/Topotrail/releases), then
`Plugins > Manage and Install Plugins > Install from ZIP`.

### Requirements

- QGIS **3.22** or later (QGIS 4 / Qt6 supported).
- The QGIS Python environment must provide **GDAL, NumPy, SciPy, Pandas,
  GeoPandas and Shapely**.
- Input rasters must have a defined CRS.

GDAL, NumPy, SciPy and Pandas ship with most QGIS installations. **GeoPandas and
Shapely often do not**, and this is the most common installation failure. Note
that `requirements.txt` documents the version floors — it is not a `pip install`
target, because these libraries have to be installed into the interpreter QGIS
itself uses.

<details>
<summary><b>Windows (OSGeo4W)</b></summary>

Open the **OSGeo4W Shell** from the Start menu (not a regular command prompt),
then:

```bat
python -m pip install geopandas shapely
```

If QGIS was installed through the standalone installer rather than OSGeo4W, use
the `Python Console` inside QGIS to find the interpreter:

```python
import sys; print(sys.executable)
```

and install with that interpreter.
</details>

<details>
<summary><b>Linux</b></summary>

If QGIS came from your distribution's packages, prefer distribution packages so
the GDAL versions match:

```bash
sudo apt install python3-geopandas python3-shapely   # Debian/Ubuntu
```

For a Flatpak QGIS, install inside the Flatpak's own Python environment.
</details>

<details>
<summary><b>macOS</b></summary>

With the official QGIS.app build:

```bash
/Applications/QGIS.app/Contents/MacOS/bin/python3 -m pip install geopandas shapely
```
</details>

Verify from the QGIS Python Console:

```python
import geopandas, shapely, scipy, numpy
print(geopandas.__version__, shapely.__version__, scipy.__version__, numpy.__version__)
```

## Quick start

1. Prepare a **DEM** for your area of interest, in a projected CRS if possible.
2. Derive **slope**, **horizontal curvature** and **vertical curvature** from
   that DEM — ideally on the same grid, resolution, extent and CRS. See
   [`docs/USUARIO_TOPOtrail.md`](docs/USUARIO_TOPOtrail.md) for the exact QGIS
   steps.
3. Open **TopoTrail** from the toolbar or the `TopoTrail` menu.
4. Load the four rasters. The CRS of each is shown next to its field.
5. Set the elevation range and maximum slope for your area. The defaults
   (0–2600 m, 55) come from the Serra da Mantiqueira and are not meaningful
   elsewhere.
6. Optionally set an origin and a destination, by file, by coordinate, or by
   clicking on the map, to get a route and a corridor.
7. Choose an output format and file, and run.

The plugin is also available as a Processing algorithm (`topotrail:topotrail`),
so it can be scripted or placed in a model.

## Inputs and outputs

**Inputs**

- Digital Elevation Model (DEM)
- Slope raster
- Horizontal curvature raster
- Vertical curvature raster
- Optional origin and destination, as point layers, as coordinates in the
  project CRS, or picked from the map canvas

**Outputs**

- Continuous topographic suitability raster
- Vector layer of potential trail and access zones
- Suggested access route, when origin and destination are given
- Access corridor around that route
- Relative topographic risk raster
- Technical diagnostic log

## How the model works

TopoTrail combines Boolean constraints — elevation range and maximum slope —
with a weighted linear combination of topographic criteria. Slope is treated as
a cost criterion; curvatures are scored by proximity to less extreme terrain
forms.

Before any spatial calculation the plugin prepares a projected metric working
CRS. If the DEM is in a geographic CRS, the raster centre is used to choose an
appropriate UTM zone automatically. Slope and curvature rasters are validated
against the DEM and, where necessary, aligned to the same grid, resolution,
extent and CRS.

For stricter scientific use, generate slope and curvature beforehand in the same
CRS, resolution, extent and grid as the working DEM. When the plugin has to
align derived rasters, resampling may smooth local terrain extremes, especially
curvature.

If the DEM has no CRS, strict scientific mode blocks processing with a clear
message: the CRS must be assigned at the data source. An internal non-strict
mode is kept only for diagnostics and may assume `EPSG:4326`; scientific use
should keep strict mode enabled and fix the CRS at the source.

Topographic suitability is calculated as:

```text
S = (w_alt * A + w_slope * D + w_curv_h * CH + w_curv_v * CV) / sum_of_weights
```

where `S` is final suitability, `A` is normalised elevation, `D` is inverted
normalised slope, `CH` and `CV` are curvature scores, and `w` are user-defined
weights. Negative weights are rejected and the sum of weights must be greater
than zero.

> **Note on the altitude weight.** It defaults to `0` on purpose. Elevation
> enters the model as a *constraint* — the elevation range — not as a
> preference. Because normalised elevation increases monotonically, any weight
> above zero means literally "the higher, the better for a trail", which is
> rarely the intent.

The relative topographic risk raster is **not** simply `1 - S`. It combines a
slope-risk term with a curvature/roughness term, using slope relative to the
maximum-slope limit and curvature magnitudes normalised by a robust percentile.
Read it as a complementary layer of relative topographic difficulty.

For planning new trails the most direct product is the access-planning workflow:
the suitability raster becomes a cost surface and the plugin searches for a
least-cost route between origin and destination. Potential zones are spatial
context; the route and corridor are the operational outputs. When the objective
is only to reach a point, disabling vector-zone generation speeds processing up
considerably.

Full formulas, the named empirical constants and the normalisation rules are in
[`docs/METODOLOGIA_TOPOtrail.md`](docs/METODOLOGIA_TOPOtrail.md), and the
critical review of those choices is in
[`docs/METHODOLOGICAL_AUDIT.md`](docs/METHODOLOGICAL_AUDIT.md).

## Methodological limitations

- Results depend directly on DEM quality, resolution and acquisition date.
- Slope and curvature values change with spatial resolution.
- Resampling slope and curvature may smooth terrain extremes; prefer
  derivatives already aligned to the DEM.
- The route model is **isotropic** and does not distinguish directional uphill
  and downhill cost.
- The route search is confined to a rectangle around origin and destination,
  expanded by the search margin. A globally cheaper path that leaves that
  rectangle will not be found.
- The 8-neighbour grid quantises route direction to multiples of 45°, which
  slightly overestimates the length of diagonal, staircase-like paths.
- Some cost, risk and normalisation constants are empirical modelling decisions
  and should be reported when the results are published.
- User-defined weights require methodological justification.
- Topographic suitability does not replace field validation.
- Vegetation, hydrology, land tenure, legal restrictions, roads, existing
  trails, pastures and environmental constraints are not considered.
- KML is a visualisation format; prefer GeoPackage for analysis.

## Cartographic interpretation

Use the suitability raster as a semi-transparent layer over satellite imagery or
a base map. Vector zones are a generalisation of the raster above the selected
threshold, so they can look fragmented when the minimum-area filter is too low.
For presentation maps, raise the minimum area and prefer GeoPackage. For field
access planning, prioritise the suggested route and corridor.

In high mountains, keep elevation-band balancing enabled. It prevents a single
global threshold from selecting only low, gentle terrain, preserving the best
relative cells within each elevation band.

## Documentation

| Document | Contents |
|---|---|
| [`docs/USUARIO_TOPOtrail.md`](docs/USUARIO_TOPOtrail.md) | Step-by-step user guide |
| [`docs/METODOLOGIA_TOPOtrail.md`](docs/METODOLOGIA_TOPOtrail.md) | Formulas, constants, normalisation |
| [`docs/METHODOLOGICAL_AUDIT.md`](docs/METHODOLOGICAL_AUDIT.md) | Critical review of the modelling choices |
| [`docs/qgis4/`](docs/qgis4) | QGIS 4 / Qt6 migration notes and manual checklist |
| [`docs/pt_BR/`](docs/pt_BR) | Portuguese reference copies of all of the above |

## Support

Open an [issue](https://github.com/LuanCortesM/Topotrail/issues). There are
templates for bug reports, methodological questions and feature requests.

When something fails, attach the `*_diagnostico_topotrail.log` file the plugin
writes next to your output. It is by far the most useful thing you can send.

## Contributing

Contributions are welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md) for the
development setup, the checks that run on every pull request, and what a good
bug report contains. Participation is governed by the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Citing TopoTrail

Citation metadata is in [`CITATION.cff`](CITATION.cff); GitHub renders a
ready-made citation from it in the sidebar.

## Configuration and security

TopoTrail requires no API keys, tokens or environment variables.

Never commit real credentials, `.env` files, access tokens, private keys,
certificates, local QGIS profiles, field datasets or generated analysis outputs.
If a future integration needs configuration through environment variables,
commit only a `.env.example` with placeholder values.

## Credits

**Developer:** Luan da Silva Cortes Maciel (MACIEL, L. S.)

**Advisor:** Leandro Freitas

**Context:** developed as a product of the author's master's research in
Biodiversity in Protected Areas, associated with the Escola Nacional de Botânica
Tropical and the Instituto de Pesquisas Jardim Botânico do Rio de Janeiro.

**Associated project:** Herpeto Mantiqueira.

## Changelog

### 0.5.1

- QGIS 4 / Qt6 compatibility improved while preserving QGIS 3.22+ support.
- Responsive interface for small screens, high-DPI scaling, horizontal scrolling
  and dark/light QGIS themes.
- The plugin metadata no longer marks the plugin as experimental.
- Interface text encoding corrected: accented Portuguese strings that had been
  re-encoded as Latin-1 now display correctly.
- Repository: continuous integration, automated consistency tests, contribution
  guidelines, issue templates and citation metadata added.

### 0.5.0

- English documentation promoted to primary for publication and external review.
- Portuguese reference copies preserved in `docs/pt_BR`.
- `PT-BR | ENG` language switch added to the interface.
- Legacy incomplete helper code removed from the active plugin tree.
- The validated suitability, relative-risk, route and corridor workflow was
  preserved.

### 0.4.0

- Initial public beta.

## Licence

MIT — see [`LICENSE`](LICENSE).
