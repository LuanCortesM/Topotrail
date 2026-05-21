import csv
import json
import math
import os
from datetime import datetime

import geopandas as gpd
import numpy as np
from osgeo import gdal, osr
from shapely.geometry import LineString
from shapely.ops import nearest_points

from .algorithm import (
    append_diagnostic_log,
    array_diagnostics,
    least_cost_path,
    metric_crs_for_raster,
    pixel_to_world,
    world_to_pixel,
)


DEFAULT_SCENARIOS = {
    "curta": {
        "label": "Rota mais curta",
        "slope_weight": 0.35,
        "curvature_weight": 0.10,
        "risk_weight": 0.15,
        "distance_bias": 0.40,
        "max_slope_deg": 45.0,
        "max_risk": 0.95,
        "buffer_m": 60.0,
        "description": "Prioriza caminho direto com penalizacao topografica moderada.",
    },
    "suave": {
        "label": "Rota mais suave",
        "slope_weight": 1.45,
        "curvature_weight": 0.25,
        "risk_weight": 0.40,
        "distance_bias": 0.10,
        "max_slope_deg": 42.0,
        "max_risk": 0.90,
        "buffer_m": 80.0,
        "description": "Penaliza fortemente declividade alta e prefere encostas menos inclinadas.",
    },
    "segura": {
        "label": "Rota mais segura",
        "slope_weight": 1.10,
        "curvature_weight": 0.45,
        "risk_weight": 1.25,
        "distance_bias": 0.05,
        "max_slope_deg": 35.0,
        "max_risk": 0.72,
        "buffer_m": 100.0,
        "description": "Penaliza fortemente risco alto e bloqueia risco extremo, buscando reduzir exposicao a terrenos perigosos quando houver alternativa espacial.",
    },
    "conservadora": {
        "label": "Rota conservadora",
        "slope_weight": 1.60,
        "curvature_weight": 0.90,
        "risk_weight": 1.35,
        "distance_bias": 0.05,
        "max_slope_deg": 30.0,
        "max_risk": 0.65,
        "curvature_percentile_block": 95.0,
        "buffer_m": 120.0,
        "description": "Bloqueia declividade acima de 30 graus e penaliza curvaturas extremas.",
    },
    "exploratoria": {
        "label": "Rota exploratoria",
        "slope_weight": 0.65,
        "curvature_weight": 0.25,
        "risk_weight": 0.50,
        "distance_bias": 0.15,
        "max_slope_deg": 48.0,
        "max_risk": 0.98,
        "buffer_m": 70.0,
        "description": "Permite maior variacao topografica, evitando NoData e risco extremo.",
    },
}


DEFAULT_RISK_THRESHOLDS = {
    "low_max": 15.0,
    "moderate_max": 25.0,
    "high_max": 35.0,
    "very_high_max": 45.0,
    "curvature_extreme_percentile": 98.0,
}


def _finite_norm(array, upper=None):
    values = array[np.isfinite(array)]
    result = np.zeros_like(array, dtype=np.float32)
    if values.size == 0:
        result[:] = np.nan
        return result
    limit = float(upper) if upper is not None else float(np.nanpercentile(values, 95))
    if not np.isfinite(limit) or limit <= 0:
        limit = float(np.nanmax(values)) if values.size else 1.0
    if not np.isfinite(limit) or limit <= 0:
        limit = 1.0
    mask = np.isfinite(array)
    result[mask] = np.clip(array[mask] / limit, 0, 1)
    result[~mask] = np.nan
    return result


def classify_topographic_risk(slope, curvature_horizontal, curvature_vertical, thresholds=None):
    """Classify terrain risk from slope degrees and curvature magnitudes.

    Returns an integer array: 0 low, 1 moderate, 2 high, 3 very high, 4 blocked.
    NoData and curvature above the configured extreme percentile are blocked.
    """
    thresholds = {**DEFAULT_RISK_THRESHOLDS, **(thresholds or {})}
    risk_class = np.full(slope.shape, 4, dtype=np.uint8)
    valid = np.isfinite(slope) & np.isfinite(curvature_horizontal) & np.isfinite(curvature_vertical)
    curvature_mag = np.sqrt(curvature_horizontal ** 2 + curvature_vertical ** 2)
    finite_curv = curvature_mag[np.isfinite(curvature_mag) & valid]
    if finite_curv.size:
        curv_limit = float(np.nanpercentile(finite_curv, thresholds["curvature_extreme_percentile"]))
    else:
        curv_limit = np.inf
    usable = valid & (curvature_mag <= curv_limit)
    risk_class[usable & (slope < thresholds["low_max"])] = 0
    risk_class[usable & (slope >= thresholds["low_max"]) & (slope < thresholds["moderate_max"])] = 1
    risk_class[usable & (slope >= thresholds["moderate_max"]) & (slope < thresholds["high_max"])] = 2
    risk_class[usable & (slope >= thresholds["high_max"]) & (slope <= thresholds["very_high_max"])] = 3
    risk_class[usable & (slope > thresholds["very_high_max"])] = 4
    return risk_class


