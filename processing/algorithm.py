import os
import tempfile
import shutil
import heapq
import json
import traceback
import platform
import sys
from datetime import datetime

# QGIS' Python bootstrap may try to register every PATH directory as a DLL
# directory. The Microsoft WindowsApps shim can be unreadable in this setup,
# so keep it out of this process before importing qgis.* modules.
os.environ["PATH"] = ";".join(
    path for path in os.environ.get("PATH", "").split(";")
    if "Microsoft\\WindowsApps" not in path
)

import geopandas as gpd
import numpy as np
from osgeo import gdal, ogr, osr
from scipy import ndimage
from shapely.geometry import LineString
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterEnum,
    QgsProcessingParameterCrs,
    QgsProcessingParameterBoolean,
    QgsProcessingOutputVectorLayer,
    QgsProcessingOutputRasterLayer,
    QgsProcessingOutputFile,
    QgsProject,
)

gdal.UseExceptions()
ogr.UseExceptions()


PLUGIN_VERSION = "0.3"
STRICT_CRS_MODE = True


def diagnostic_log_path(output_path):
    base_path, _ = os.path.splitext(output_path)
    return f"{base_path}_diagnostico_topotrail.log"


def array_diagnostics(array):
    valid = array[np.isfinite(array)]
    if valid.size == 0:
        return {"shape": list(array.shape), "valid_pixels": 0}
    return {
        "shape": list(array.shape),
        "total_pixels": int(array.size),
        "valid_pixels": int(valid.size),
        "nodata_pixels": int(array.size - valid.size),
        "min": float(np.nanmin(valid)),
        "max": float(np.nanmax(valid)),
        "mean": float(np.nanmean(valid)),
        "std": float(np.nanstd(valid)),
        "p05": float(np.nanpercentile(valid, 5)),
        "p25": float(np.nanpercentile(valid, 25)),
        "p50": float(np.nanpercentile(valid, 50)),
        "p75": float(np.nanpercentile(valid, 75)),
        "p95": float(np.nanpercentile(valid, 95)),
    }


def file_diagnostics(path):
    if not path:
        return {"path": path, "exists": False}
    return {
        "path": path,
        "exists": os.path.exists(path),
        "size_bytes": os.path.getsize(path) if os.path.exists(path) else None,
    }


def append_diagnostic_log(log_path, event, **data):
    if not log_path:
        return
    output_dir = os.path.dirname(log_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "event": event,
        **data,
    }
    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def dependency_diagnostics():
    """Return lightweight runtime versions for diagnostic JSONL records."""
    try:
        gdal_version = gdal.VersionInfo("--version")
    except Exception:
        gdal_version = "indisponivel"
    return {
        "plugin_version": PLUGIN_VERSION,
        "python": sys.version.replace("\n", " "),
        "gdal": gdal_version,
        "sistema": platform.platform(),
    }


def srs_from_projection(projection, default_crs=None):
    """Build an OSR SpatialReference from WKT or an optional default CRS.

    Parameters are projection WKT from GDAL and an optional fallback such as
    EPSG:4326. The returned SRS uses traditional GIS axis order. Returns None
    when neither projection nor default CRS is available.
    """
    srs = osr.SpatialReference()
    if projection:
        srs.ImportFromWkt(projection)
    elif default_crs:
        if str(default_crs).upper().startswith("EPSG:"):
            srs.ImportFromEPSG(int(str(default_crs).split(":")[1]))
        else:
            srs.SetFromUserInput(str(default_crs))
    else:
        return None
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def srs_label(srs):
    """Return a compact CRS label, preferring AUTHORITY:CODE when available."""
    if not srs:
        return None
    authority = srs.GetAuthorityName(None)
    code = srs.GetAuthorityCode(None)
    if authority and code:
        return f"{authority}:{code}"
    return srs.ExportToProj4() or srs.ExportToWkt()[:120]


def raster_metadata(path):
    """Read raster grid metadata without loading pixel values.

    Returns CRS, dimensions, GeoTransform, pixel size, bounds, NoData and axis
    orientation. Raises a clear exception if GDAL cannot open the raster. The
    dataset handle is explicitly released before returning.
    """
    dataset = gdal.Open(path)
    if dataset is None:
        raise Exception(f"Nao foi possivel abrir raster para metadados: {path}")
    transform = dataset.GetGeoTransform()
    projection = dataset.GetProjection()
    band = dataset.GetRasterBand(1)
    nodata = band.GetNoDataValue() if band else None
    cols = dataset.RasterXSize
    rows = dataset.RasterYSize
    min_x = transform[0]
    max_y = transform[3]
    max_x = transform[0] + cols * transform[1] + rows * transform[2]
    min_y = transform[3] + cols * transform[4] + rows * transform[5]
    bounds = (min(min_x, max_x), min(min_y, max_y), max(min_x, max_x), max(min_y, max_y))
    srs = srs_from_projection(projection)
    metadata = {
        "path": path,
        "cols": cols,
        "rows": rows,
        "transform": tuple(float(value) for value in transform),
        "projection": projection,
        "crs": srs_label(srs),
        "is_geographic": bool(srs and srs.IsGeographic()),
        "is_projected": bool(srs and srs.IsProjected()),
        "pixel_size_x": abs(float(transform[1])),
        "pixel_size_y": abs(float(transform[5])),
        "bounds": bounds,
        "nodata": nodata,
        "y_axis_orientation": "north_up" if transform[5] < 0 else "south_up_or_unknown",
    }
    dataset = None
    return metadata


def raster_center_from_metadata(metadata):
    """Calculate raster center coordinates from metadata and GeoTransform."""
    transform = metadata["transform"]
    cols = metadata["cols"]
    rows = metadata["rows"]
    center_x = transform[0] + (cols * transform[1]) / 2.0 + (rows * transform[2]) / 2.0
    center_y = transform[3] + (cols * transform[4]) / 2.0 + (rows * transform[5]) / 2.0
    return float(center_x), float(center_y)


def automatic_utm_crs_for_geographic_raster(metadata):
    """Choose an EPSG UTM CRS from a geographic raster center.

    Uses longitude to choose zone 1-60 and latitude to choose hemisphere:
    EPSG:326xx in the north, EPSG:327xx in the south.
    """
    center_x, center_y = raster_center_from_metadata(metadata)
    utm_zone = int((center_x + 180.0) / 6.0) + 1
    utm_zone = max(1, min(60, utm_zone))
    epsg = (32700 if center_y < 0 else 32600) + utm_zone
    return f"EPSG:{epsg}"


def copy_raster_with_assigned_crs(input_path, output_path, crs):
    """Create a GeoTIFF copy with an assigned CRS but unchanged pixels/grid.

    This is only used when a CRS-less raster is explicitly handled by the
    default CRS policy. It does not reproject coordinates.
    """
    dataset = gdal.Open(input_path)
    if dataset is None:
        raise Exception(f"Nao foi possivel abrir raster sem CRS: {input_path}")
    driver = gdal.GetDriverByName("GTiff")
    if os.path.exists(output_path):
        driver.Delete(output_path)
    copy = driver.CreateCopy(output_path, dataset, strict=0, options=["COMPRESS=LZW"])
    if copy is None:
        raise Exception(f"Nao foi possivel criar copia com CRS definido: {output_path}")
    srs = srs_from_projection(None, crs)
    copy.SetProjection(srs.ExportToWkt())
    copy.FlushCache()
    copy = None
    dataset = None
    return output_path


def warp_raster_checked(input_path, output_path, warp_options, description="reprojecao"):
    """Run GDAL Warp and fail loudly if the output is not created/openable."""
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    try:
        result = gdal.Warp(output_path, input_path, options=warp_options)
    except Exception as exc:
        raise Exception(f"Falha em {description}: {input_path} -> {output_path}: {exc}") from exc
    if result is None:
        raise Exception(f"Falha em {description}: GDAL Warp retornou vazio para {input_path}")
    result.FlushCache()
    result = None
    check = gdal.Open(output_path)
    if check is None:
        raise Exception(f"Falha em {description}: arquivo final nao abre: {output_path}")
    check = None
    return output_path


def ensure_projected_working_crs(
    dem_path,
    feedback=None,
    default_crs="EPSG:4326",
    temp_dir=None,
    log_path=None,
    strict_crs_mode=STRICT_CRS_MODE,
):
    """Prepare a DEM for metric processing and return path/CRS diagnostics.

    Inputs: DEM path readable by GDAL, optional feedback/log path and fallback
    CRS. Area, distance, route and buffer operations require a projected CRS in
    meters. Geographic DEMs are warped to automatic UTM based on raster center.
    CRS-less DEMs fail in strict_crs_mode, which is the scientific default. If
    strict_crs_mode is False, CRS-less DEMs are assigned default_crs with warning
    and log entry before the same decision. Returns a dict with prepared path,
    original/working CRS, reprojection flag, metadata and messages. Raises when
    the CRS is invalid or GDAL cannot create/open the prepared raster.
    """
    messages = []
    temp_dir = temp_dir or tempfile.mkdtemp(prefix="topotrail_crs_")
    original_metadata = raster_metadata(dem_path)
    source_path = dem_path
    source_projection = original_metadata["projection"]
    original_srs = srs_from_projection(source_projection)
    assigned_default = False

    if original_srs is None:
        if strict_crs_mode:
            message = (
                "O raster de entrada não possui CRS definido. Para uso científico, "
                "defina o CRS correto na fonte antes do processamento."
            )
            append_diagnostic_log(
                log_path,
                "validacao_falhou",
                erro=message,
                raster=dem_path,
                strict_crs_mode=True,
            )
            raise ValueError(message)
        assigned_default = True
        assigned_path = os.path.join(temp_dir, "dem_assumido_crs.tif")
        source_path = copy_raster_with_assigned_crs(dem_path, assigned_path, default_crs)
        messages.append(
            f"DEM sem CRS. CRS assumido para diagnostico: {default_crs}. "
            "Resultado depende dessa suposicao; defina o CRS correto para uso cientifico."
        )
        if feedback:
            feedback.pushWarning(messages[-1])
        original_srs = srs_from_projection(None, default_crs)
        original_metadata = raster_metadata(source_path)

    working_crs = srs_label(original_srs)
    reprojected = False
    prepared_path = source_path
    reason = "CRS ja projetado"

    if original_srs.IsGeographic():
        working_crs = automatic_utm_crs_for_geographic_raster(original_metadata)
        prepared_path = os.path.join(temp_dir, "dem_trabalho_metrico.tif")
        reason = "CRS geografico reprojetado para UTM automatica"
        warp_options = gdal.WarpOptions(
            dstSRS=working_crs,
            resampleAlg=gdal.GRA_Bilinear,
            format="GTiff",
            creationOptions=["COMPRESS=LZW"],
        )
        warp_raster_checked(source_path, prepared_path, warp_options, "reprojecao do DEM para CRS metrico")
        reprojected = True
        messages.append(f"DEM reprojetado para CRS de trabalho metrico: {working_crs}.")
    elif not original_srs.IsProjected():
        raise Exception("O CRS do DEM nao e geografico nem projetado. Defina um CRS valido antes de processar.")
    else:
        messages.append(f"DEM em CRS projetado mantido: {working_crs}.")

    prepared_metadata = raster_metadata(prepared_path)
    diagnostics = {
        "dem_path": prepared_path,
        "original_crs": srs_label(srs_from_projection(source_projection)) or (default_crs if assigned_default else None),
        "working_crs": working_crs,
        "reprojected": reprojected,
        "assigned_default_crs": assigned_default,
        "strict_crs_mode": strict_crs_mode,
        "reason": reason,
        "messages": messages,
        "original_metadata": original_metadata,
        "prepared_metadata": prepared_metadata,
        "temp_path": prepared_path if prepared_path != dem_path else None,
    }
    append_diagnostic_log(log_path, "crs_trabalho_definido", **diagnostics)
    for message in messages:
        if feedback:
            feedback.pushInfo(message)
    return diagnostics


