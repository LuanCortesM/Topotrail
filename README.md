# TopoTrail

TopoTrail is a QGIS plugin for preliminary planning of trails, access routes and field movement in natural areas and protected areas.

The plugin models **topographic suitability** from a Digital Elevation Model (DEM), slope and terrain curvatures using multicriteria GIS analysis. Its main output is a continuous topographic suitability raster. From this raster, TopoTrail can also generate potential access zones, a suggested least-cost route between origin and destination, and an access corridor around that route.

TopoTrail does not automatically detect roads, pastures, existing trails, land cover, watercourses, land tenure or legal restrictions. These layers are complementary and should be overlaid later in QGIS when the planning objective requires a broader territorial analysis.

Portuguese documentation is preserved in [`docs/pt_BR`](docs/pt_BR).

## Version Status

Current version: `0.5.0`.

This is an experimental version for topographic suitability testing. Use the results as preliminary technical support and validate them in the field before any operational decision.

The graphical interface includes a simple `PT-BR | ENG` language switch for Portuguese and English use.

## Changelog

### 0.5.0

- English documentation is now the primary documentation for publication and external review.
- Portuguese reference copies are preserved in `docs/pt_BR`.
- The graphical interface includes a `PT-BR | ENG` language switch.
- Legacy incomplete helper code was removed from the active plugin tree.
- The validated topographic suitability, relative-risk, route and corridor workflow was preserved.

Repository: https://github.com/LuanCortesM/Topotrail

Issues and suggestions: https://github.com/LuanCortesM/Topotrail/issues

## Installation for Testing

1. Download the published `TopoTrail.zip` file.
2. In QGIS, open `Plugins > Manage and Install Plugins`.
3. Choose `Install from ZIP`.
4. Select `TopoTrail.zip`.
5. Enable the TopoTrail plugin.

Main requirements:

- QGIS 3.22 or later.
- QGIS Python environment with GDAL, NumPy, SciPy, GeoPandas and Shapely available.
- DEM and auxiliary rasters with a defined CRS.

## Configuration and Security

TopoTrail does not require API keys, tokens or environment variables for normal use.

Never commit real credentials, `.env` files, access tokens, private keys, certificates, local QGIS profiles, field datasets or generated analysis outputs. If future integrations require configuration through environment variables, commit only a safe `.env.example` file with placeholder values.

## Credits

Developer: Luan da Silva Cortes Maciel (MACIEL, L. S.)

Advisor: Leandro Freitas

Context: developed as a product of the author's master's research in Biodiversity in Protected Areas, associated with the Escola Nacional de Botanica Tropical and Jardim Botanico do Rio de Janeiro.

Associated project: Herpeto Mantiqueira.

## Inputs

- Digital Elevation Model (DEM)
- Slope raster
- Horizontal curvature raster
- Vertical curvature raster
- Optional origin and destination points for access route planning
- Origin and destination coordinates, or direct point capture from the QGIS map canvas

## Outputs

- Continuous topographic suitability raster
- Vector layer with potential trail and access zones
- Suggested access route when origin and destination are provided
- Access corridor around the suggested route
- Relative topographic risk raster
- Technical diagnostic log

## Methodological Overview

TopoTrail combines Boolean constraints, such as elevation range and maximum slope, with a weighted linear combination of topographic criteria. Slope is treated as a cost criterion, while curvatures are scored according to proximity to less extreme terrain forms.

Before spatial calculations, the plugin prepares a projected metric working CRS. If the DEM is in a geographic CRS, the raster center is used to automatically choose an appropriate UTM zone. For southeastern Brazil this usually results in EPSG:32723, but the rule is generic for other hemispheres and longitudes. Slope and curvature rasters are validated against the DEM and, when necessary, aligned to the same grid, resolution, extent and CRS.

For stricter scientific use, slope and curvature rasters should preferably be generated beforehand in the same CRS, resolution, extent and grid as the working DEM. When the plugin needs to align these derived rasters, resampling may smooth local terrain extremes, especially curvatures. The current version preserves compatibility with the four user-supplied rasters; automatic recalculation of derivatives from the reprojected DEM is planned as a future improvement.

If the DEM has no CRS, strict scientific mode blocks processing with a clear message: the correct CRS must be assigned at the data source before analysis. An internal non-strict mode is kept only for diagnostics/compatibility and may assume `EPSG:4326`; scientific use should keep strict mode enabled and correct the CRS at the source.

Topographic suitability is calculated as:

```text
S = (w_alt * A + w_slope * D + w_curv_h * CH + w_curv_v * CV) / sum_of_weights
```

Where `S` is final suitability, `A` is normalized elevation, `D` is inverted normalized slope, `CH` is horizontal curvature score, `CV` is vertical curvature score, and `w` are user-defined weights. Negative weights are rejected and the sum of weights must be greater than zero.

The relative topographic risk raster is not simply `1 - S`. It combines slope risk with a curvature/roughness component, using slope relative to the maximum slope limit and curvature magnitudes normalized by a robust percentile. It should therefore be read as a complementary layer of relative topographic difficulty.

For planning new trails, the most direct product is the access-planning workflow: the suitability raster is converted into a cost surface and the plugin searches for a least-cost route between origin and destination. Potential zones should be read as spatial context; the route and corridor are the most direct outputs for field access planning. When the objective is only to reach a point, disabling vector-zone generation can speed up processing.

The least-cost route in the current version is isotropic: movement cost depends on the cost surface and step distance, but it does not explicitly distinguish uphill and downhill movement between adjacent cells. Therefore, the route should be interpreted as a preliminary topographic least-cost path, not as a complete physiological hiking model.

## Methodological Limitations

- Results depend directly on DEM quality, resolution and acquisition date.
- Slope and curvature values change with spatial resolution.
- Resampling slope and curvature rasters may smooth terrain extremes; prefer derivatives already aligned to the DEM.
- The current route model is isotropic and does not distinguish directional uphill and downhill costs.
- Some cost, risk and normalization constants are empirical modelling decisions and should be reported in scientific articles or technical reports.
- User-defined weights require methodological justification.
- Topographic suitability does not replace field validation.
- The plugin does not automatically consider vegetation, hydrology, land tenure, legal restrictions, roads, existing trails, pastures or environmental constraints.
- Additional thematic layers should be integrated later in QGIS when the objective requires territorial analysis.
- KML should be treated as a visualization format; GeoPackage is preferred for analysis.

## Cartographic Interpretation

The suitability raster should be used as a semi-transparent layer over satellite imagery or a base map. Vector zones are a generalization of the raster above the selected threshold; therefore, they can appear fragmented when the minimum-area filter is too low. For presentation maps, use a higher minimum area and prefer GeoPackage. For field access planning, prioritize the suggested route and corridor.

When working with high mountains, keep elevation-band balancing enabled. This mode prevents a global threshold from selecting only low and gentle terrain, preserving the best relative cells within higher elevation bands.