def build_cost_surface_for_scenario(
    adequability,
    slope,
    curvature_horizontal,
    curvature_vertical,
    risk,
    scenario_name,
    parameters=None,
):
    """Build a least-cost surface for a route scenario.

    Cost is based on inverse adequability plus configurable penalties for slope,
    curvature and risk. Blocked cells are set to np.inf.
    """
    scenario = {**DEFAULT_SCENARIOS.get(scenario_name, {}), **(parameters or {})}
    if not scenario:
        raise ValueError(f"Cenario desconhecido: {scenario_name}")

    epsilon = float(scenario.get("epsilon", 0.05))
    valid_adequability = np.isfinite(adequability)
    valid_slope = np.isfinite(slope)
    valid_curv_h = np.isfinite(curvature_horizontal)
    valid_curv_v = np.isfinite(curvature_vertical)
    valid_risk = np.isfinite(risk)
    valid = valid_adequability & valid_slope & valid_curv_h & valid_curv_v & valid_risk
    base_cost = np.full(adequability.shape, np.inf, dtype=np.float32)
    base_cost[valid] = 1.0 / (np.clip(adequability[valid], 0, 1) + epsilon)

    slope_cost = _finite_norm(slope, upper=scenario.get("slope_norm_max", 45.0))
    curvature_mag = np.sqrt(curvature_horizontal ** 2 + curvature_vertical ** 2)
    curvature_cost = _finite_norm(curvature_mag)
    risk_cost = np.clip(risk, 0, 1).astype(np.float32)

    slope_component = float(scenario.get("slope_weight", 0)) * slope_cost
    curvature_component = float(scenario.get("curvature_weight", 0)) * curvature_cost
    risk_component = float(scenario.get("risk_weight", 0)) * risk_cost
    distance_component = float(scenario.get("distance_bias", 0))
    final_cost = (
        base_cost + slope_component + curvature_component + risk_component + distance_component
    ).astype(np.float32)

    blocked = ~valid
    if "max_slope_deg" in scenario:
        blocked |= slope > float(scenario["max_slope_deg"])
    if "max_risk" in scenario:
        blocked |= risk > float(scenario["max_risk"])
    if "curvature_percentile_block" in scenario:
        values = curvature_mag[np.isfinite(curvature_mag) & valid]
        if values.size:
            blocked |= curvature_mag > float(np.nanpercentile(values, scenario["curvature_percentile_block"]))

    final_cost[blocked] = np.inf
    metadata = {
        "scenario_name": scenario_name,
        "label": scenario.get("label", scenario_name),
        "description": scenario.get("description", ""),
        "parameters": scenario,
        "blocked_cells": int(np.sum(blocked)),
        "navigable_cells": int(np.sum(np.isfinite(final_cost))),
        "cost_stats": array_diagnostics(np.where(np.isfinite(final_cost), final_cost, np.nan)),
        "formula": "cost = 1/(adequability + epsilon) + w_slope*slope_norm + w_curvature*curvature_norm + w_risk*risk + distance_bias",
    }
    explanation = (
        f"{metadata['label']}: {metadata['description']} "
        f"Pesos: declividade={scenario.get('slope_weight')}, "
        f"curvatura={scenario.get('curvature_weight')}, risco={scenario.get('risk_weight')}."
    )
    metadata["explanation"] = explanation
    return final_cost, blocked, metadata, explanation