def validate_raster_grid_compatibility(reference_raster, candidate_raster, tolerance=1e-6):
    """Compare two rasters for same analysis grid.

    Checks CRS, rows, columns, pixel size, full GeoTransform, bounds, NoData and
    Y-axis orientation. Returns a dict with compatible/problemas and both
    metadata snapshots; it does not mutate files.
    """
    reference = raster_metadata(reference_raster)
    candidate = raster_metadata(candidate_raster)
    problems = []

    if reference["crs"] != candidate["crs"]:
        problems.append(f"CRS diferente: referencia={reference['crs']} candidato={candidate['crs']}")
    if reference["rows"] != candidate["rows"]:
        problems.append(f"Numero de linhas diferente: referencia={reference['rows']} candidato={candidate['rows']}")
    if reference["cols"] != candidate["cols"]:
        problems.append(f"Numero de colunas diferente: referencia={reference['cols']} candidato={candidate['cols']}")
    if abs(reference["pixel_size_x"] - candidate["pixel_size_x"]) > tolerance:
        problems.append("Resolucao X diferente")
    if abs(reference["pixel_size_y"] - candidate["pixel_size_y"]) > tolerance:
        problems.append("Resolucao Y diferente")
    if reference["y_axis_orientation"] != candidate["y_axis_orientation"]:
        problems.append("Orientacao do eixo Y diferente")
    for index, (ref_value, cand_value) in enumerate(zip(reference["transform"], candidate["transform"])):
        if abs(ref_value - cand_value) > tolerance:
            problems.append(f"GeoTransform diferente no indice {index}: referencia={ref_value} candidato={cand_value}")
    for index, (ref_value, cand_value) in enumerate(zip(reference["bounds"], candidate["bounds"])):
        if abs(ref_value - cand_value) > max(tolerance, reference["pixel_size_x"] * 1e-6):
            problems.append(f"Extensao diferente no indice {index}: referencia={ref_value} candidato={cand_value}")
    if reference["nodata"] != candidate["nodata"]:
        problems.append(f"NoData diferente: referencia={reference['nodata']} candidato={candidate['nodata']}")

    return {
        "compatible": len(problems) == 0,
        "problems": problems,
        "reference_metadata": reference,
        "candidate_metadata": candidate,
    }


def align_raster_to_reference(candidate_path, reference_path, output_path, resampling="bilinear", feedback=None, log_path=None):
    """Warp a candidate raster onto a reference raster grid.

    Uses the reference CRS, bounds and resolution. Resampling defaults to
    bilinear for continuous DEM/slope/curvature surfaces; nearest is available
    for masks/classes. The result is reopened and checked against the reference.
    Raises if blocking grid differences remain.
    """
    reference = raster_metadata(reference_path)
    resampling_map = {
        "bilinear": gdal.GRA_Bilinear,
        "nearest": gdal.GRA_NearestNeighbour,
        "cubic": gdal.GRA_Cubic,
    }
    resampling_alg = resampling_map.get(resampling, gdal.GRA_Bilinear)
    bounds = reference["bounds"]
    warp_options = gdal.WarpOptions(
        dstSRS=reference["projection"],
        outputBounds=bounds,
        xRes=reference["pixel_size_x"],
        yRes=reference["pixel_size_y"],
        resampleAlg=resampling_alg,
        format="GTiff",
        creationOptions=["COMPRESS=LZW"],
        dstNodata=reference["nodata"] if reference["nodata"] is not None else -9999.0,
    )
    if feedback:
        feedback.pushInfo(f"Alinhando raster ao MDE: {os.path.basename(candidate_path)}")
    warp_raster_checked(candidate_path, output_path, warp_options, "alinhamento raster ao MDE")
    compatibility = validate_raster_grid_compatibility(reference_path, output_path)
    blocking_problems = [
        problem for problem in compatibility["problems"]
        if not problem.startswith("NoData diferente")
    ]
    if blocking_problems:
        raise Exception(
            "Raster alinhado ainda incompativel com o MDE: "
            + "; ".join(blocking_problems)
        )
    append_diagnostic_log(
        log_path,
        "raster_alinhado",
        entrada=candidate_path,
        saida=output_path,
        referencia=reference_path,
        resampling=resampling,
        compatibilidade=compatibility,
    )
    return output_path


def read_raster(raster_path, feedback=None):
    """Read band 1 as float32, converting NoData to NaN.

    Returns array, GeoTransform and projection WKT. GDAL datasets are explicitly
    closed. Raises clear exceptions for missing/unreadable rasters.
    """
    try:
        dataset = gdal.Open(raster_path)
    except RuntimeError as exc:
        raise Exception(f"Não foi possível abrir o raster: {raster_path}") from exc
    if dataset is None:
        raise Exception(f"Não foi possível abrir o raster: {raster_path}")

    band = dataset.GetRasterBand(1)
    array = band.ReadAsArray()
    if array is None:
        raise Exception(f"Não foi possível ler a banda 1 do raster: {raster_path}")

    array = array.astype(np.float32)
    nodata = band.GetNoDataValue()
    if nodata is not None:
        array[array == nodata] = np.nan

    transform = dataset.GetGeoTransform()
    proj = dataset.GetProjection()

    if feedback:
        valid = array[~np.isnan(array)]
        if valid.size:
            feedback.pushInfo(
                f"Raster {os.path.basename(raster_path)}: shape={array.shape}, "
                f"min={np.nanmin(valid):.4f}, max={np.nanmax(valid):.4f}, mean={np.nanmean(valid):.4f}"
            )
        else:
            feedback.pushInfo(f"Raster {os.path.basename(raster_path)}: sem valores válidos")

    dataset = None
    return array, transform, proj


def validate_raster_alignment(reference_shape, reference_transform, rasters, feedback=None):
    """Ensure every input raster shares the DEM grid."""
    for name, array, transform in rasters:
        if array.shape != reference_shape:
            raise ValueError(
                f"{name} possui dimensões {array.shape}, mas o MDE possui {reference_shape}. "
                "Reamostre e alinhe os rasters antes de processar."
            )

        diffs = [abs(float(transform[i]) - float(reference_transform[i])) for i in range(6)]
        if any(diff > 1e-9 for diff in diffs):
            raise ValueError(
                f"{name} não está alinhado ao MDE. "
                "Use a mesma extensão, resolução e origem de grade para todos os rasters."
            )

        if feedback:
            feedback.pushInfo(f"{name} alinhado ao MDE: shape={array.shape}")


def normalize_linear(array, min_val, max_val, feedback=None, name="Critério"):
    if max_val <= min_val:
        raise ValueError(f"Limites inválidos para {name}: min={min_val}, max={max_val}")

    valid_mask = ~np.isnan(array)
    normalized = np.zeros_like(array, dtype=np.float32)
    normalized[valid_mask] = (array[valid_mask] - min_val) / (max_val - min_val)
    normalized = np.clip(normalized, 0, 1)

    if feedback:
        feedback.pushInfo(
            f"{name} normalizado: min={np.nanmin(normalized):.4f}, "
            f"max={np.nanmax(normalized):.4f}, mean={np.nanmean(normalized):.4f}"
        )

    return normalized


def normalize_cost(array, min_val, max_val, feedback=None, name="Critério"):
    normalized = normalize_linear(array, min_val, max_val, feedback, name)
    valid_mask = ~np.isnan(array)
    result = np.zeros_like(normalized, dtype=np.float32)
    result[valid_mask] = 1.0 - normalized[valid_mask]

    if feedback:
        feedback.pushInfo(
            f"{name} invertido como custo: min={np.nanmin(result):.4f}, "
            f"max={np.nanmax(result):.4f}, mean={np.nanmean(result):.4f}"
        )

    return result


