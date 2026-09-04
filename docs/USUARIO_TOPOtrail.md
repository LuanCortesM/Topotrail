# TopoTrail User Guide

## What It Is

TopoTrail is a QGIS plugin designed to support technical planning of trails, access routes and field movement in natural areas and protected areas.

## What It Does

The plugin uses terrain, elevation, slope and curvatures to generate:

- a topographic suitability raster;
- a relative topographic risk raster;
- potential zones;
- a least-cost route between origin and destination;
- a corridor around the route.

## TopoTrail as Topographic Suitability Analysis

TopoTrail models topographic suitability for preliminary planning of new trails. It uses DEM, slope, curvatures, relative topographic risk, suitability, zones, routes and corridors to indicate where terrain tends to be more or less favorable.

The plugin does not automatically recognize roads, pastures, existing trails, land cover, land tenure, hydrology or legal restrictions. These layers can be overlaid later in QGIS as complementary analyses, according to the planning objective.

Therefore, a visually open area, such as a pasture or road, may not appear as potential if the terrain in that pixel is penalized by slope, curvature, risk, threshold behavior, NoData or the minimum-area filter. This does not automatically mean a plugin error: the correct question is whether the exclusion is consistent with the calculated topographic suitability.

Results should be interpreted as a preliminary topographic basis. For operational decisions, TopoTrail outputs should be crossed with hydrology, existing trails, roads, land cover, protected areas, legal restrictions and field validation.

## Requirements

- QGIS 3.22 or later.
- GDAL, NumPy and SciPy — all shipped with QGIS itself; nothing extra to install.
- DEM with a defined CRS.

## Inputs

- Elevation DEM.
- Slope raster.
- Horizontal curvature raster.
- Vertical curvature raster.
- Criteria weights.
- Origin and destination points, when generating a route.
- Output file/folder.

## CRS Care

Terrain, area, distance, route and corridor calculations require a projected CRS in meters. If the DEM is in a geographic CRS, processing prepares a metric working CRS when applicable. A raster without CRS should be corrected at the source before scientific use.

## Outputs

- Suitability: continuous values indicating topographically more favorable areas.
- Relative topographic risk: indicator derived from the topographic criteria.
- Zones: optional polygons of favorable areas.
- Route: suggested access line.
- Corridor: polygon around the route.
- Technical diagnostic log.

## How to Use

1. Open QGIS.
2. Enable the TopoTrail plugin.
3. Open the interface from the TopoTrail menu.
4. Select the required rasters.
5. Configure weights and parameters.
6. Provide origin and destination if you want a route.
7. Choose the output file.
8. Run the tool and review the generated layers.

## Methodological Limitations

- Results depend on DEM quality and resolution.
- Slope and curvature should preferably be in the same CRS, resolution, extent and grid as the DEM; if the plugin needs to align them, topographic derivatives may be smoothed.
- The suggested route is isotropic in the current version: it uses the cost surface and step distance, but does not explicitly differentiate uphill and downhill movement.
- Internal cost, risk and normalization constants are empirical choices of the preliminary model and should be cited in scientific use.
- Weights require technical justification.
- Topographic suitability does not replace field validation.
- The plugin does not automatically consider vegetation, hydrology, private property, legal restrictions, roads, pastures or existing trails; these layers are complementary and can be overlaid in QGIS.
- Suggested routes should be evaluated by a specialist before operational use.

## Common Errors

- Raster without CRS.
- Misaligned rasters.
- Weights summing to zero.
- Origin without destination or destination without origin.
- Output path without write permission.
- Files already loaded in QGIS blocking overwrite.