def validate_start_end_points(
    dem_array,
    transform,
    start_point,
    end_point,
    expected_start_altitude=None,
    expected_end_altitude=None,
    tolerance_m=100,
    strict=False,
    strict_altitude=False,
    slope=None,
    risk=None,
    navigable_mask=None,
):
    """Validate route endpoints against raster extent, altitude and optional terrain layers."""
    messages = []
    rows, cols = dem_array.shape
    result = {"valid": True, "warnings": messages}

    def sample(point, label):
        row, col = world_to_pixel(transform, point[0], point[1])
        info = {
            "row": row,
            "col": col,
            "inside": False,
            "altitude": None,
            "slope": None,
            "risk": None,
            "navigable": None,
        }
        if row < 0 or row >= rows or col < 0 or col >= cols:
            message = f"{label} fora da extensao do raster."
            if strict:
                raise ValueError(message)
            messages.append(message)
            return info
        info["inside"] = True
        value = dem_array[row, col]
        if not np.isfinite(value):
            message = f"{label} cai em celula sem altitude valida."
            if strict:
                raise ValueError(message)
            messages.append(message)
        else:
            info["altitude"] = float(value)
        if slope is not None:
            slope_value = slope[row, col]
            info["slope"] = float(slope_value) if np.isfinite(slope_value) else None
        if risk is not None:
            risk_value = risk[row, col]
            info["risk"] = float(risk_value) if np.isfinite(risk_value) else None
        if navigable_mask is not None:
            info["navigable"] = bool(navigable_mask[row, col])
            if not info["navigable"]:
                message = f"{label} cai em celula nao navegavel."
                if strict:
                    raise ValueError(message)
                messages.append(message)
        return info

    start_info = sample(start_point, "Origem")
    end_info = sample(end_point, "Destino")
    for label, actual, expected in [
        ("Origem", start_info["altitude"], expected_start_altitude),
        ("Destino", end_info["altitude"], expected_end_altitude),
    ]:
        if actual is not None and expected is not None and abs(actual - expected) > tolerance_m:
            message = (
                f"{label} tem altitude {actual:.1f} m, fora da tolerancia de {tolerance_m:.1f} m em relacao a {expected:.1f} m."
            )
            if strict_altitude:
                raise ValueError(message)
            messages.append(message)
    result.update(
        {
            "start_row_col": (start_info["row"], start_info["col"]),
            "end_row_col": (end_info["row"], end_info["col"]),
            "start_inside": start_info["inside"],
            "end_inside": end_info["inside"],
            "start_altitude": start_info["altitude"],
            "end_altitude": end_info["altitude"],
            "start_altitude_delta_m": (
                start_info["altitude"] - expected_start_altitude
                if start_info["altitude"] is not None and expected_start_altitude is not None
                else None
            ),
            "end_altitude_delta_m": (
                end_info["altitude"] - expected_end_altitude
                if end_info["altitude"] is not None and expected_end_altitude is not None
                else None
            ),
            "start_navigable": start_info["navigable"],
            "end_navigable": end_info["navigable"],
            "start_risk": start_info["risk"],
            "end_risk": end_info["risk"],
            "start_slope": start_info["slope"],
            "end_slope": end_info["slope"],
            "valid": not messages,
        }
    )
    return result


def path_metrics(path_cells, cost_array, dem, slope, risk_class, transform, proj, corridor_gdf=None):
    altitudes = [float(dem[row, col]) for row, col in path_cells if np.isfinite(dem[row, col])]
    slopes = [float(slope[row, col]) for row, col in path_cells if np.isfinite(slope[row, col])]
    risks = [int(risk_class[row, col]) for row, col in path_cells]
    coordinates = [pixel_to_world(transform, row, col) for row, col in path_cells]
    line = LineString(coordinates)
    srs = osr.SpatialReference()
    srs.ImportFromWkt(proj) if proj else srs.ImportFromEPSG(4326)
    crs_wkt = srs.ExportToWkt()
    route_gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[line], crs=crs_wkt)
    metric_crs = metric_crs_for_raster(transform, dem.shape, proj)
    metric_route = route_gdf.to_crs(metric_crs)
    distance_m = float(metric_route.geometry.length.iloc[0])
    gains = []
    losses = []
    for previous, current in zip(altitudes, altitudes[1:]):
        delta = current - previous
        if delta > 0:
            gains.append(delta)
        elif delta < 0:
            losses.append(abs(delta))
    total = max(1, len(risks))
    risk_counts = {klass: risks.count(klass) for klass in range(5)}
    metrics = {
        "distance_m": distance_m,
        "start_altitude_m": altitudes[0] if altitudes else None,
        "end_altitude_m": altitudes[-1] if altitudes else None,
        "gross_gain_m": float(sum(gains)),
        "gross_loss_m": float(sum(losses)),
        "mean_slope_deg": float(np.mean(slopes)) if slopes else None,
        "max_slope_deg": float(np.max(slopes)) if slopes else None,
        "accumulated_cost": float(sum(cost_array[row, col] for row, col in path_cells if np.isfinite(cost_array[row, col]))),
        "risk_low_pct": risk_counts[0] / total * 100.0,
        "risk_moderate_pct": risk_counts[1] / total * 100.0,
        "risk_high_pct": risk_counts[2] / total * 100.0,
        "risk_very_high_pct": risk_counts[3] / total * 100.0,
        "risk_blocked_pct": risk_counts[4] / total * 100.0,
        "risk_high_very_high_pct": (risk_counts[2] + risk_counts[3]) / total * 100.0,
        "cells": int(len(path_cells)),
        "blocked_cells_on_route": int(
            sum(1 for row, col in path_cells if not np.isfinite(cost_array[row, col]))
        ),
        "corridor_length_m": None,
        "corridor_area_m2": None,
    }
    if corridor_gdf is not None and len(corridor_gdf):
        metric_corridor = corridor_gdf.to_crs(metric_crs)
        metrics["corridor_length_m"] = distance_m
        metrics["corridor_area_m2"] = float(metric_corridor.geometry.area.iloc[0])
    return metrics, route_gdf


