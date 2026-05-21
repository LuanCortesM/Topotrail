# TopoTrail Methodology

## Conceptual Model

TopoTrail combines topographic criteria to estimate relative suitability for field movement and to support preliminary planning of trails and access routes.

## TopoTrail as Topographic Suitability Analysis

The methodological objective of TopoTrail is to model topographic suitability for preliminary planning of new trails. The main unit of analysis is terrain represented by a Digital Elevation Model (DEM), combined with slope, terrain curvatures, suitability, relative topographic risk, potential zones, routes and access corridors.

The plugin does not model complete territorial walkability. It does not automatically recognize roads, existing trails, pastures, open areas, land cover, land tenure, hydrology or legal restrictions. These themes are complementary and should be overlaid later in QGIS when planning requires a broader territorial interpretation.

Thus, a visually walkable road or pasture may be classified as less favorable if, from a topographic perspective, it has unfavorable slope, curvature, risk, fragmentation, NoData or threshold behavior. This difference should be interpreted as a distinction between topographic suitability and observed/territorial walkability, not automatically as a software bug.

TopoTrail outputs are defensible as preliminary technical topographic layers. Final decisions should integrate other thematic layers and field validation.

## Metric CRS

Slope, curvature, area, distance, route and corridor calculations depend on metric units. Processing should therefore occur in a projected CRS.

## Reprojection to UTM

When the input is in a geographic CRS, the working UTM CRS can be chosen from the raster center. Southern hemisphere rasters use EPSG:327xx; northern hemisphere rasters use EPSG:326xx.

## Raster Alignment

Auxiliary rasters should share CRS, dimensions, resolution, extent and GeoTransform with the reference DEM.

In the current version, slope and curvature rasters are mandatory user-supplied inputs. If these derived rasters are not in the same grid as the working DEM, the plugin may align them to allow processing. This operation solves spatial compatibility, but it may smooth local slope/curvature extremes. For scientific analysis, the recommended procedure is to generate derivatives directly from the corrected DEM in the final analysis grid.

## NoData

NoData is converted to NaN in numerical arrays. Invalid pixels must not enter suitability calculations as valid values.

## Slope

Slope should consider the real pixel size:

```text
dy, dx = np.gradient(dem, pixel_size_y, pixel_size_x)
slope = degrees(arctan(sqrt(dx^2 + dy^2)))
```

## Curvatures

Horizontal and vertical curvatures are treated as normalized/scored topographic criteria, respecting NoData and spatial resolution.

## Multicriteria Suitability

The main combination is:

```text
S = (w_alt * A + w_slope * D + w_curv_h * CH + w_curv_v * CV) / sum_of_weights
```

Where:

- `S`: final suitability;
- `A`: normalized elevation;
- `D`: inverted normalized slope;
- `CH`: horizontal curvature score;
- `CV`: vertical curvature score;
- `w`: user-defined weight.

## Relative Topographic Risk

Risk is treated as a relative indicator derived from topographic criteria and suitability. It should be interpreted as technical support, not as an absolute hazard map. The weights and exponents used in the risk curve are empirical constants in the current model and should be described in any report or article when results are used scientifically.

## Least-Cost Route

The route uses a cost surface derived from suitability and topographic criteria. NoData or blocked cells must not be crossed. The current algorithm is isotropic: transition cost uses the mean cost between cells and the step length, with no explicit directional penalty for uphill or downhill movement. An anisotropic mode should be treated as a future improvement because it changes outputs, parameters and methodological interpretation.

## Corridor

The corridor is a metric buffer around the route. Its width is interpreted in meters.

## Limitations

- Poor DEM quality produces poor results.
- Spatial resolution changes slope and curvature values.
- Resampling derived rasters may smooth topographic peaks and extremes.
- The current route model is isotropic and does not model directional differences between ascending and descending terrain.
- Empirical constants for cost, risk and normalization must be justified in the methodological text.
- Weights are subjective and must be justified.
- Results do not replace field validation.
- Layers such as hydrology, existing trails, roads, land cover, land tenure, vegetation and legal restrictions are complementary to the topographic core and can be integrated in QGIS according to the study objective.
