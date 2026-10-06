---
title: 'TopoTrail: a QGIS plugin for DEM-based topographic suitability and least-cost route planning'
tags:
  - QGIS
  - Python
  - geomorphometry
  - least-cost path
  - multicriteria analysis
  - protected areas
  - trail planning
authors:
  - name: Luan da Silva Cortes Maciel
    orcid: 0009-0002-7242-9650
    affiliation: 1
affiliations:
  - name: Escola Nacional de Botânica Tropical, Instituto de Pesquisas Jardim Botânico do Rio de Janeiro, Brazil
    index: 1
date: 14 September 2026
bibliography: paper.bib
---

# Summary

Planning a trail, an access route, or the movement of a field team in rugged
terrain begins with a question that is purely geometric: what does the relief
allow? `TopoTrail` is a QGIS plugin that answers that question from a single
Digital Elevation Model (DEM). It derives slope, tangential and profile
curvature, terrain ruggedness, a topographic wetness index and the drainage
network itself; combines them into a continuous topographic suitability surface
by weighted multicriteria analysis; and returns seven coordinated products: the
suitability raster and its complement as relative topographic risk; a
trafficability map in five absolute slope classes, whose legend is written into
the GeoTIFF in the language of the run; potential access zones as polygons with
area; a least-cost route between an origin and one or more declared
destinations, costed as walking time through Tobler's anisotropic hiking
function [@tobler1993]; a metric corridor around that route; and the watercourse
crossings the route makes, each one listed with its contributing area and
flagged for field checking. Every run writes a JSON diagnostic log recording the
plugin version, the versions of its dependencies, all fifty-two parameters and
the distribution statistics of every intermediate raster, so that a route
printed in a report can be traced back to the analysis that produced it.

The plugin is available both as a four-step wizard and as a Processing algorithm
(`topotrail:topotrail`), so it can be scripted or embedded in a model. It runs on
QGIS 3.22 through QGIS 4, in six interface languages, and requires nothing beyond
the NumPy [@harris2020] and GDAL/OGR [@gdal2024] that every QGIS [@qgis2023]
installation ships; SciPy [@virtanen2020] is used when present, with an
equivalent NumPy implementation where it is not.

# Statement of need

Protected-area staff and field researchers who need to decide how to reach a
point in rugged terrain — or where a new trail could plausibly run — generally
work inside QGIS rather than in a programming environment. Doing this analysis by
hand means chaining raster-calculator expressions, reclassifications and
cost-distance runs, then repeating the whole chain whenever one threshold
changes. Each run is hard to document and harder to reproduce, so the reasoning
behind a chosen route rarely survives into a report. The consequence is not only
inefficiency: in a protected area a trail is a permanent intervention whose
alignment governs erosion and habitat fragmentation for decades
[@tomczyk2013; @snyder2008], and the evidence behind that alignment ought to be
auditable. `TopoTrail` packages the chain into a single parameterised, logged
operation and documents every empirical constant it uses.

# State of the field

Least-cost path analysis on raster surfaces is mature, and `TopoTrail` does not
replace the general-purpose implementations. GRASS `r.walk` and `r.drain`,
exposed in QGIS through the GRASS provider, model anisotropic walking cost more
rigorously than this plugin does; GRASS `r.cost` and the SAGA least-cost path
tools compute isotropic accumulated cost; the R packages `leastcostpath` and
`gdistance` offer rich movement modelling. All of them, however, take an
already-built cost surface as input and offer no opinion on how topographic
suitability should be derived from a DEM. Existing QGIS least-cost path plugins
route between points on a supplied cost raster and produce neither a suitability
model, nor zones, nor a corridor, nor a provenance log. `TopoTrail`'s
contribution is the upstream, documented multicriteria step and the reproducible
chaining of the whole sequence for a QGIS user, following the precedent of
plugins such as SZ for landslide susceptibility [@titti2022]. Where a
physiological hiking model matters more than the suitability model, `r.walk`
remains the better tool, and `TopoTrail`'s suitability raster can be fed to it as
a cost surface.

# Implementation

Terrain attributes follow the differential definitions of @mitasova1993 and
@moore1991. Plan curvature is the tangential (normal contour) curvature rather
than the geometric contour curvature, because the latter diverges as the
gradient goes to zero and would make the shape criterion reward steep ground.
Depressions are filled with the Priority-Flood algorithm [@barnes2014] and flow
is routed with D8 [@ocallaghan1984]; the topographic wetness index follows
@beven1979 and ruggedness the vector measure of @sappington2007. Watercourse
crossings are graded by contributing area as a proxy for channel size, following
hydraulic geometry [@leopold1953; @faustini2009], so that a stream is a graded
cost rather than an absolute barrier — and each crossing the route makes is
reported instead of being hidden inside the cost. Routes are found by A\* search
[@hart1968] over the cost surface, on an eight-neighbour grid in which a
diagonal step is allowed only where there is room to pass outside it, so that a
route cannot slip through the vertex where two impassable cells meet. When
several intermediate destinations are declared, their optimal visiting order is
solved exactly by dynamic programming [@heldkarp1962]. Criteria are combined by
weighted linear combination in the standard GIS multicriteria form
[@saaty1977; @malczewski2006], with per-cell weight renormalisation where a
criterion does not cover a pixel.

A single least-cost line can hide that it is ill-determined: two corridors whose
costs differ by a fraction of a percent are equally good answers, and a minimal
perturbation of the input switches one for the other. The plugin can therefore
also return the near-optimal corridor, every cell lying on some path at most a
chosen percentage costlier than the optimum, from forward and backward
accumulated-cost surfaces over the same anisotropic step model, in the manner of
the least-cost corridors of connectivity planning [@beier2008]. A related source
of irreproducibility is the working grid: a geographic DEM reprojected to UTM is
resampled onto a grid whose cell and origin follow the extent of the clip, so two
clips of the same area yield different cells. A fixed, target-aligned working
cell removes that dependence; on field cases where the route changed with the
clip margin it became identical across margins. The test suite runs in
continuous integration both without QGIS and inside official QGIS 3.22, 3.44 and
4.2 images, driving the Processing algorithm, the wizard and the packaged
plugin.

# Research application

`TopoTrail` was developed as a product of the author's master's research in
Biodiversity in Protected Areas (ENBT/JBRJ), associated with the Herpeto
Mantiqueira project. Its empirical constants were calibrated, and its class
legend revised, against 88 km of walked field GPS tracks recorded in two
Brazilian biomes; that validation is reported separately (Maciel, in
preparation). The plugin is distributed through the official QGIS plugin
repository and each release is archived on Zenodo.

# Acknowledgements

I thank Sabrina Barros da Silva, who recorded the caatinga GPS tracks during the
botanical inventory of her own dissertation and shared them for the analyses on
which the entire empirical calibration of this software rests, Leandro Freitas
for supervising the research of which the software is a product, the Escola
Nacional de Botânica Tropical and the Instituto de Pesquisas Jardim Botânico do
Rio de Janeiro for institutional support, and the Herpeto Mantiqueira field teams
for the Serra da Mantiqueira tracks. Parts of the implementation were written with the assistance of a large
language model used as a programming tool; all methodological decisions, and
responsibility for the correctness of the result, are the author's.

# References