def _save_cost_raster(cost_array, transform, proj, path):
    output = np.where(np.isfinite(cost_array), cost_array, -9999.0).astype(np.float32)
    rows, cols = output.shape
    driver = gdal.GetDriverByName("GTiff")
    if os.path.exists(path):
        driver.Delete(path)
    dataset = driver.Create(path, cols, rows, 1, gdal.GDT_Float32, options=["COMPRESS=LZW"])
    if dataset is None:
        raise Exception(f"Nao foi possivel criar raster de custo: {path}")
    dataset.SetGeoTransform(transform)
    if proj:
        dataset.SetProjection(proj)
    band = dataset.GetRasterBand(1)
    band.SetNoDataValue(-9999.0)
    band.WriteArray(output)
    band.FlushCache()
    dataset = None
    return path


def _normalise_metric(rows, key):
    values = [row.get(key) for row in rows if row.get("status") == "ok" and row.get(key) is not None]
    finite = [float(value) for value in values if np.isfinite(value)]
    if not finite:
        return {}
    low = min(finite)
    high = max(finite)
    if math.isclose(low, high):
        return {row["scenario"]: 0.0 for row in rows if row.get("status") == "ok"}
    return {
        row["scenario"]: (float(row[key]) - low) / (high - low)
        for row in rows
        if row.get("status") == "ok" and row.get(key) is not None
    }


def rank_route_scenarios(rows):
    successful = [row for row in rows if row.get("status") == "ok"]
    if not successful:
        return {}
    cost_norm = _normalise_metric(successful, "accumulated_cost")
    distance_norm = _normalise_metric(successful, "distance_m")
    risk_norm = _normalise_metric(successful, "risk_high_very_high_pct")
    mean_slope_norm = _normalise_metric(successful, "mean_slope_deg")
    max_slope_norm = _normalise_metric(successful, "max_slope_deg")

    def general_score(row):
        scenario = row["scenario"]
        cost_part = 0.30 * cost_norm.get(scenario, 0.0)
        risk_part = 0.20 * risk_norm.get(scenario, 0.0)
        mean_slope_part = 0.20 * mean_slope_norm.get(scenario, 0.0)
        max_slope_part = 0.15 * max_slope_norm.get(scenario, 0.0)
        distance_part = 0.15 * distance_norm.get(scenario, 0.0)
        score = cost_part + risk_part + mean_slope_part + max_slope_part + distance_part
        if row.get("risk_blocked_pct", 0) > 0:
            score += 0.10
        return score

    ranking = {
        "melhor_rota_geral": min(successful, key=general_score)["scenario"],
        "melhor_rota_curta": min(successful, key=lambda row: row["distance_m"])["scenario"],
        "melhor_rota_suave": min(successful, key=lambda row: (row["mean_slope_deg"], row["max_slope_deg"]))["scenario"],
        "melhor_rota_segura": min(
            successful,
            key=lambda row: (
                row.get("risk_high_very_high_pct", 0),
                row.get("risk_blocked_pct", 0),
                row.get("max_slope_deg", 0),
                row.get("accumulated_cost", 0),
            ),
        )["scenario"],
        "metodo_ranking_geral": (
            "score = 0.30*custo_norm + 0.20*risco_alto_norm + "
            "0.20*declividade_media_norm + 0.15*declividade_maxima_norm + 0.15*distancia_norm; menor score vence."
        ),
    }
    return ranking


def _mean_line_distance(line_a, line_b, samples=40):
    if line_a.is_empty or line_b.is_empty:
        return None
    distances = []
    for index in range(samples):
        fraction = index / max(1, samples - 1)
        point = line_a.interpolate(fraction, normalized=True)
        distances.append(point.distance(nearest_points(point, line_b)[1]))
    return float(np.mean(distances)) if distances else None