def normalize_curvature_preference(array, feedback=None, name="Curvatura", target=0.0, limit=None, floor=0.2):
    """Score curvature by proximity to a target, avoiding extreme concave/convex forms."""
    valid_mask = ~np.isnan(array)
    valid_data = array[valid_mask]
    if valid_data.size == 0:
        raise ValueError(f"{name} não contém valores válidos")

    if limit is None or limit <= 0:
        deviations = np.abs(valid_data - target)
        limit = float(np.nanpercentile(deviations, 99))
        if limit <= 0:
            limit = float(np.nanmax(deviations))
        if limit <= 0:
            limit = 1.0

    score = np.zeros_like(array, dtype=np.float32)
    score[valid_mask] = floor + (1.0 - floor) * (
        1.0 - np.clip(np.abs(array[valid_mask] - target) / limit, 0, 1)
    )

    if feedback:
        feedback.pushInfo(f"{name}: alvo={target:.4f}, limite={limit:.4f}")
        feedback.pushInfo(
            f"{name} score: min={np.nanmin(score):.4f}, "
            f"max={np.nanmax(score):.4f}, mean={np.nanmean(score):.4f}"
        )

    return score


def calculate_slope_degrees(dem_array, transform, feedback=None):
    """Calculate slope in degrees using physical pixel size from GeoTransform.

    Expects DEM values in a metric working CRS and uses transform pixel width
    and height as spacing for np.gradient. NaN cells remain NaN in the output.
    Raises ValueError for invalid non-positive pixel sizes.
    """
    pixel_size_x = abs(float(transform[1]))
    pixel_size_y = abs(float(transform[5]))
    if pixel_size_x <= 0 or pixel_size_y <= 0:
        raise ValueError("Resolucao espacial invalida para calculo de declividade.")
    dem = dem_array.astype(np.float32)
    valid_mask = np.isfinite(dem)
    filled = np.where(valid_mask, dem, np.nanmean(dem[valid_mask]) if np.any(valid_mask) else 0.0)
    dy, dx = np.gradient(filled, pixel_size_y, pixel_size_x)
    slope = np.degrees(np.arctan(np.sqrt(dx ** 2 + dy ** 2))).astype(np.float32)
    slope[~valid_mask] = np.nan
    slope[~np.isfinite(slope)] = np.nan
    if feedback:
        feedback.pushInfo(
            f"Declividade calculada com resolucao {pixel_size_x:.3f} x {pixel_size_y:.3f}: "
            f"{array_diagnostics(slope)}"
        )
    return slope


def calculate_curvature_arrays(dem_array, transform, feedback=None):
    """Calculate simple second-derivative horizontal/vertical curvature proxies.

    Expects DEM values in a metric working CRS. The derivatives use physical
    pixel spacing from GeoTransform. These arrays are lightweight internal
    diagnostics/fallback terrain derivatives; user supplied curvature rasters
    remain the primary production input. NaN cells remain NaN.
    """
    pixel_size_x = abs(float(transform[1]))
    pixel_size_y = abs(float(transform[5]))
    if pixel_size_x <= 0 or pixel_size_y <= 0:
        raise ValueError("Resolucao espacial invalida para calculo de curvatura.")
    dem = dem_array.astype(np.float32)
    valid_mask = np.isfinite(dem)
    filled = np.where(valid_mask, dem, np.nanmean(dem[valid_mask]) if np.any(valid_mask) else 0.0)
    dy, dx = np.gradient(filled, pixel_size_y, pixel_size_x)
    _, dxx = np.gradient(dx, pixel_size_y, pixel_size_x)
    dyy, _ = np.gradient(dy, pixel_size_y, pixel_size_x)
    curv_h = dxx.astype(np.float32)
    curv_v = dyy.astype(np.float32)
    curv_h[~valid_mask] = np.nan
    curv_v[~valid_mask] = np.nan
    curv_h[~np.isfinite(curv_h)] = np.nan
    curv_v[~np.isfinite(curv_v)] = np.nan
    if feedback:
        feedback.pushInfo(
            f"Curvaturas calculadas com resolucao {pixel_size_x:.3f} x {pixel_size_y:.3f}: "
            f"H={array_diagnostics(curv_h)}, V={array_diagnostics(curv_v)}"
        )
    return curv_h, curv_v


def binarize_result(array, threshold, feedback=None):
    binary = np.where(array >= threshold, 1, 0).astype(np.uint8)
    binary = np.where(np.isnan(array), 0, binary).astype(np.uint8)

    if feedback:
        valid_pixels = int(np.sum(binary == 1))
        feedback.pushInfo(
            f"Binarização: {valid_pixels} pixels aptos de {binary.size} "
            f"({valid_pixels / binary.size * 100:.2f}%)"
        )

    return binary


def build_walkability_mask(zone_constraint_mask, feedback=None):
    binary = zone_constraint_mask.astype(np.uint8)
    if feedback:
        valid_pixels = int(np.sum(binary == 1))
        feedback.pushInfo(
            f"Máscara caminhável: {valid_pixels} pixels aptos de {binary.size} "
            f"({valid_pixels / binary.size * 100:.2f}%)"
        )
    return binary


def binarize_by_altitude_bands(score_array, dem_array, percentile, band_size_m, feedback=None):
    valid_mask = np.isfinite(score_array) & np.isfinite(dem_array)
    binary = np.zeros_like(score_array, dtype=np.uint8)
    if not np.any(valid_mask):
        return binary

    min_altitude = float(np.nanmin(dem_array[valid_mask]))
    max_altitude = float(np.nanmax(dem_array[valid_mask]))
    band_size_m = max(50.0, float(band_size_m))
    start = np.floor(min_altitude / band_size_m) * band_size_m
    thresholds = []

    current = start
    while current <= max_altitude:
        next_altitude = current + band_size_m
        band_mask = valid_mask & (dem_array >= current) & (dem_array < next_altitude)
        band_scores = score_array[band_mask]
        if band_scores.size >= 50:
            band_threshold = float(np.percentile(band_scores, percentile))
            binary[band_mask & (score_array >= band_threshold)] = 1
            thresholds.append((current, next_altitude, band_threshold, int(band_scores.size)))
        current = next_altitude

    if feedback:
        feedback.pushInfo(
            f"Threshold por faixa altimetrica: {len(thresholds)} faixas de {band_size_m:.0f} m, "
            f"percentil {percentile:.1f}"
        )
        for low, high, band_threshold, pixels in thresholds[:12]:
            feedback.pushInfo(
                f"  {low:.0f}-{high:.0f} m: threshold={band_threshold:.4f}, pixels={pixels}"
            )
        if len(thresholds) > 12:
            feedback.pushInfo(f"  ... {len(thresholds) - 12} faixas adicionais")

    return binary


def estimate_pixel_area_m2(transform, shape, proj):
    x_size = abs(float(transform[1]))
    y_size = abs(float(transform[5]))

    srs = osr.SpatialReference()
    if proj:
        srs.ImportFromWkt(proj)

    if srs.IsGeographic():
        center_lat = float(transform[3]) + (shape[0] * float(transform[5]) / 2.0)
        meters_per_degree_lon = 111320.0 * np.cos(np.deg2rad(center_lat))
        meters_per_degree_lat = 110574.0
        return abs(x_size * meters_per_degree_lon * y_size * meters_per_degree_lat)

    return abs(x_size * y_size)


def metric_crs_for_raster(transform, shape, proj):
    srs = osr.SpatialReference()
    if proj:
        srs.ImportFromWkt(proj)
    else:
        srs.ImportFromEPSG(4326)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    if not srs.IsGeographic():
        authority = srs.GetAuthorityName(None)
        code = srs.GetAuthorityCode(None)
        if authority and code:
            return f"{authority}:{code}"
        return srs.ExportToWkt()

    center_lon = float(transform[0]) + (shape[1] * float(transform[1]) / 2.0)
    center_lat = float(transform[3]) + (shape[0] * float(transform[5]) / 2.0)
    zone = int(np.floor((center_lon + 180.0) / 6.0)) + 1
    zone = min(60, max(1, zone))
    epsg = (32600 if center_lat >= 0 else 32700) + zone
    return f"EPSG:{epsg}"


def filter_small_regions(binary_array, transform, proj, min_area_ha, feedback=None, log_path=None):
    """Remove connected raster fragments smaller than a minimum area.

    Area is computed from metric pixel area when the CRS is projected; for
    geographic CRS the helper estimates meters from latitude, but production
    flow now prepares a projected working CRS before this function is reached.
    Returns a uint8 mask with small fragments removed and logs pixel/fragment
    counts when log_path is provided.
    """
    if min_area_ha <= 0:
        return binary_array

    pixel_area_m2 = estimate_pixel_area_m2(transform, binary_array.shape, proj)
    min_pixels = max(1, int(np.ceil((min_area_ha * 10000.0) / pixel_area_m2)))
    labels, region_count = ndimage.label(binary_array == 1, structure=np.ones((3, 3), dtype=np.uint8))

    if region_count == 0:
        return binary_array

    region_sizes = np.bincount(labels.ravel())
    keep_labels = np.where(region_sizes >= min_pixels)[0]
    keep_labels = keep_labels[keep_labels != 0]
    filtered = np.isin(labels, keep_labels).astype(np.uint8)

    if feedback:
        before_pixels = int(np.sum(binary_array == 1))
        after_pixels = int(np.sum(filtered == 1))
        removed_regions = int(region_count - len(keep_labels))
        feedback.pushInfo(
            f"Filtro de area minima: {min_area_ha:.2f} ha, "
            f"{min_pixels} pixels por fragmento; {removed_regions} fragmentos removidos usando 8 vizinhos"
        )
        feedback.pushInfo(f"Pixels aptos apos filtro: {after_pixels} de {before_pixels}")
    append_diagnostic_log(
        log_path,
        "filtro_area_minima",
        area_pixel_m2=float(pixel_area_m2),
        area_min_fragmento_ha=float(min_area_ha),
        min_pixels=int(min_pixels),
        fragmentos_antes=int(region_count),
        fragmentos_depois=int(len(keep_labels)),
        pixels_antes=int(np.sum(binary_array == 1)),
        pixels_depois=int(np.sum(filtered == 1)),
    )

    return filtered


