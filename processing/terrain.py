"""Terrain derivatives computed from the working DEM.

TopoTrail historically required the user to supply slope and both curvatures as
separate rasters. That requirement was the single largest barrier to using the
plugin: it forced three Processing runs before the tool could be opened, and it
made the result depend on choices the plugin could not see -- the unit of the
slope raster (degrees or percent), the sign convention and magnitude scale of
the curvature provider, and whether the derived rasters shared the DEM's grid.

Deriving them here removes all four problems at once. The derivatives are
computed on the projected metric working DEM, so pixel spacing is in metres and
the same everywhere, and they are aligned to the DEM by construction.

Only NumPy is required; nothing here touches QGIS or GDAL.
"""

import numpy as np


def _metric_spacing(transform):
    pixel_size_x = abs(float(transform[1]))
    pixel_size_y = abs(float(transform[5]))
    if pixel_size_x <= 0 or pixel_size_y <= 0:
        raise ValueError(
            "Resolucao espacial invalida no GeoTransform para derivar o relevo."
        )
    return pixel_size_x, pixel_size_y


def _filled_for_gradient(dem_array):
    """Replace invalid cells with the mean so np.gradient does not spread NaN.

    The invalid cells are masked back out by the caller; filling only keeps a
    single NaN from contaminating its whole neighbourhood.
    """
    dem = dem_array.astype(np.float64)
    valid = np.isfinite(dem)
    fill = float(np.nanmean(dem[valid])) if np.any(valid) else 0.0
    return np.where(valid, dem, fill), valid


def slope_percent_from_dem(dem_array, transform, feedback=None):
    """Slope as a percentage: 100 * tan(angle of steepest descent).

    Percentage is TopoTrail's internal unit. A 45 degree slope is 100%.
    """
    px, py = _metric_spacing(transform)
    filled, valid = _filled_for_gradient(dem_array)
    dz_dy, dz_dx = np.gradient(filled, py, px)
    slope = (np.hypot(dz_dx, dz_dy) * 100.0).astype(np.float32)
    slope[~valid] = np.nan
    slope[~np.isfinite(slope)] = np.nan
    if feedback:
        finite = slope[np.isfinite(slope)]
        if finite.size:
            feedback.pushInfo(
                "Declividade derivada do MDE ({:.1f} x {:.1f} m): "
                "p50={:.1f}%, p95={:.1f}%, max={:.1f}%".format(
                    px, py, float(np.percentile(finite, 50)),
                    float(np.percentile(finite, 95)), float(finite.max()))
            )
    return slope


def curvatures_from_dem(dem_array, transform, feedback=None):
    """Plan (horizontal) and profile (vertical) curvature, Zevenbergen-Thorne.

    These are the two curvatures the multicriteria model expects, and they are
    defined relative to the direction of steepest descent rather than to the
    grid axes:

    * **plan** curvature is measured across the slope. It is positive on
      diverging terrain (ridges and spurs, where flow spreads out) and negative
      on converging terrain (hollows and channels, where flow concentrates).
    * **profile** curvature is measured along the slope. It describes whether
      the terrain is accelerating (convex breaks) or decelerating (concave
      footslopes) downhill.

    Both are returned in units of 1/m. Their absolute scale does not matter to
    the suitability model, which normalises each by a percentile of its own
    distribution and scores cells by distance from zero -- so a provider using
    a different scale, or the opposite sign convention, produces the same
    result. Flat cells, where the curvature is undefined, are returned as zero.

    Reference: Zevenbergen, L.W. & Thorne, C.R. (1987) Quantitative analysis of
    land surface topography. Earth Surface Processes and Landforms 12: 47-56.
    """
    px, py = _metric_spacing(transform)
    filled, valid = _filled_for_gradient(dem_array)

    zy, zx = np.gradient(filled, py, px)
    zyy, zyx = np.gradient(zy, py, px)
    _, zxx = np.gradient(zx, py, px)

    p = zx ** 2 + zy ** 2          # squared gradient magnitude
    q = p + 1.0

    with np.errstate(divide="ignore", invalid="ignore"):
        plan = np.where(
            p > 1e-12,
            (zxx * zy ** 2 - 2.0 * zyx * zx * zy + zyy * zx ** 2) / np.power(p, 1.5),
            0.0,
        )
        profile = np.where(
            p > 1e-12,
            (zxx * zx ** 2 + 2.0 * zyx * zx * zy + zyy * zy ** 2) / (p * np.power(q, 1.5)),
            0.0,
        )

    curv_h = plan.astype(np.float32)
    curv_v = profile.astype(np.float32)
    for array in (curv_h, curv_v):
        array[~valid] = np.nan
        array[~np.isfinite(array)] = np.nan

    if feedback:
        for name, array in (("horizontal (plan)", curv_h), ("vertical (profile)", curv_v)):
            finite = array[np.isfinite(array)]
            if finite.size:
                feedback.pushInfo(
                    "Curvatura {} derivada do MDE: p05={:.4g}, p50={:.4g}, p95={:.4g}".format(
                        name, float(np.percentile(finite, 5)),
                        float(np.percentile(finite, 50)), float(np.percentile(finite, 95)))
                )
    return curv_h, curv_v


def derive_terrain(dem_array, transform, feedback=None):
    """Slope (percent) plus both curvatures, from one DEM in a metric CRS."""
    slope = slope_percent_from_dem(dem_array, transform, feedback)
    curv_h, curv_v = curvatures_from_dem(dem_array, transform, feedback)
    return slope, curv_h, curv_v