def compare_route_geometries(rows, output_dir=None, buffer_m=15.0):
    """Compare viable route geometries and optionally write CSV/JSON outputs."""
    routes = []
    for row in rows:
        path = row.get("route")
        if row.get("status") != "ok" or not path or not os.path.exists(path):
            continue
        gdf = gpd.read_file(path)
        if len(gdf) == 0:
            continue
        geom = gdf.geometry.iloc[0]
        routes.append({"scenario": row["scenario"], "row": row, "geometry": geom, "crs": gdf.crs})

    comparisons = []
    for index, first in enumerate(routes):
        for second in routes[index + 1:]:
            line_a = first["geometry"]
            line_b = second["geometry"]
            length_a = float(line_a.length)
            length_b = float(line_b.length)
            if line_a.is_empty or line_b.is_empty:
                category = "sem_geometria"
                hausdorff = None
                mean_distance = None
                overlap_pct = 0.0
            else:
                hausdorff = float(line_a.hausdorff_distance(line_b))
                mean_distance = _mean_line_distance(line_a, line_b)
                buffer_a = line_a.buffer(buffer_m)
                buffer_b = line_b.buffer(buffer_m)
                min_area = max(1e-9, min(buffer_a.area, buffer_b.area))
                overlap_pct = float(buffer_a.intersection(buffer_b).area / min_area * 100.0)
                if hausdorff < 30.0 and overlap_pct > 90.0:
                    category = "praticamente_iguais"
                elif hausdorff <= 150.0:
                    category = "levemente_diferentes"
                elif hausdorff > 150.0 or overlap_pct < 60.0:
                    category = "geometricamente_diferentes"
                else:
                    category = "parcialmente_diferentes"
            row = {
                "scenario_a": first["scenario"],
                "scenario_b": second["scenario"],
                "hausdorff_m": hausdorff,
                "mean_distance_m": mean_distance,
                "overlap_pct": overlap_pct,
                "length_diff_m": abs(length_a - length_b),
                "cost_diff": abs(first["row"].get("accumulated_cost", 0) - second["row"].get("accumulated_cost", 0)),
                "mean_slope_diff_deg": abs(first["row"].get("mean_slope_deg", 0) - second["row"].get("mean_slope_deg", 0)),
                "risk_high_diff_pct": abs(first["row"].get("risk_high_very_high_pct", 0) - second["row"].get("risk_high_very_high_pct", 0)),
                "corridor_area_diff_m2": abs((first["row"].get("corridor_area_m2") or 0) - (second["row"].get("corridor_area_m2") or 0)),
                "same_corridor": bool(overlap_pct > 90.0),
                "category": category,
            }
            comparisons.append(row)

    outputs = {}
    if output_dir is not None:
        os.makedirs(output_dir, exist_ok=True)
        csv_path = os.path.join(output_dir, "route_geometry_comparison.csv")
        json_path = os.path.join(output_dir, "route_geometry_comparison.json")
        fieldnames = sorted({key for row in comparisons for key in row.keys()}) if comparisons else [
            "scenario_a",
            "scenario_b",
            "category",
        ]
        with open(csv_path, "w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()
            for row in comparisons:
                writer.writerow(row)
        with open(json_path, "w", encoding="utf-8") as json_file:
            json.dump({"comparisons": comparisons}, json_file, indent=2, ensure_ascii=False)
        outputs = {"geometry_csv": csv_path, "geometry_json": json_path}
    return {"comparisons": comparisons, "outputs": outputs}


def write_route_scenario_outputs(rows, ranking, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, "route_scenario_comparison.csv")
    json_path = os.path.join(output_dir, "route_scenario_comparison.json")
    md_path = os.path.join(output_dir, "route_scenario_report.md")
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with open(csv_path, "w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    with open(json_path, "w", encoding="utf-8") as json_file:
        json.dump({"generated_at": datetime.now().isoformat(timespec="seconds"), "rows": rows, "ranking": ranking}, json_file, indent=2, ensure_ascii=False)
    lines = [
        "# Comparacao de Cenarios de Rota TopoTrail",
        "",
        "## Ranking",
        "",
    ]
    if ranking:
        for key, value in ranking.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- Nenhuma rota viavel foi encontrada.")
    lines.extend(["", "## Tabela Comparativa", ""])
    for row in rows:
        lines.extend(
            [
                f"### {row.get('scenario')}",
                "",
                f"- Status: {row.get('status')}",
                f"- Distancia (m): {row.get('distance_m')}",
                f"- Custo acumulado: {row.get('accumulated_cost')}",
                f"- Declividade media (graus): {row.get('mean_slope_deg')}",
                f"- Risco alto + muito alto (%): {row.get('risk_high_very_high_pct')}",
                f"- Celulas bloqueadas na rota: {row.get('blocked_cells_on_route')}",
                f"- Observacao: {row.get('error') or row.get('explanation') or ''}",
                "",
            ]
        )
    with open(md_path, "w", encoding="utf-8") as md_file:
        md_file.write("\n".join(lines) + "\n")
    return {"csv": csv_path, "json": json_path, "markdown": md_path}


def generate_route_scenarios(
    dem,
    adequability,
    slope,
    curvature_horizontal,
    curvature_vertical,
    risk,
    start_point,
    end_point,
    scenarios,
    transform,
    proj,
    output_dir,
    log_path=None,
    expected_start_altitude=None,
    expected_end_altitude=None,
):
    """Generate routes, corridors, cost rasters and comparison metrics."""
    os.makedirs(output_dir, exist_ok=True)
    validation = validate_start_end_points(
        dem,
        transform,
        start_point,
        end_point,
        expected_start_altitude=expected_start_altitude,
        expected_end_altitude=expected_end_altitude,
        slope=slope,
        risk=risk,
        navigable_mask=np.isfinite(adequability),
    )
    append_diagnostic_log(log_path, "validacao_origem_destino_cenarios", validacao=validation)
    start_rc = validation["start_row_col"]
    end_rc = validation["end_row_col"]
    risk_class = classify_topographic_risk(slope, curvature_horizontal, curvature_vertical)
    rows = []

    for scenario_name, parameters in scenarios.items():
        row = {"scenario": scenario_name, "status": "erro"}
        try:
            cost, blocked, metadata, explanation = build_cost_surface_for_scenario(
                adequability,
                slope,
                curvature_horizontal,
                curvature_vertical,
                risk,
                scenario_name,
                parameters,
            )
            cost_path = _save_cost_raster(cost, transform, proj, os.path.join(output_dir, f"custo_{scenario_name}.tif"))
            path_cells, accumulated_cost = least_cost_path(cost, start_rc, end_rc)
            metrics, route_gdf = path_metrics(path_cells, cost, dem, slope, risk_class, transform, proj)
            metrics["accumulated_cost"] = accumulated_cost
            metrics["blocked_cells_on_route"] = int(sum(1 for row_index, col_index in path_cells if blocked[row_index, col_index]))
            route_gdf["scenario"] = scenario_name
            route_gdf["custo"] = accumulated_cost
            route_gdf["vertices"] = len(path_cells)
            route_gdf["compr_m"] = metrics["distance_m"]
            route_path = os.path.join(output_dir, f"rota_{scenario_name}.gpkg")
            corridor_path = os.path.join(output_dir, f"corredor_{scenario_name}.gpkg")
            route_gdf.to_file(route_path, driver="GPKG")

            metric_crs = metric_crs_for_raster(transform, dem.shape, proj)
            corridor_metric = route_gdf.to_crs(metric_crs)
            buffer_m = float(parameters.get("buffer_m", DEFAULT_SCENARIOS.get(scenario_name, {}).get("buffer_m", 80.0)))
            corridor_gdf = gpd.GeoDataFrame(
                {"scenario": [scenario_name], "buffer_m": [buffer_m]},
                geometry=corridor_metric.geometry.buffer(buffer_m),
                crs=corridor_metric.crs,
            )
            corridor_out = corridor_gdf.to_crs(route_gdf.crs)
            corridor_out.to_file(corridor_path, driver="GPKG")
            metrics, _ = path_metrics(path_cells, cost, dem, slope, risk_class, transform, proj, corridor_gdf=corridor_gdf)
            metrics["accumulated_cost"] = accumulated_cost
            row.update(metrics)
            row.update(
                {
                    "status": "ok",
                    "cost_raster": cost_path,
                    "route": route_path,
                    "corridor": corridor_path,
                    "blocked_cells": metadata["blocked_cells"],
                    "navigable_cells": metadata["navigable_cells"],
                    "explanation": explanation,
                }
            )
            append_diagnostic_log(log_path, "cenario_rota_calculado", scenario=scenario_name, metricas=row, metadata=metadata)
        except Exception as exc:
            row["error"] = str(exc)
            append_diagnostic_log(log_path, "cenario_rota_falhou", scenario=scenario_name, erro=str(exc))
        rows.append(row)

    ranking = rank_route_scenarios(rows)
    outputs = write_route_scenario_outputs(rows, ranking, output_dir)
    geometry = compare_route_geometries(rows, output_dir=output_dir)
    outputs.update(geometry.get("outputs", {}))
    append_diagnostic_log(log_path, "cenarios_rota_concluidos", ranking=ranking, outputs=outputs, geometria=geometry)
    return {"validation": validation, "rows": rows, "ranking": ranking, "outputs": outputs, "geometry_comparison": geometry}


def create_synthetic_route_dataset(rows=160, cols=100):
    """Create a synthetic mountain route dataset in EPSG:32723."""
    transform = (500000.0, 30.0, 0.0, 7500000.0, 0.0, -30.0)
    x = np.linspace(0, 1, cols, dtype=np.float32)
    y = np.linspace(0, 1, rows, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)
    dem = 380.0 + 2100.0 * yy + 120.0 * np.sin(xx * np.pi * 3) + 80.0 * np.cos(yy * np.pi * 2)
    ridge = np.exp(-((xx - 0.55) ** 2) / 0.012) * 240.0
    dem = (dem + ridge).astype(np.float32)
    pixel_size_x = abs(transform[1])
    pixel_size_y = abs(transform[5])
    dy, dx = np.gradient(dem, pixel_size_y, pixel_size_x)
    slope = np.degrees(np.arctan(np.sqrt(dx ** 2 + dy ** 2))).astype(np.float32)
    _, curvh = np.gradient(dx, pixel_size_y, pixel_size_x)
    curvv, _ = np.gradient(dy, pixel_size_y, pixel_size_x)
    curvature_horizontal = curvh.astype(np.float32)
    curvature_vertical = curvv.astype(np.float32)
    slope_norm = np.clip(slope / 45.0, 0, 1)
    curvature_mag = np.sqrt(curvature_horizontal ** 2 + curvature_vertical ** 2)
    curv_norm = _finite_norm(curvature_mag)
    risk = np.clip(0.75 * slope_norm + 0.25 * curv_norm, 0, 1).astype(np.float32)
    adequability = np.clip(1.0 - (0.65 * slope_norm + 0.25 * risk + 0.10 * curv_norm), 0.05, 1.0).astype(np.float32)
    start_point = pixel_to_world(transform, 2, 5)
    end_point = pixel_to_world(transform, rows - 3, cols - 6)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32723)
    return {
        "dem": dem,
        "adequability": adequability,
        "slope": slope,
        "curvature_horizontal": curvature_horizontal,
        "curvature_vertical": curvature_vertical,
        "risk": risk,
        "start_point": start_point,
        "end_point": end_point,
        "transform": transform,
        "proj": srs.ExportToWkt(),
        "crs": "EPSG:32723",
    }


def create_contrasting_route_dataset(rows=200, cols=140):
    """Create a projected synthetic terrain with short/risky and long/safer alternatives."""
    transform = (500000.0, 30.0, 0.0, 7500000.0, 0.0, -30.0)
    yy, xx = np.indices((rows, cols), dtype=np.float32)
    y_norm = yy / max(1, rows - 1)
    x_norm = xx / max(1, cols - 1)

    dem = 400.0 + 2070.0 * y_norm + 130.0 * (y_norm ** 2) + 55.0 * np.sin(x_norm * np.pi * 4)
    dem += 95.0 * np.exp(-((x_norm - 0.55) ** 2) / 0.01)
    dem = dem.astype(np.float32)

    slope = np.full((rows, cols), 48.0, dtype=np.float32)
    curvature_horizontal = np.full((rows, cols), 0.020, dtype=np.float32)
    curvature_vertical = np.full((rows, cols), 0.018, dtype=np.float32)
    risk = np.full((rows, cols), 0.96, dtype=np.float32)
    adequability = np.full((rows, cols), np.nan, dtype=np.float32)

    start_rc = (1, 10)
    end_rc = (rows - 9, cols - 10)
    diagonal_col = start_rc[1] + (yy - start_rc[0]) * ((end_rc[1] - start_rc[1]) / (end_rc[0] - start_rc[0]))
    short_corridor = (yy >= start_rc[0]) & (yy <= end_rc[0]) & (np.abs(xx - diagonal_col) <= 2.5)

    safe_vertical_a = (xx >= 8) & (xx <= 20) & (yy >= start_rc[0]) & (yy <= 152)
    safe_horizontal = (yy >= 145) & (yy <= 160) & (xx >= 14) & (xx <= cols - 20)
    safe_vertical_b = (xx >= cols - 24) & (xx <= cols - 8) & (yy >= 150) & (yy <= end_rc[0])
    safe_corridor = safe_vertical_a | safe_horizontal | safe_vertical_b

    transition_left = (xx >= 18) & (xx <= 42) & (yy >= 70) & (yy <= 118)
    transition_right = (xx >= 96) & (xx <= 124) & (yy >= 80) & (yy <= 132)
    transition_corridor = transition_left | transition_right

    adequability[short_corridor] = 0.62
    slope[short_corridor] = 32.0
    risk[short_corridor] = 0.68
    curvature_horizontal[short_corridor] = 0.010
    curvature_vertical[short_corridor] = 0.012

    adequability[safe_corridor] = 0.88
    slope[safe_corridor] = 13.0
    risk[safe_corridor] = 0.18
    curvature_horizontal[safe_corridor] = 0.003
    curvature_vertical[safe_corridor] = 0.004

    adequability[transition_corridor & np.isnan(adequability)] = 0.70
    slope[transition_corridor] = np.minimum(slope[transition_corridor], 22.0)
    risk[transition_corridor] = np.minimum(risk[transition_corridor], 0.42)
    curvature_horizontal[transition_corridor] = np.minimum(curvature_horizontal[transition_corridor], 0.008)
    curvature_vertical[transition_corridor] = np.minimum(curvature_vertical[transition_corridor], 0.008)

    barrier = (xx >= 66) & (xx <= 74)
    short_pass = short_corridor & (yy >= 84) & (yy <= 108)
    safe_pass = safe_corridor & (yy >= 145) & (yy <= 160)
    blocked_barrier = barrier & ~(short_pass | safe_pass)
    adequability[blocked_barrier] = np.nan
    slope[blocked_barrier] = 62.0
    risk[blocked_barrier] = 1.0
    curvature_horizontal[blocked_barrier] = 0.080
    curvature_vertical[blocked_barrier] = 0.080

    # Make the short pass risky but traversable for permissive scenarios.
    adequability[short_pass] = 0.58
    slope[short_pass] = 34.0
    risk[short_pass] = 0.70
    curvature_horizontal[short_pass] = 0.014
    curvature_vertical[short_pass] = 0.014

    dem[~np.isfinite(adequability)] = dem[~np.isfinite(adequability)]
    start_point = (
        transform[0] + (start_rc[1] + 0.1) * transform[1],
        transform[3] + (start_rc[0] + 0.1) * transform[5],
    )
    end_point = (
        transform[0] + (end_rc[1] + 0.1) * transform[1],
        transform[3] + (end_rc[0] + 0.1) * transform[5],
    )
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32723)
    return {
        "dem": dem.astype(np.float32),
        "adequability": adequability.astype(np.float32),
        "slope": slope.astype(np.float32),
        "curvature_horizontal": curvature_horizontal.astype(np.float32),
        "curvature_vertical": curvature_vertical.astype(np.float32),
        "risk": risk.astype(np.float32),
        "start_point": start_point,
        "end_point": end_point,
        "transform": transform,
        "proj": srs.ExportToWkt(),
        "crs": "EPSG:32723",
        "expected_start_altitude": 400.0,
        "expected_end_altitude": 2470.0,
    }


