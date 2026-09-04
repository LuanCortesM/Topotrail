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

    Sign convention, verified against surfaces with known shape in
    `tests/test_terrain_math.py` rather than asserted here:

    * **negative on convex forms** -- domes, ridges, spurs, where the surface
      falls away from the cell;
    * **positive on concave forms** -- bowls, hollows, channels, where the
      surface closes in around it.

    * **plan** curvature is measured across the slope, so it captures whether
      flow spreads out or concentrates. On a cylindrical ridge, whose contours
      are straight, it is exactly zero -- the test asserts that.
    * **profile** curvature is measured along the slope: convex breaks where
      the gradient steepens downhill are negative, concave footslopes positive.

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


def roughness_index(dem_array, transform=None, feedback=None):
    """Terrain Ruggedness Index: diferenca absoluta media para os 8 vizinhos.

    Riley, S.J., DeGloria, S.D. & Elliot, R. (1999) A terrain ruggedness index
    that quantifies topographic heterogeneity. Intermountain Journal of Sciences
    5: 23-27.

    Em metros. **Nao e independente da declividade**, e a documentacao anterior
    afirmava que era: numa rampa perfeitamente lisa de 80% o TRI vale 6,00 m,
    contra 3,36 m numa superficie ruidosa de declividade media 27%. Isso nao e
    defeito do indice -- e a definicao dele, a diferenca absoluta media de
    altitude, que cresce com a inclinacao. O teste que mede isso esta em
    tests/test_terrain_math.py.

    Para a rugosidade desacoplada da inclinacao, que e o que o modelo quer,
    use `vector_ruggedness`. Este indice fica disponivel por ser o padrao
    citavel e por ser util como medida de amplitude local em metros.

    Celulas de borda usam apenas os vizinhos existentes.
    """
    dem = dem_array.astype(np.float64)
    valid = np.isfinite(dem)
    rows, cols = dem.shape

    total = np.zeros((rows, cols), np.float64)
    count = np.zeros((rows, cols), np.float64)
    neighbours = ((-1, -1), (-1, 0), (-1, 1), (0, -1),
                  (0, 1), (1, -1), (1, 0), (1, 1))
    for d_row, d_col in neighbours:
        shifted = np.full((rows, cols), np.nan)
        shifted_valid = np.zeros((rows, cols), bool)
        dst = (slice(max(0, -d_row), rows + min(0, -d_row)),
               slice(max(0, -d_col), cols + min(0, -d_col)))
        src = (slice(max(0, d_row), rows + min(0, d_row)),
               slice(max(0, d_col), cols + min(0, d_col)))
        shifted[dst] = dem[src]
        shifted_valid[dst] = valid[src]
        usable = valid & shifted_valid
        total[usable] += np.abs(dem[usable] - shifted[usable])
        count[usable] += 1.0

    with np.errstate(divide="ignore", invalid="ignore"):
        tri = np.where(count > 0, total / count, np.nan).astype(np.float32)
    tri[~valid] = np.nan

    if feedback:
        finite = tri[np.isfinite(tri)]
        if finite.size:
            feedback.pushInfo(
                "Rugosidade (TRI) derivada do MDE: p50={:.2f} m, p90={:.2f} m, max={:.2f} m".format(
                    float(np.percentile(finite, 50)), float(np.percentile(finite, 90)),
                    float(finite.max()))
            )
    return tri


def vector_ruggedness(dem_array, transform, feedback=None):
    """Vector Ruggedness Measure: rugosidade desacoplada da inclinacao.

    Sappington, J.M., Longshore, K.M. & Thompson, D.B. (2007) Quantifying
    landscape ruggedness for animal habitat analysis. Journal of Wildlife
    Management 71: 1419-1426.

    Cada celula vira o vetor unitario normal a superficie, decomposto por
    declividade e orientacao. Os vetores da vizinhanca 3x3 sao somados; se o
    terreno for um plano, por mais ingreme que seja, todos os normais apontam
    para o mesmo lado, a resultante tem modulo igual ao numero de celulas e o
    indice da zero. Quanto mais os normais divergem, menor a resultante e maior
    o indice.

    Sai entre 0 (plano, qualquer que seja a inclinacao) e 1 (maximamente
    rugoso). E esta a medida que separa uma encosta lisa de campo de um campo de
    blocos na mesma inclinacao media -- o TRI nao separa, apesar do que a
    documentacao anterior afirmava.
    """
    px, py = _metric_spacing(transform)
    filled, valid = _filled_for_gradient(dem_array)
    rows, cols = dem_array.shape

    dz_dy, dz_dx = np.gradient(filled, py, px)
    slope = np.arctan(np.hypot(dz_dx, dz_dy))
    aspect = np.arctan2(-dz_dy, dz_dx)

    # Vetor normal unitario de cada celula.
    xy = np.sin(slope)
    vector_x = xy * np.cos(aspect)
    vector_y = xy * np.sin(aspect)
    vector_z = np.cos(slope)

    neighbours = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 0),
                  (0, 1), (1, -1), (1, 0), (1, 1))
    sum_x = np.zeros((rows, cols))
    sum_y = np.zeros((rows, cols))
    sum_z = np.zeros((rows, cols))
    count = np.zeros((rows, cols))
    for d_row, d_col in neighbours:
        dst = (slice(max(0, -d_row), rows + min(0, -d_row)),
               slice(max(0, -d_col), cols + min(0, -d_col)))
        src = (slice(max(0, d_row), rows + min(0, d_row)),
               slice(max(0, d_col), cols + min(0, d_col)))
        usable = np.zeros((rows, cols), bool)
        usable[dst] = valid[src]
        sum_x[dst] += np.where(valid[src], vector_x[src], 0.0)
        sum_y[dst] += np.where(valid[src], vector_y[src], 0.0)
        sum_z[dst] += np.where(valid[src], vector_z[src], 0.0)
        count += usable

    with np.errstate(divide="ignore", invalid="ignore"):
        resultant = np.sqrt(sum_x ** 2 + sum_y ** 2 + sum_z ** 2)
        vrm = np.where(count > 0, 1.0 - resultant / count, np.nan)
    vrm = np.clip(vrm, 0.0, 1.0).astype(np.float32)
    vrm[~valid] = np.nan

    if feedback:
        finite = vrm[np.isfinite(vrm)]
        if finite.size:
            feedback.pushInfo(
                "Rugosidade vetorial (VRM) derivada do MDE: p50={:.5f}, p90={:.5f}, "
                "max={:.5f}".format(
                    float(np.percentile(finite, 50)), float(np.percentile(finite, 90)),
                    float(finite.max()))
            )
    return vrm


def derive_terrain(dem_array, transform, feedback=None):
    """Slope (percent) plus both curvatures, from one DEM in a metric CRS."""
    slope = slope_percent_from_dem(dem_array, transform, feedback)
    curv_h, curv_v = curvatures_from_dem(dem_array, transform, feedback)
    return slope, curv_h, curv_v
