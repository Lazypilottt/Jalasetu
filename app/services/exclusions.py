"""
No-build exclusion zones for pond siting.

Turns infrastructure features (from ``app.services.infrastructure``) and
user-marked zones into buffered polygons, then masks them out of the terrain
suitability raster so the ranking can never place a pond on a river, tank,
building, school or road. Cells outside the surveyed circle are masked too,
because infrastructure there was not checked.

Zones travel between services as WGS84 GeoJSON, so the gateway can build
them once and any stage worker can apply them to its DEM grid.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import rasterio.features
from pyproj import Transformer
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform as shapely_transform, unary_union

from app.services.infrastructure import CATEGORIES
from app.utils.geometry import get_utm_epsg_from_lon_lat

logger = logging.getLogger(__name__)

MANUAL_CATEGORY = "manual"


def parse_categories(value: Any) -> List[str]:
    """Accept a list or a comma-separated string; unknown names are ignored."""
    if value is None:
        return list(CATEGORIES)
    items = value if isinstance(value, (list, tuple)) else str(value).split(",")
    return [item.strip() for item in items if item and item.strip() in CATEGORIES]


def parse_manual_zones(value: Any) -> List[Dict[str, float]]:
    """Manual zones as ``[{"lat", "lon", "radius_m", "label"?}]`` (list or JSON string)."""
    import json

    if not value:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    zones = []
    for item in value if isinstance(value, list) else []:
        try:
            lat, lon = float(item["lat"]), float(item["lon"])
            radius = max(1.0, min(float(item.get("radius_m", 25.0)), 1000.0))
        except (KeyError, TypeError, ValueError):
            continue
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            zones.append({"lat": lat, "lon": lon, "radius_m": radius, "label": str(item.get("label") or "Marked zone")[:60]})
    return zones[:50]


def build_exclusion_zones(
    features: Iterable[Dict[str, Any]],
    center_lat: float,
    center_lon: float,
    survey_radius_m: float,
    categories: Optional[List[str]] = None,
    buffer_scale: float = 1.0,
    manual_zones: Optional[List[Dict[str, float]]] = None,
) -> Dict[str, Any]:
    """Buffer features by category and return dissolved WGS84 zones plus stats."""
    categories = parse_categories(categories) if categories is not None else list(CATEGORIES)
    buffer_scale = max(0.0, min(float(buffer_scale), 5.0))
    epsg = get_utm_epsg_from_lon_lat(center_lon, center_lat)
    to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform
    to_wgs = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True).transform

    survey = Point(*to_utm(center_lon, center_lat)).buffer(survey_radius_m, 64)
    by_category: Dict[str, List[Any]] = {}
    counts: Dict[str, int] = {}
    for feature in features:
        category = (feature.get("properties") or {}).get("category")
        if category not in categories:
            continue
        try:
            geom = shapely_transform(to_utm, shape(feature["geometry"]))
        except Exception:  # malformed geometry from a third-party source
            continue
        # Points and lines need at least a small footprint to be masked.
        buffer_m = max(CATEGORIES[category]["buffer_m"] * buffer_scale, 0.0 if geom.area > 0 else 3.0)
        zone = geom.buffer(buffer_m, 16) if buffer_m > 0 else geom
        if zone.is_empty or not zone.intersects(survey.buffer(200)):
            continue
        by_category.setdefault(category, []).append(zone)
        counts[category] = counts.get(category, 0) + 1

    for zone in manual_zones or []:
        circle = Point(*to_utm(zone["lon"], zone["lat"])).buffer(zone["radius_m"], 32)
        by_category.setdefault(MANUAL_CATEGORY, []).append(circle)
        counts[MANUAL_CATEGORY] = counts.get(MANUAL_CATEGORY, 0) + 1

    zone_features = []
    total_area = 0.0
    dissolved_all = []
    for category, geoms in by_category.items():
        dissolved = unary_union(geoms)
        dissolved_all.append(dissolved)
        clipped_area = dissolved.intersection(survey).area
        total_area += clipped_area
        wgs = shapely_transform(to_wgs, dissolved.simplify(0.5, preserve_topology=True))
        label = CATEGORIES.get(category, {}).get("label", "Marked no-build zones")
        zone_features.append(
            {
                "type": "Feature",
                "geometry": mapping(wgs),
                "properties": {
                    "category": category,
                    "label": label,
                    "count": counts[category],
                    "area_m2": round(clipped_area, 1),
                    "buffer_m": None if category == MANUAL_CATEGORY else round(CATEGORIES[category]["buffer_m"] * buffer_scale, 1),
                },
            }
        )
    union_area = unary_union(dissolved_all).intersection(survey).area if dissolved_all else 0.0
    return {
        "zones": {"type": "FeatureCollection", "features": zone_features},
        "survey": {"lat": center_lat, "lon": center_lon, "radius_m": survey_radius_m},
        "counts": counts,
        "excluded_area_m2": round(union_area, 1),
        "survey_area_m2": round(math.pi * survey_radius_m ** 2, 1),
    }


def apply_exclusions(analysis_result: Any, zones: Optional[Dict[str, Any]], survey: Optional[Dict[str, float]]) -> Dict[str, Any]:
    """Zero suitability inside zones and outside the survey circle.

    Mutates ``analysis_result.suitability_score`` and ``suitable_mask`` in
    place and returns how many cells each rule removed.
    """
    dem = analysis_result.dem_data
    shape_rc = analysis_result.suitability_score.shape
    to_dem = Transformer.from_crs("EPSG:4326", dem.crs, always_xy=True).transform
    blocked = np.zeros(shape_rc, dtype=bool)
    zone_cells = 0

    geoms = []
    for feature in (zones or {}).get("features", []):
        try:
            geom = shapely_transform(to_dem, shape(feature["geometry"]))
        except Exception:
            continue
        if not geom.is_empty:
            geoms.append(geom)
    if geoms:
        zone_mask = rasterio.features.rasterize(
            ((g, 1) for g in geoms), out_shape=shape_rc, transform=dem.transform, fill=0, all_touched=True, dtype="uint8"
        ).astype(bool)
        zone_cells = int(zone_mask.sum())
        blocked |= zone_mask

    outside_cells = 0
    if survey:
        cx, cy = to_dem(float(survey["lon"]), float(survey["lat"]))
        rows, cols = np.indices(shape_rc)
        xs = dem.transform.c + (cols + 0.5) * dem.transform.a
        ys = dem.transform.f + (rows + 0.5) * dem.transform.e
        outside = (xs - cx) ** 2 + (ys - cy) ** 2 > float(survey["radius_m"]) ** 2
        outside_cells = int((outside & ~blocked).sum())
        blocked |= outside

    if blocked.any():
        analysis_result.suitability_score = np.where(blocked, 0.0, analysis_result.suitability_score)
        if getattr(analysis_result, "suitable_mask", None) is not None:
            analysis_result.suitable_mask = analysis_result.suitable_mask & ~blocked
    cell_area = abs(dem.transform.a * dem.transform.e)
    return {
        "zone_cells": zone_cells,
        "zone_area_m2": round(zone_cells * cell_area, 1),
        "outside_survey_cells": outside_cells,
    }


def exclusion_note(stats: Dict[str, Any], counts: Dict[str, int]) -> str:
    parts = [f"{n} {CATEGORIES.get(c, {}).get('label', 'marked zones').lower()}" for c, n in sorted(counts.items())]
    listed = ", ".join(parts) if parts else "no mapped features"
    return (
        f"Excluded existing infrastructure from siting ({listed}); "
        f"{stats['zone_area_m2']:.0f} m² of terrain masked as no-build."
    )


def survey_radius_for(selected_radius_m: float) -> float:
    """Infrastructure is checked a little beyond the selected circle, because
    the ranking may fall back to the nearest site just outside it."""
    radius = float(selected_radius_m)
    return radius + max(150.0, 0.5 * radius)


def plan_exclusions(
    infra: Optional[Dict[str, Any]],
    center_lat: float,
    center_lon: float,
    survey_radius_m: float,
    categories: Any = None,
    buffer_scale: float = 1.0,
    manual_zones: Optional[List[Dict[str, float]]] = None,
) -> Dict[str, Any]:
    """Zones to mask plus the survey circle (only when the lookup succeeded)."""
    status = (infra or {}).get("status", "disabled")
    features = (infra or {}).get("features", {}).get("features", []) if status == "ok" else []
    plan = build_exclusion_zones(
        features, center_lat, center_lon, survey_radius_m,
        categories=parse_categories(categories), buffer_scale=buffer_scale, manual_zones=manual_zones,
    )
    plan["apply_survey"] = status == "ok"
    return plan


def summarize(
    infra: Optional[Dict[str, Any]],
    plan: Dict[str, Any],
    stats: Optional[Dict[str, Any]],
    categories: Any,
    buffer_scale: float,
) -> Dict[str, Any]:
    """Fields for ``InfrastructureSummary`` and the processing note to add."""
    infra = infra or {"status": "disabled"}
    status = infra.get("status", "disabled")
    if status == "ok":
        note = exclusion_note(stats or {"zone_area_m2": 0.0}, plan["counts"])
        if not infra.get("features", {}).get("features"):
            note += " " + infra.get("message", "")
        note += f" Candidates were limited to the {plan['survey']['radius_m']:.0f} m surveyed radius."
    elif status == "unavailable":
        note = (
            "Existing infrastructure could not be checked (OpenStreetMap lookup failed); "
            "verify the site for rivers, tanks, buildings and roads before excavation."
        )
        if plan["counts"].get(MANUAL_CATEGORY):
            note += f" {plan['counts'][MANUAL_CATEGORY]} user-marked no-build zone(s) were still applied."
    else:
        note = (
            f"Applied {plan['counts'].get(MANUAL_CATEGORY, 0)} user-marked no-build zone(s)."
            if plan["counts"].get(MANUAL_CATEGORY) else ""
        )
    return {
        "summary": {
            "status": status,
            "source": infra.get("source"),
            "message": infra.get("message"),
            "survey_radius_m": plan["survey"]["radius_m"],
            "categories": parse_categories(categories),
            "buffer_scale": float(buffer_scale),
            "counts": plan["counts"],
            "excluded_area_m2": plan["excluded_area_m2"],
            "zones_geojson": plan["zones"],
            "features_geojson": infra.get("features") if status == "ok" else None,
        },
        "note": note,
    }