def validate_route_scenario_outputs(result, transform=None, proj=None):
    """Validate generated cost rasters, GeoPackages and tabular reports."""
    validations = {"rasters": {}, "routes": {}, "corridors": {}, "tables": {}, "ok": True}
    for row in result.get("rows", []):
        scenario = row.get("scenario")
        cost_path = row.get("cost_raster")
        if cost_path:
            item = {"exists": os.path.exists(cost_path), "opens": False, "has_crs": False, "finite_values": 0, "blocked_values": 0}
            if item["exists"]:
                ds = gdal.Open(cost_path)
                if ds is not None:
                    arr = ds.GetRasterBand(1).ReadAsArray()
                    nodata = ds.GetRasterBand(1).GetNoDataValue()
                    item.update(
                        {
                            "opens": True,
                            "has_crs": bool(ds.GetProjection()),
                            "cols": ds.RasterXSize,
                            "rows": ds.RasterYSize,
                            "finite_values": int(np.sum(np.isfinite(arr) & (arr != nodata))),
                            "blocked_values": int(np.sum(arr == nodata)),
                        }
                    )
                    ds = None
            validations["rasters"][scenario] = item
            validations["ok"] = validations["ok"] and item["exists"] and item["opens"] and item["has_crs"]
        for key, group, expected_type in [
            ("route", "routes", "LineString"),
            ("corridor", "corridors", "Polygon"),
        ]:
            path = row.get(key)
            if not path:
                continue
            item = {"exists": os.path.exists(path), "opens": False, "has_crs": False, "valid_geometry": False}
            if item["exists"]:
                gdf = gpd.read_file(path)
                if len(gdf):
                    geom = gdf.geometry.iloc[0]
                    item.update(
                        {
                            "opens": True,
                            "has_crs": gdf.crs is not None,
                            "geometry_type": geom.geom_type,
                            "valid_geometry": bool(geom.is_valid and not geom.is_empty),
                            "length": float(geom.length),
                            "area": float(geom.area),
                            "expected_type": expected_type,
                        }
                    )
            validations[group][scenario] = item
            validations["ok"] = validations["ok"] and item["exists"] and item["opens"] and item["has_crs"] and item["valid_geometry"]
    for key, path in result.get("outputs", {}).items():
        if key in {"csv", "json", "markdown", "geometry_csv", "geometry_json"}:
            validations["tables"][key] = {"exists": os.path.exists(path), "size": os.path.getsize(path) if os.path.exists(path) else 0}
            validations["ok"] = validations["ok"] and validations["tables"][key]["exists"]
    return validations


def run_synthetic_route_scenarios(output_dir, log_path=None):
    dataset = create_synthetic_route_dataset()
    return generate_route_scenarios(
        dataset["dem"],
        dataset["adequability"],
        dataset["slope"],
        dataset["curvature_horizontal"],
        dataset["curvature_vertical"],
        dataset["risk"],
        dataset["start_point"],
        dataset["end_point"],
        DEFAULT_SCENARIOS,
        dataset["transform"],
        dataset["proj"],
        output_dir,
        log_path=log_path,
        expected_start_altitude=400.0,
        expected_end_altitude=2470.0,
    )


def run_contrasting_route_scenarios(output_dir, log_path=None):
    dataset = create_contrasting_route_dataset()
    return generate_route_scenarios(
        dataset["dem"],
        dataset["adequability"],
        dataset["slope"],
        dataset["curvature_horizontal"],
        dataset["curvature_vertical"],
        dataset["risk"],
        dataset["start_point"],
        dataset["end_point"],
        DEFAULT_SCENARIOS,
        dataset["transform"],
        dataset["proj"],
        output_dir,
        log_path=log_path,
        expected_start_altitude=dataset["expected_start_altitude"],
        expected_end_altitude=dataset["expected_end_altitude"],
    )