def save_score_raster(score_array, transform, proj, output_path, feedback=None):
    base_path, _ = os.path.splitext(output_path)
    score_path = f"{base_path}_adequabilidade.tif"
    rows, cols = score_array.shape
    output_dir = os.path.dirname(score_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    output = np.where(np.isnan(score_array), -9999.0, score_array).astype(np.float32)
    driver = gdal.GetDriverByName("GTiff")
    if os.path.exists(score_path):
        try:
            driver.Delete(score_path)
        except RuntimeError:
            score_path = available_output_path(score_path)
            if feedback:
                feedback.pushWarning(
                    "O raster de adequabilidade anterior esta em uso no QGIS ou bloqueado pelo sistema. "
                    f"Salvando novo arquivo como: {score_path}"
                )
    dataset = driver.Create(score_path, cols, rows, 1, gdal.GDT_Float32, options=["COMPRESS=LZW"])
    if dataset is None:
        raise Exception("Nao foi possivel criar o raster de adequabilidade.")

    dataset.SetGeoTransform(transform)
    if proj:
        dataset.SetProjection(proj)
    band = dataset.GetRasterBand(1)
    band.SetNoDataValue(-9999.0)
    band.WriteArray(output)
    band.FlushCache()
    dataset = None

    if feedback:
        feedback.pushInfo(f"Raster de adequabilidade salvo: {score_path}")
    return score_path


def save_risk_raster(risk_array, transform, proj, output_path, feedback=None):
    base_path, _ = os.path.splitext(output_path)
    risk_path = f"{base_path}_risco_topografico.tif"
    rows, cols = risk_array.shape
    output_dir = os.path.dirname(risk_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    output = np.where(np.isnan(risk_array), -9999.0, risk_array).astype(np.float32)
    driver = gdal.GetDriverByName("GTiff")
    if os.path.exists(risk_path):
        try:
            driver.Delete(risk_path)
        except RuntimeError:
            risk_path = available_output_path(risk_path)
            if feedback:
                feedback.pushWarning(
                    "O raster de risco topografico anterior esta em uso no QGIS ou bloqueado pelo sistema. "
                    f"Salvando novo arquivo como: {risk_path}"
                )
    dataset = driver.Create(risk_path, cols, rows, 1, gdal.GDT_Float32, options=["COMPRESS=LZW"])
    if dataset is None:
        raise Exception("Nao foi possivel criar o raster de risco topografico.")

    dataset.SetGeoTransform(transform)
    if proj:
        dataset.SetProjection(proj)
    band = dataset.GetRasterBand(1)
    band.SetNoDataValue(-9999.0)
    band.WriteArray(output)
    band.FlushCache()
    dataset = None

    if feedback:
        feedback.pushInfo(f"Raster de risco topografico salvo: {risk_path}")
    return risk_path


def robust_abs_norm(array, valid_mask, percentile=95.0):
    values = np.abs(array[valid_mask & np.isfinite(array)])
    if values.size == 0:
        return np.full(array.shape, np.nan, dtype=np.float32)
    limit = float(np.nanpercentile(values, percentile))
    if not np.isfinite(limit) or limit <= 0:
        limit = float(np.nanmax(values)) if values.size else 1.0
    if not np.isfinite(limit) or limit <= 0:
        limit = 1.0
    return np.clip(np.abs(array) / limit, 0, 1).astype(np.float32)


def compute_topographic_risk(slope_data, curvh_data, curvv_data, valid_mask, max_slope, feedback=None):
    """Relative topographic risk: 0 is easier terrain, 1 is steep/rough/abrupt terrain."""
    slope_limit = max(float(max_slope), 1.0)
    slope_risk = np.clip(slope_data / slope_limit, 0, 1)
    slope_risk = np.power(slope_risk, 1.35)

    curvh_risk = robust_abs_norm(curvh_data, valid_mask)
    curvv_risk = robust_abs_norm(curvv_data, valid_mask)
    curvature_risk = np.nanmean(np.stack([curvh_risk, curvv_risk]), axis=0)

    risk = (0.75 * slope_risk + 0.25 * curvature_risk).astype(np.float32)
    risk = np.where(valid_mask, np.clip(risk, 0, 1), np.nan).astype(np.float32)

    if feedback:
        values = risk[np.isfinite(risk)]
        if values.size:
            feedback.pushInfo(
                "Risco topografico relativo: "
                f"min={np.nanmin(values):.3f}, p50={np.nanpercentile(values, 50):.3f}, "
                f"p75={np.nanpercentile(values, 75):.3f}, p95={np.nanpercentile(values, 95):.3f}, "
                f"max={np.nanmax(values):.3f}"
            )
    return risk


def vectorize_binary_raster(binary_array, transform, proj, feedback=None):
    """Polygonize a binary raster and return only polygons with value 1."""
    temp_dir = tempfile.mkdtemp()
    try:
        if np.sum(binary_array == 1) == 0:
            srs = osr.SpatialReference()
            srs.ImportFromWkt(proj) if proj else srs.ImportFromEPSG(4326)
            crs = srs.ExportToWkt()
            return gpd.GeoDataFrame({"value": []}, geometry=[], crs=crs)

        temp_raster = os.path.join(temp_dir, "mask.tif")
        rows, cols = binary_array.shape
        driver = gdal.GetDriverByName("GTiff")
        dataset = driver.Create(temp_raster, cols, rows, 1, gdal.GDT_Byte)
        if dataset is None:
            raise Exception("Não foi possível criar raster temporário")

        dataset.SetGeoTransform(transform)
        if proj:
            dataset.SetProjection(proj)
        band = dataset.GetRasterBand(1)
        band.SetNoDataValue(0)
        band.WriteArray(binary_array)
        band.FlushCache()
        dataset = None

        temp_vector = os.path.join(temp_dir, "mask.shp")
        shp_driver = ogr.GetDriverByName("ESRI Shapefile")
        vector_ds = shp_driver.CreateDataSource(temp_vector)
        if vector_ds is None:
            raise Exception("Não foi possível criar vetor temporário")

        srs = osr.SpatialReference()
        srs.ImportFromWkt(proj) if proj else srs.ImportFromEPSG(4326)
        layer = vector_ds.CreateLayer("polygons", srs=srs, geom_type=ogr.wkbPolygon)
        layer.CreateField(ogr.FieldDefn("value", ogr.OFTInteger))

        raster_ds = gdal.Open(temp_raster)
        raster_band = raster_ds.GetRasterBand(1)
        gdal.Polygonize(raster_band, raster_band, layer, 0, options=["8CONNECTED=8"])
        raster_ds = None
        vector_ds = None

        gdf = gpd.read_file(temp_vector)
        if "value" in gdf.columns:
            gdf = gdf[gdf["value"] == 1].copy()
        else:
            gdf["value"] = 1

        if len(gdf) > 0:
            gdf["geometry"] = gdf.geometry.buffer(0)
            gdf = gdf[gdf.is_valid & ~gdf.is_empty].copy()

        if feedback:
            feedback.pushInfo(f"Vetorizações geradas: {len(gdf)} polígonos")

        return gdf
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def save_vector(gdf, output_path, output_format, output_crs, feedback=None):
    driver_map = {
        "Shapefile": "ESRI Shapefile",
        "GeoPackage": "GPKG",
        "KML": "KML",
    }

    if len(gdf) == 0:
        raise Exception("Nenhuma area atingiu o threshold configurado. Reduza o threshold ou revise os criterios.")

    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    if len(gdf) > 0 and output_crs and output_crs.isValid():
        target_crs = output_crs.authid()
        if target_crs:
            gdf = gdf.to_crs(target_crs)
            if feedback:
                feedback.pushInfo(f"Resultado reprojetado para {target_crs}")

    export_gdf = gdf.copy()
    if output_format == "Shapefile" and "area_m2" in export_gdf.columns:
        export_gdf = export_gdf.drop(columns=["area_m2"])
        if feedback:
            feedback.pushInfo("Campo area_m2 removido da saida Shapefile para evitar estouro de largura DBF; area_ha foi preservado.")
    if output_format == "KML":
        for column in export_gdf.columns:
            if column != export_gdf.geometry.name:
                export_gdf[column] = export_gdf[column].apply(
                    lambda value: "" if value is None or (isinstance(value, float) and np.isnan(value)) else str(value)
                )

    driver = driver_map.get(output_format, "ESRI Shapefile")
    driver_obj = ogr.GetDriverByName(driver)
    if driver_obj and os.path.exists(output_path):
        try:
            driver_obj.DeleteDataSource(output_path)
        except RuntimeError:
            output_path = available_output_path(output_path)
            if feedback:
                feedback.pushWarning(
                    "O vetor anterior esta em uso no QGIS ou bloqueado pelo sistema. "
                    f"Salvando novo arquivo como: {output_path}"
                )
    export_gdf.to_file(output_path, driver=driver)

    if feedback:
        feedback.pushInfo(f"{output_format} salvo com sucesso: {len(gdf)} feições")
    return output_path


def ensure_output_extension(output_path, output_format):
    extension_map = {
        "Shapefile": ".shp",
        "GeoPackage": ".gpkg",
        "KML": ".kml",
    }
    expected_extension = extension_map.get(output_format)
    if not expected_extension:
        return output_path

    base_path, current_extension = os.path.splitext(output_path)
    if current_extension.lower() != expected_extension:
        return f"{base_path}{expected_extension}"
    return output_path


def available_output_path(path):
    base, extension = os.path.splitext(path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = f"{base}_{timestamp}{extension}"
    counter = 1
    while os.path.exists(candidate):
        candidate = f"{base}_{timestamp}_{counter}{extension}"
        counter += 1
    return candidate


def transform_point_to_raster(point_path, raster_proj):
    datasource = ogr.Open(point_path)
    if datasource is None:
        raise Exception(f"Nao foi possivel abrir o ponto: {point_path}")

    raster_srs = osr.SpatialReference()
    raster_srs.ImportFromWkt(raster_proj) if raster_proj else raster_srs.ImportFromEPSG(4326)
    raster_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    for layer_index in range(datasource.GetLayerCount()):
        layer = datasource.GetLayerByIndex(layer_index)
        source_srs = layer.GetSpatialRef()
        transform = None
        if source_srs is not None and not source_srs.IsSame(raster_srs):
            source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            transform = osr.CoordinateTransformation(source_srs, raster_srs)

        for feature in layer:
            geometry = feature.GetGeometryRef()
            if geometry is None:
                continue
            geom = geometry.Clone()
            if transform is not None:
                geom.Transform(transform)
            flat_type = ogr.GT_Flatten(geom.GetGeometryType())
            if flat_type == ogr.wkbPoint:
                return float(geom.GetX()), float(geom.GetY())
            if geom.GetGeometryCount() > 0:
                sub_geom = geom.GetGeometryRef(0)
                if sub_geom and ogr.GT_Flatten(sub_geom.GetGeometryType()) == ogr.wkbPoint:
                    return float(sub_geom.GetX()), float(sub_geom.GetY())

    raise Exception(f"Nenhuma geometria de ponto encontrada em: {point_path}")


def world_to_pixel(transform, x, y):
    inv_transform = gdal.InvGeoTransform(transform)
    col = int(round(inv_transform[0] + inv_transform[1] * x + inv_transform[2] * y))
    row = int(round(inv_transform[3] + inv_transform[4] * x + inv_transform[5] * y))
    return row, col


def pixel_to_world(transform, row, col):
    x = transform[0] + (col + 0.5) * transform[1] + (row + 0.5) * transform[2]
    y = transform[3] + (col + 0.5) * transform[4] + (row + 0.5) * transform[5]
    return float(x), float(y)


def meters_to_pixels(transform, shape, proj, distance_m):
    pixel_area = estimate_pixel_area_m2(transform, shape, proj)
    pixel_size = np.sqrt(pixel_area) if pixel_area > 0 else 30.0
    return max(1, int(np.ceil(distance_m / pixel_size)))


def nearest_valid_cell(valid_mask, row, col, radius=30):
    rows, cols = valid_mask.shape
    if 0 <= row < rows and 0 <= col < cols and valid_mask[row, col]:
        return row, col

    best = None
    best_dist = None
    row_min = max(0, row - radius)
    row_max = min(rows, row + radius + 1)
    col_min = max(0, col - radius)
    col_max = min(cols, col + radius + 1)
    candidates = np.argwhere(valid_mask[row_min:row_max, col_min:col_max])
    for candidate_row, candidate_col in candidates:
        rr = int(candidate_row + row_min)
        cc = int(candidate_col + col_min)
        dist = (rr - row) ** 2 + (cc - col) ** 2
        if best_dist is None or dist < best_dist:
            best = (rr, cc)
            best_dist = dist
    if best is None:
        raise Exception("Ponto inicial ou final caiu fora das celulas viaveis e nao ha celula valida proxima.")
    return best


def least_cost_path(cost_array, start_rc, end_rc):
    rows, cols = cost_array.shape
    start_index = start_rc[0] * cols + start_rc[1]
    end_index = end_rc[0] * cols + end_rc[1]

    dist = np.full(rows * cols, np.inf, dtype=np.float64)
    previous = np.full(rows * cols, -1, dtype=np.int64)
    visited = np.zeros(rows * cols, dtype=bool)
    dist[start_index] = 0.0
    finite_costs = cost_array[np.isfinite(cost_array)]
    if finite_costs.size == 0:
        raise Exception("A area de busca da rota nao contem celulas viaveis.")
    min_step_cost = float(np.nanmin(finite_costs))

    def heuristic(row, col):
        return np.hypot(row - end_rc[0], col - end_rc[1]) * min_step_cost

    heap = [(heuristic(start_rc[0], start_rc[1]), 0.0, start_index)]

    neighbors = [
        (-1, 0, 1.0),
        (1, 0, 1.0),
        (0, -1, 1.0),
        (0, 1, 1.0),
        (-1, -1, np.sqrt(2.0)),
        (-1, 1, np.sqrt(2.0)),
        (1, -1, np.sqrt(2.0)),
        (1, 1, np.sqrt(2.0)),
    ]

    while heap:
        _, current_dist, index = heapq.heappop(heap)
        if visited[index]:
            continue
        visited[index] = True
        if index == end_index:
            break
        row = index // cols
        col = index % cols
        current_cost = cost_array[row, col]
        for d_row, d_col, step_length in neighbors:
            next_row = row + d_row
            next_col = col + d_col
            if next_row < 0 or next_row >= rows or next_col < 0 or next_col >= cols:
                continue
            next_cost = cost_array[next_row, next_col]
            if not np.isfinite(next_cost):
                continue
            next_index = next_row * cols + next_col
            if visited[next_index]:
                continue
            move_cost = ((current_cost + next_cost) / 2.0) * step_length
            candidate_dist = current_dist + move_cost
            if candidate_dist < dist[next_index]:
                dist[next_index] = candidate_dist
                previous[next_index] = index
                priority = candidate_dist + heuristic(next_row, next_col)
                heapq.heappush(heap, (priority, candidate_dist, next_index))

    if not np.isfinite(dist[end_index]):
        raise Exception("Nao foi possivel conectar o ponto inicial ao ponto final com as restricoes atuais.")

    path = []
    index = end_index
    while index != -1:
        path.append((index // cols, index % cols))
        if index == start_index:
            break
        index = previous[index]
    path.reverse()
    return path, float(dist[end_index])


def save_access_route(
    score_array,
    transform,
    proj,
    start_path,
    end_path,
    output_path,
    buffer_m,
    margin_m,
    feedback=None,
    elevation_array=None,
    output_crs=None,
    log_path=None,
):
    """Generate least-cost route and metric corridor files.

    Inputs are an adequability raster array in the prepared working grid,
    GeoTransform/projection, point files, output base path, buffer width and
    search margin in meters. NaN cells are blocked. Cost is computed as
    1 / (adequability + 0.05). Route and corridor are written as GeoPackage
    files; corridor buffering is done in a metric CRS. Raises clear errors for
    invalid buffer/margin, unreachable endpoints or impossible paths.
    """
    if buffer_m <= 0:
        raise ValueError("A largura do corredor deve ser maior que zero.")
    if margin_m <= 0:
        raise ValueError("A margem de busca da rota deve ser maior que zero.")

    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    start_xy = transform_point_to_raster(start_path, proj)
    end_xy = transform_point_to_raster(end_path, proj)
    start_row, start_col = world_to_pixel(transform, start_xy[0], start_xy[1])
    end_row, end_col = world_to_pixel(transform, end_xy[0], end_xy[1])

    valid_mask = np.isfinite(score_array)
    start_row, start_col = nearest_valid_cell(valid_mask, start_row, start_col)
    end_row, end_col = nearest_valid_cell(valid_mask, end_row, end_col)

    margin_pixels = meters_to_pixels(transform, score_array.shape, proj, margin_m)
    row_min = max(0, min(start_row, end_row) - margin_pixels)
    row_max = min(score_array.shape[0], max(start_row, end_row) + margin_pixels + 1)
    col_min = max(0, min(start_col, end_col) - margin_pixels)
    col_max = min(score_array.shape[1], max(start_col, end_col) + margin_pixels + 1)

    score_crop = score_array[row_min:row_max, col_min:col_max]
    if score_crop.size > 8000000:
        raise Exception(
            "A area de busca da rota ficou grande demais. Reduza a margem de busca ou use pontos mais proximos "
            "para evitar travamento durante o calculo."
        )
    cost_crop = np.where(np.isfinite(score_crop), 1.0 / (score_crop + 0.05), np.inf).astype(np.float32)
    finite_costs = cost_crop[np.isfinite(cost_crop)]
    append_diagnostic_log(
        log_path,
        "superficie_custo_rota",
        metodo="cost = 1 / (adequabilidade + 0.05)",
        recorte_shape=list(cost_crop.shape),
        custo_min=float(np.nanmin(finite_costs)) if finite_costs.size else None,
        custo_max=float(np.nanmax(finite_costs)) if finite_costs.size else None,
        custo_medio=float(np.nanmean(finite_costs)) if finite_costs.size else None,
        celulas_bloqueadas=int(np.sum(~np.isfinite(cost_crop))),
        celulas_navegaveis=int(finite_costs.size),
    )
    local_start = (start_row - row_min, start_col - col_min)
    local_end = (end_row - row_min, end_col - col_min)

    if feedback:
        feedback.pushInfo(
            f"Planejamento de acesso: recorte {cost_crop.shape[1]} x {cost_crop.shape[0]} celulas; "
            f"margem {margin_m:.0f} m"
        )

    path_cells, accumulated_cost = least_cost_path(cost_crop, local_start, local_end)
    if len(path_cells) < 2:
        raise Exception(
            "O ponto inicial e o ponto final caem na mesma celula do raster. "
            "Use pontos mais afastados ou um raster de maior resolucao para gerar uma rota."
        )
    coordinates = [pixel_to_world(transform, row + row_min, col + col_min) for row, col in path_cells]
    line = LineString(coordinates)
    route_attributes = {
        "tipo": ["rota_principal"],
        "custo": [accumulated_cost],
        "vertices": [len(coordinates)],
    }
    if elevation_array is not None:
        route_altitudes = [
            float(elevation_array[row + row_min, col + col_min])
            for row, col in path_cells
            if np.isfinite(elevation_array[row + row_min, col + col_min])
        ]
        if route_altitudes:
            route_attributes.update(
                {
                    "alt_ini_m": [route_altitudes[0]],
                    "alt_fim_m": [route_altitudes[-1]],
                    "alt_min_m": [min(route_altitudes)],
                    "alt_max_m": [max(route_altitudes)],
                    "ganho_m": [max(route_altitudes) - route_altitudes[0]],
                }
            )

    raster_srs = osr.SpatialReference()
    raster_srs.ImportFromWkt(proj) if proj else raster_srs.ImportFromEPSG(4326)
    raster_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    crs_wkt = raster_srs.ExportToWkt()
    route_gdf = gpd.GeoDataFrame(
        route_attributes,
        geometry=[line],
        crs=crs_wkt,
    )

    base_path, _ = os.path.splitext(output_path)
    route_path = f"{base_path}_rota.gpkg"
    corridor_path = f"{base_path}_corredor.gpkg"

    try:
        metric_crs = metric_crs_for_raster(transform, score_array.shape, proj)
        metric_route = route_gdf.to_crs(metric_crs) if raster_srs.IsGeographic() else route_gdf
        route_gdf["compr_m"] = metric_route.geometry.length.values
        corridor_geometry = metric_route.geometry.buffer(buffer_m)
        corridor_gdf = gpd.GeoDataFrame(
            {"tipo": ["corredor_acesso"], "buffer_m": [buffer_m]},
            geometry=corridor_geometry,
            crs=metric_route.crs,
        )
        corridor_area_m2 = float(corridor_gdf.geometry.area.iloc[0]) if len(corridor_gdf) else None
        if raster_srs.IsGeographic():
            corridor_gdf = corridor_gdf.to_crs(crs_wkt)
    except Exception:
        route_gdf["compr_m"] = np.nan
        corridor_gdf = gpd.GeoDataFrame(
            {"tipo": ["corredor_acesso"], "buffer_m": [buffer_m]},
            geometry=route_gdf.geometry.buffer(0),
            crs=crs_wkt,
        )
        corridor_area_m2 = None

    if output_crs and output_crs.isValid():
        target_crs = output_crs.authid()
        if target_crs:
            route_gdf = route_gdf.to_crs(target_crs)
            corridor_gdf = corridor_gdf.to_crs(target_crs)
            if feedback:
                feedback.pushInfo(f"Rota e corredor reprojetados para {target_crs}")

    gpkg_driver = ogr.GetDriverByName("GPKG")
    for path in [route_path, corridor_path]:
        if gpkg_driver and os.path.exists(path):
            try:
                gpkg_driver.DeleteDataSource(path)
            except RuntimeError:
                if path == route_path:
                    route_path = available_output_path(route_path)
                else:
                    corridor_path = available_output_path(corridor_path)
                if feedback:
                    feedback.pushWarning(
                        "Uma saida de rota/corredor anterior esta em uso no QGIS ou bloqueada pelo sistema. "
                        "Salvando com novo nome."
                    )

    route_gdf.to_file(route_path, driver="GPKG")
    corridor_gdf.to_file(corridor_path, driver="GPKG")

    if feedback:
        length = route_gdf["compr_m"].iloc[0]
        feedback.pushInfo(f"Rota de acesso salva: {route_path}")
        feedback.pushInfo(f"Corredor de acesso salvo: {corridor_path}")
        if np.isfinite(length):
            feedback.pushInfo(f"Comprimento estimado da rota: {length:.1f} m")
    append_diagnostic_log(
        log_path,
        "rota_calculada",
        custo_acumulado=float(accumulated_cost),
        celulas_percorridas=int(len(path_cells)),
        vertices=int(len(coordinates)),
        comprimento_m=float(route_gdf["compr_m"].iloc[0]) if "compr_m" in route_gdf and np.isfinite(route_gdf["compr_m"].iloc[0]) else None,
        buffer_m=float(buffer_m),
        crs_buffer=str(corridor_gdf.crs),
        area_corredor_m2=corridor_area_m2,
        extensao_corredor=list(corridor_gdf.total_bounds) if len(corridor_gdf) else None,
        geometrias_corredor=int(len(corridor_gdf)),
    )

    return route_path, corridor_path


class TopotrailAlgorithm(QgsProcessingAlgorithm):
    INPUT_DEM = "INPUT_DEM"
    INPUT_SLOPE = "INPUT_SLOPE"
    INPUT_CURVH = "INPUT_CURVH"
    INPUT_CURVV = "INPUT_CURVV"
    OUTPUT_CRS = "OUTPUT_CRS"
    ALT_MIN = "ALT_MIN"
    ALT_MAX = "ALT_MAX"
    SLOPE_MAX = "SLOPE_MAX"
    SLOPE_SCORE_MAX = "SLOPE_SCORE_MAX"
    WEIGHT_ALT = "WEIGHT_ALT"
    WEIGHT_SLOPE = "WEIGHT_SLOPE"
    WEIGHT_CURVH = "WEIGHT_CURVH"
    WEIGHT_CURVV = "WEIGHT_CURVV"
    MIN_PATCH_AREA_HA = "MIN_PATCH_AREA_HA"
    THRESHOLD = "THRESHOLD"
    AUTO_PERCENTILE = "AUTO_PERCENTILE"
    ALTITUDE_BAND_THRESHOLD = "ALTITUDE_BAND_THRESHOLD"
    ALTITUDE_BAND_SIZE_M = "ALTITUDE_BAND_SIZE_M"
    WALKABILITY_ZONES = "WALKABILITY_ZONES"
    START_POINT_FILE = "START_POINT_FILE"
    END_POINT_FILE = "END_POINT_FILE"
    ROUTE_BUFFER_M = "ROUTE_BUFFER_M"
    ROUTE_MARGIN_M = "ROUTE_MARGIN_M"
    GENERATE_ZONES = "GENERATE_ZONES"
    OUTPUT_FORMAT = "OUTPUT_FORMAT"
    OUTPUT_FILE = "OUTPUT_FILE"
    OUTPUT_VECTOR = "OUTPUT_VECTOR"
    OUTPUT_SCORE_RASTER = "OUTPUT_SCORE_RASTER"
    OUTPUT_RISK_RASTER = "OUTPUT_RISK_RASTER"
    OUTPUT_ROUTE = "OUTPUT_ROUTE"
    OUTPUT_CORRIDOR = "OUTPUT_CORRIDOR"
    OUTPUT_DEBUG_LOG = "OUTPUT_DEBUG_LOG"

    def tr(self, string):
        return QCoreApplication.translate("Processing", string)

    def createInstance(self):
        return TopotrailAlgorithm()

    def name(self):
        return "topotrail"

    def displayName(self):
        return self.tr("TopoTrail - Análise Multicritério")

    def group(self):
        return self.tr("TopoTrail")

    def groupId(self):
        return "topotrail"

    def shortHelpString(self):
        return self.tr(
            "Gera zonas potenciais de trilhas por restrições booleanas e combinação linear ponderada."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT_DEM, self.tr("Altitude / MDE")))
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT_SLOPE, self.tr("Declividade")))
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT_CURVH, self.tr("Curvatura horizontal")))
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT_CURVV, self.tr("Curvatura vertical")))

        self.addParameter(
            QgsProcessingParameterNumber(
                self.ALT_MIN,
                self.tr("Altitude mínima para zonas (m)"),
                QgsProcessingParameterNumber.Double,
                defaultValue=0.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ALT_MAX,
                self.tr("Altitude máxima para zonas (m)"),
                QgsProcessingParameterNumber.Double,
                defaultValue=2600.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SLOPE_MAX,
                self.tr("Declividade maxima absoluta (%)"),
                QgsProcessingParameterNumber.Double,
                defaultValue=55.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SLOPE_SCORE_MAX,
                self.tr("Declividade de custo maximo (%)"),
                QgsProcessingParameterNumber.Double,
                defaultValue=50.0,
                minValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.THRESHOLD,
                self.tr("Threshold para binarização (0 = percentil automático)"),
                QgsProcessingParameterNumber.Double,
                defaultValue=0.0,
                minValue=0.0,
                maxValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.AUTO_PERCENTILE,
                self.tr("Percentil automatico"),
                QgsProcessingParameterNumber.Double,
                defaultValue=75.0,
                minValue=1.0,
                maxValue=99.0,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.MIN_PATCH_AREA_HA,
                self.tr("Area minima do fragmento (ha)"),
                QgsProcessingParameterNumber.Double,
                defaultValue=50.0,
                minValue=0.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.ALTITUDE_BAND_THRESHOLD,
                self.tr("Equilibrar zonas por faixa altimetrica"),
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ALTITUDE_BAND_SIZE_M,
                self.tr("Tamanho da faixa altimetrica (m)"),
                QgsProcessingParameterNumber.Double,
                defaultValue=200.0,
                minValue=50.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.WALKABILITY_ZONES,
                self.tr("Gerar zonas como area caminhavel continua"),
                defaultValue=True,
            )
        )

        for key, label, default in [
            (self.WEIGHT_ALT, "Peso da altitude", 0.0),
            (self.WEIGHT_SLOPE, "Peso da declividade", 1.0),
            (self.WEIGHT_CURVH, "Peso da curvatura horizontal", 1.0),
            (self.WEIGHT_CURVV, "Peso da curvatura vertical", 1.0),
        ]:
            self.addParameter(
                QgsProcessingParameterNumber(
                    key,
                    self.tr(label),
                    QgsProcessingParameterNumber.Double,
                    defaultValue=default,
                    minValue=0.0,
                    maxValue=10.0,
                )
            )

        self.addParameter(
            QgsProcessingParameterFile(
                self.START_POINT_FILE,
                self.tr("Ponto inicial para rota (opcional)"),
                behavior=QgsProcessingParameterFile.File,
                fileFilter="Vetores (*.gpkg *.shp *.kml *.geojson)",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.END_POINT_FILE,
                self.tr("Ponto final / destino (opcional)"),
                behavior=QgsProcessingParameterFile.File,
                fileFilter="Vetores (*.gpkg *.shp *.kml *.geojson)",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ROUTE_BUFFER_M,
                self.tr("Largura do corredor de acesso (m)"),
                QgsProcessingParameterNumber.Double,
                defaultValue=100.0,
                minValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ROUTE_MARGIN_M,
                self.tr("Margem lateral de busca da rota (m)"),
                QgsProcessingParameterNumber.Double,
                defaultValue=5000.0,
                minValue=100.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.GENERATE_ZONES,
                self.tr("Gerar zonas vetoriais"),
                defaultValue=False,
            )
        )

        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_FILE,
                self.tr("Arquivo de saída"),
                "Vetores (*.shp *.gpkg *.kml)",
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.OUTPUT_FORMAT,
                self.tr("Formato de saída"),
                options=["Shapefile", "GeoPackage", "KML"],
                defaultValue=1,
            )
        )
        self.addParameter(
            QgsProcessingParameterCrs(
                self.OUTPUT_CRS,
                self.tr("CRS de saída"),
                defaultValue=QgsProject.instance().crs().authid(),
            )
        )
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT_VECTOR, self.tr("Zonas potenciais")))
        self.addOutput(QgsProcessingOutputRasterLayer(self.OUTPUT_SCORE_RASTER, self.tr("Adequabilidade continua")))
        self.addOutput(QgsProcessingOutputRasterLayer(self.OUTPUT_RISK_RASTER, self.tr("Risco topografico relativo")))
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT_ROUTE, self.tr("Rota de acesso sugerida")))
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT_CORRIDOR, self.tr("Corredor de acesso")))
        self.addOutput(QgsProcessingOutputFile(self.OUTPUT_DEBUG_LOG, self.tr("Log diagnostico TopoTrail")))

    def processAlgorithm(self, parameters, context, feedback):
        dem_layer = self.parameterAsRasterLayer(parameters, self.INPUT_DEM, context)
        slope_layer = self.parameterAsRasterLayer(parameters, self.INPUT_SLOPE, context)
        curvh_layer = self.parameterAsRasterLayer(parameters, self.INPUT_CURVH, context)
        curvv_layer = self.parameterAsRasterLayer(parameters, self.INPUT_CURVV, context)

        for label, layer in [
            ("Altitude / MDE", dem_layer),
            ("Declividade", slope_layer),
            ("Curvatura horizontal", curvh_layer),
            ("Curvatura vertical", curvv_layer),
        ]:
            if layer is None:
                raise Exception(f"Camada obrigatória ausente: {label}")
            if not layer.crs().isValid():
                raise Exception(f"O raster {label} não possui CRS definido.")
            if not os.path.exists(layer.source()):
                raise Exception(f"Arquivo não encontrado para {label}: {layer.source()}")

        min_altitude = self.parameterAsDouble(parameters, self.ALT_MIN, context)
        max_altitude = self.parameterAsDouble(parameters, self.ALT_MAX, context)
        max_slope = self.parameterAsDouble(parameters, self.SLOPE_MAX, context)
        slope_score_max = self.parameterAsDouble(parameters, self.SLOPE_SCORE_MAX, context)
        threshold = self.parameterAsDouble(parameters, self.THRESHOLD, context)
        auto_percentile = self.parameterAsDouble(parameters, self.AUTO_PERCENTILE, context)
        min_patch_area_ha = self.parameterAsDouble(parameters, self.MIN_PATCH_AREA_HA, context)
        altitude_band_threshold = self.parameterAsBool(parameters, self.ALTITUDE_BAND_THRESHOLD, context)
        altitude_band_size_m = self.parameterAsDouble(parameters, self.ALTITUDE_BAND_SIZE_M, context)
        walkability_zones = self.parameterAsBool(parameters, self.WALKABILITY_ZONES, context)
        start_point_file = self.parameterAsFile(parameters, self.START_POINT_FILE, context)
        end_point_file = self.parameterAsFile(parameters, self.END_POINT_FILE, context)
        route_buffer_m = self.parameterAsDouble(parameters, self.ROUTE_BUFFER_M, context)
        route_margin_m = self.parameterAsDouble(parameters, self.ROUTE_MARGIN_M, context)
        generate_zones = self.parameterAsBool(parameters, self.GENERATE_ZONES, context)
        altitude_weight = self.parameterAsDouble(parameters, self.WEIGHT_ALT, context)
        slope_weight = self.parameterAsDouble(parameters, self.WEIGHT_SLOPE, context)
        curvh_weight = self.parameterAsDouble(parameters, self.WEIGHT_CURVH, context)
        curvv_weight = self.parameterAsDouble(parameters, self.WEIGHT_CURVV, context)
        total_weight = altitude_weight + slope_weight + curvh_weight + curvv_weight

        output_path = self.parameterAsFileOutput(parameters, self.OUTPUT_FILE, context)
        output_format_idx = self.parameterAsEnum(parameters, self.OUTPUT_FORMAT, context)
        output_formats = ["Shapefile", "GeoPackage", "KML"]
        output_format = output_formats[output_format_idx] if 0 <= output_format_idx < len(output_formats) else "Shapefile"
        output_crs = self.parameterAsCrs(parameters, self.OUTPUT_CRS, context)
        output_path = ensure_output_extension(output_path, output_format)
        debug_log_path = diagnostic_log_path(output_path)
        append_diagnostic_log(
            debug_log_path,
            "processamento_iniciado",
            plugin="TopoTrail",
            ambiente=dependency_diagnostics(),
            output_path=output_path,
            output_format=output_format,
            output_crs=output_crs.authid() if output_crs and output_crs.isValid() else None,
            inputs={
                "dem": file_diagnostics(dem_layer.source() if dem_layer else ""),
                "slope": file_diagnostics(slope_layer.source() if slope_layer else ""),
                "curvatura_horizontal": file_diagnostics(curvh_layer.source() if curvh_layer else ""),
                "curvatura_vertical": file_diagnostics(curvv_layer.source() if curvv_layer else ""),
                "ponto_inicial": file_diagnostics(start_point_file),
                "ponto_final": file_diagnostics(end_point_file),
            },
            parametros={
                "altitude_min_m": min_altitude,
                "altitude_max_m": max_altitude,
                "declividade_max_abs_pct": max_slope,
                "declividade_custo_max_pct": slope_score_max,
                "threshold": threshold,
                "percentil_automatico": auto_percentile,
                "area_min_fragmento_ha": min_patch_area_ha,
                "zonas_como_area_caminhavel": walkability_zones,
                "threshold_por_faixa_altimetrica": altitude_band_threshold,
                "faixa_altimetrica_m": altitude_band_size_m,
                "pesos": {
                    "altitude": altitude_weight,
                    "declividade": slope_weight,
                    "curvatura_horizontal": curvh_weight,
                    "curvatura_vertical": curvv_weight,
                },
                "gerar_zonas_vetoriais": generate_zones,
                "corredor_m": route_buffer_m,
                "margem_busca_m": route_margin_m,
            },
        )
        if bool(start_point_file) != bool(end_point_file):
            message = "Informe os dois pontos: inicial e final. Para gerar rota, ambos sao obrigatorios."
            append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
            raise Exception(message)
        for point_file, label in [(start_point_file, "ponto inicial"), (end_point_file, "ponto final")]:
            if point_file and not os.path.exists(point_file):
                message = f"Arquivo do {label} nao encontrado: {point_file}"
                append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
                raise Exception(message)

        if total_weight <= 0:
            message = "A soma dos pesos deve ser maior que zero."
            append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
            raise ValueError(message)
        if any(weight < 0 for weight in [altitude_weight, slope_weight, curvh_weight, curvv_weight]):
            message = "Os pesos nao podem ser negativos."
            append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
            raise ValueError(message)
        if min_altitude >= max_altitude:
            message = "A altitude minima deve ser menor que a altitude maxima."
            append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
            raise ValueError(message)
        if max_slope <= 0 or slope_score_max <= 0:
            message = "Os limites de declividade devem ser maiores que zero."
            append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
            raise ValueError(message)
        if min_patch_area_ha < 0:
            message = "A area minima do fragmento nao pode ser negativa."
            append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
            raise ValueError(message)
        if not (0 <= threshold <= 1):
            message = "O threshold deve estar entre 0 e 1."
            append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
            raise ValueError(message)
        if not (0 < auto_percentile < 100):
            message = "O percentil automatico deve estar entre 0 e 100."
            append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
            raise ValueError(message)
        if route_buffer_m <= 0 or route_margin_m <= 0:
            message = "Corredor e margem de busca devem ser maiores que zero."
            append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
            raise ValueError(message)

        if feedback:
            feedback.pushInfo("=== PARÂMETROS CONFIGURADOS ===")
            feedback.pushInfo(f"Log diagnostico: {debug_log_path}")
            feedback.pushInfo(f"Altitude mínima: {min_altitude}")
            feedback.pushInfo(f"Altitude máxima: {max_altitude}")
            feedback.pushInfo(f"Declividade máxima: {max_slope}%")
            feedback.pushInfo(f"Declividade de custo maximo: {slope_score_max}%")
            feedback.pushInfo(f"Threshold: {threshold}")
            feedback.pushInfo(f"Percentil automatico: {auto_percentile}")
            feedback.pushInfo(f"Area minima do fragmento: {min_patch_area_ha} ha")
            feedback.pushInfo(
                f"Zonas vetoriais: {'sim' if generate_zones else 'nao'}; "
                f"modo caminhavel: {'sim' if walkability_zones else 'nao'}; "
                f"threshold por faixa altimetrica: {'sim' if altitude_band_threshold else 'nao'} "
                f"({altitude_band_size_m:.0f} m)"
            )
            feedback.pushInfo(f"Pesos: altitude={altitude_weight}, declividade={slope_weight}, curvH={curvh_weight}, curvV={curvv_weight}")
            feedback.pushInfo(f"Formato de saída: {output_format}")
            feedback.pushInfo("================================")

        temp_work_dir = tempfile.mkdtemp(prefix="topotrail_work_")
        dem_crs_info = ensure_projected_working_crs(
            dem_layer.source(),
            feedback=feedback,
            temp_dir=temp_work_dir,
            log_path=debug_log_path,
        )
        dem_path = dem_crs_info["dem_path"]
        prepared_rasters = {"dem": dem_path}
        for label, source_path, key in [
            ("Declividade", slope_layer.source(), "slope"),
            ("Curvatura horizontal", curvh_layer.source(), "curvh"),
            ("Curvatura vertical", curvv_layer.source(), "curvv"),
        ]:
            compatibility = validate_raster_grid_compatibility(dem_path, source_path)
            append_diagnostic_log(
                debug_log_path,
                "compatibilidade_raster",
                raster=label,
                entrada=source_path,
                compatibilidade=compatibility,
            )
            if compatibility["compatible"]:
                prepared_rasters[key] = source_path
            else:
                aligned_path = os.path.join(temp_work_dir, f"{key}_alinhado.tif")
                prepared_rasters[key] = align_raster_to_reference(
                    source_path,
                    dem_path,
                    aligned_path,
                    resampling="bilinear",
                    feedback=feedback,
                    log_path=debug_log_path,
                )

        dem_data, transform, proj = read_raster(prepared_rasters["dem"], feedback)
        slope_data, slope_transform, slope_proj = read_raster(prepared_rasters["slope"], feedback)
        curvh_data, curvh_transform, curvh_proj = read_raster(prepared_rasters["curvh"], feedback)
        curvv_data, curvv_transform, curvv_proj = read_raster(prepared_rasters["curvv"], feedback)
        append_diagnostic_log(
            debug_log_path,
            "rasters_lidos",
            crs_trabalho=dem_crs_info,
            caminhos_preparados=prepared_rasters,
            transform=list(transform) if transform else None,
            projection_wkt_start=proj[:300] if proj else None,
            dem=array_diagnostics(dem_data),
            declividade=array_diagnostics(slope_data),
            curvatura_horizontal=array_diagnostics(curvh_data),
            curvatura_vertical=array_diagnostics(curvv_data),
        )

        validate_raster_alignment(
            dem_data.shape,
            transform,
            [
                ("Declividade", slope_data, slope_transform),
                ("Curvatura horizontal", curvh_data, curvh_transform),
                ("Curvatura vertical", curvv_data, curvv_transform),
            ],
            feedback,
        )

        for label, raster_proj in [
            ("Declividade", slope_proj),
            ("Curvatura horizontal", curvh_proj),
            ("Curvatura vertical", curvv_proj),
        ]:
            if proj and raster_proj and proj != raster_proj:
                raise Exception(f"{label} possui projeção diferente do MDE.")

        altitude_norm = normalize_linear(dem_data, min_altitude, max_altitude, feedback, "Altitude")
        slope_norm = normalize_cost(slope_data, 0, slope_score_max, feedback, "Declividade")
        curvh_norm = normalize_curvature_preference(curvh_data, feedback, "Curvatura horizontal")
        curvv_norm = normalize_curvature_preference(curvv_data, feedback, "Curvatura vertical")

        valid_mask = ~np.isnan(dem_data) & ~np.isnan(slope_data) & ~np.isnan(curvh_data) & ~np.isnan(curvv_data)
        zone_constraint_mask = (
            valid_mask
            & (dem_data >= min_altitude)
            & (dem_data <= max_altitude)
            & (slope_data <= max_slope)
        )
        route_constraint_mask = valid_mask & (slope_data <= max_slope)

        if feedback:
            viable = int(np.sum(zone_constraint_mask))
            route_viable = int(np.sum(route_constraint_mask))
            feedback.pushInfo(f"Máscara de zonas: {viable} pixels viáveis de {dem_data.size} ({viable / dem_data.size * 100:.2f}%)")
            feedback.pushInfo(f"Máscara de rota: {route_viable} pixels navegáveis de {dem_data.size} ({route_viable / dem_data.size * 100:.2f}%)")
        append_diagnostic_log(
            debug_log_path,
            "mascara_booleana",
            pixels_total=int(dem_data.size),
            pixels_validos_entrada=int(np.sum(valid_mask)),
            pixels_viaveis_zonas=int(np.sum(zone_constraint_mask)),
            proporcao_viavel_zonas=float(np.sum(zone_constraint_mask) / dem_data.size),
            pixels_navegaveis_rota=int(np.sum(route_constraint_mask)),
            proporcao_navegavel_rota=float(np.sum(route_constraint_mask) / dem_data.size),
            pixels_altitude_baixa=int(np.sum(valid_mask & (dem_data < min_altitude))),
            pixels_altitude_alta=int(np.sum(valid_mask & (dem_data > max_altitude))),
            pixels_declividade_acima_limite=int(np.sum(valid_mask & (slope_data > max_slope))),
        )

        raw_score = (
            altitude_weight * altitude_norm
            + slope_weight * slope_norm
            + curvh_weight * curvh_norm
            + curvv_weight * curvv_norm
        ) / total_weight
        zone_score = np.where(zone_constraint_mask, raw_score, np.nan).astype(np.float32)
        route_score = np.where(route_constraint_mask, raw_score, np.nan).astype(np.float32)
        output_score = zone_score if generate_zones else route_score
        risk_score = compute_topographic_risk(slope_data, curvh_data, curvv_data, valid_mask, max_slope, feedback)

        zone_valid_scores = zone_score[~np.isnan(zone_score)]
        route_valid_scores = route_score[~np.isnan(route_score)]
        if generate_zones and zone_valid_scores.size == 0:
            raise Exception("Nenhum pixel atende às restrições configuradas para zonas potenciais.")
        if start_point_file and end_point_file and route_valid_scores.size == 0:
            raise Exception("Nenhum pixel navegável atende às restrições de rota. Aumente o limite de declividade máxima.")
        if not generate_zones and not (start_point_file and end_point_file) and route_valid_scores.size == 0:
            raise Exception("Nenhum pixel atende às restrições configuradas.")

        threshold_is_auto = threshold is None or threshold == 0
        if generate_zones and not walkability_zones and threshold_is_auto:
            threshold = float(np.percentile(zone_valid_scores, auto_percentile))
            if feedback:
                feedback.pushInfo(f"Threshold automatico pelo percentil {auto_percentile:.1f}: {threshold:.4f}")
                if altitude_band_threshold:
                    feedback.pushInfo("Zonas vetoriais usarao threshold automatico por faixa altimetrica.")
        append_diagnostic_log(
            debug_log_path,
            "score_e_threshold",
            threshold_final=threshold,
            threshold_automatico=threshold_is_auto,
            score_zonas=array_diagnostics(zone_score),
            score_rota=array_diagnostics(route_score),
            risco_topografico=array_diagnostics(risk_score),
        )

        if feedback:
            if zone_valid_scores.size:
                feedback.pushInfo(
                    f"Score zonas: min={np.nanmin(zone_valid_scores):.4f}, "
                    f"max={np.nanmax(zone_valid_scores):.4f}, mean={np.nanmean(zone_valid_scores):.4f}"
                )
            if route_valid_scores.size:
                feedback.pushInfo(
                    f"Score rota: min={np.nanmin(route_valid_scores):.4f}, "
                    f"max={np.nanmax(route_valid_scores):.4f}, mean={np.nanmean(route_valid_scores):.4f}"
                )

        score_path = save_score_raster(output_score, transform, proj, output_path, feedback)
        risk_path = save_risk_raster(risk_score, transform, proj, output_path, feedback)
        append_diagnostic_log(debug_log_path, "raster_adequabilidade_salvo", arquivo=file_diagnostics(score_path))
        append_diagnostic_log(debug_log_path, "raster_risco_topografico_salvo", arquivo=file_diagnostics(risk_path))
        route_path = None
        corridor_path = None
        if start_point_file and end_point_file:
            route_path, corridor_path = save_access_route(
                route_score,
                transform,
                proj,
                start_point_file,
                end_point_file,
                output_path,
                route_buffer_m,
                route_margin_m,
                feedback,
                dem_data,
                output_crs,
                debug_log_path,
            )
            append_diagnostic_log(
                debug_log_path,
                "rota_e_corredor_salvos",
                rota=file_diagnostics(route_path),
                corredor=file_diagnostics(corridor_path),
            )
        gdf = None
        if generate_zones:
            if walkability_zones:
                binary_result = build_walkability_mask(zone_constraint_mask, feedback)
            elif altitude_band_threshold and threshold_is_auto:
                binary_result = binarize_by_altitude_bands(
                    zone_score,
                    dem_data,
                    auto_percentile,
                    altitude_band_size_m,
                    feedback,
                )
            else:
                binary_result = binarize_result(zone_score, threshold, feedback)
            append_diagnostic_log(
                debug_log_path,
                "zonas_binarizadas",
                pixels_aptos_antes_filtro=int(np.sum(binary_result == 1)),
                modo_caminhavel=bool(walkability_zones),
                threshold_por_faixa_altimetrica=bool(altitude_band_threshold and threshold_is_auto and not walkability_zones),
            )
            binary_result = filter_small_regions(binary_result, transform, proj, min_patch_area_ha, feedback, debug_log_path)
            append_diagnostic_log(
                debug_log_path,
                "zonas_filtradas",
                pixels_aptos_apos_filtro=int(np.sum(binary_result == 1)),
                area_min_fragmento_ha=min_patch_area_ha,
            )
            gdf = vectorize_binary_raster(binary_result, transform, proj, feedback)
            append_diagnostic_log(
                debug_log_path,
                "zonas_vetorizadas",
                feicoes=int(len(gdf)),
                colunas=list(gdf.columns),
                crs=str(gdf.crs),
            )

            if len(gdf) > 0:
                area_crs = metric_crs_for_raster(transform, dem_data.shape, proj)
                try:
                    area_gdf = gdf.to_crs(area_crs)
                    gdf["area_m2"] = area_gdf.geometry.area.values
                    gdf["area_ha"] = gdf["area_m2"] / 10000.0
                except Exception as e:
                    if feedback:
                        feedback.pushWarning(f"Não foi possível calcular áreas em CRS métrico: {str(e)}")
        elif feedback:
            feedback.pushInfo("Geracao de zonas vetoriais desativada; raster, rota e corredor foram preservados.")
        result = {self.OUTPUT_SCORE_RASTER: score_path, self.OUTPUT_RISK_RASTER: risk_path}
        if gdf is not None and len(gdf) > 0:
            vector_path = save_vector(gdf, output_path, output_format, output_crs, feedback)
            result[self.OUTPUT_VECTOR] = vector_path
            append_diagnostic_log(debug_log_path, "vetor_zonas_salvo", arquivo=file_diagnostics(vector_path))
        elif generate_zones and feedback:
            feedback.pushWarning("Nenhuma zona potencial atingiu o threshold configurado; raster e rota foram preservados.")
        if route_path:
            result[self.OUTPUT_ROUTE] = route_path
        if corridor_path:
            result[self.OUTPUT_CORRIDOR] = corridor_path
        result[self.OUTPUT_DEBUG_LOG] = debug_log_path
        append_diagnostic_log(debug_log_path, "processamento_concluido", outputs=result)
        return result
