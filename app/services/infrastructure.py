"""
Existing-infrastructure lookup from OpenStreetMap (Overpass API).

A farm pond must not be excavated over a river, an existing tank, a school,
houses or a road. This module fetches those features around a selected point
and classifies them into exclusion categories, each with a default safety
buffer. It uses only the standard library so the sys1 edge node can serve it
without the geospatial stack; buffering and rasterising happen in
``app.services.exclusions``.

Overpass is a shared public service and often queues requests for 30 s or
more. A lookup therefore has one overall time budget across all endpoints,
concurrent lookups of the same area share one request (the map preview warms
the cache for the analysis that follows), and after a total failure further
lookups fail fast for a short cool-down. Failures are reported as
``status="unavailable"`` rather than raised: the analysis then proceeds and
says that infrastructure could not be checked.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Category -> label and default safety buffer in metres around the feature.
CATEGORIES: Dict[str, Dict[str, Any]] = {
    "water": {"label": "Lakes, tanks & ponds", "buffer_m": 15.0},
    "waterway": {"label": "Rivers, streams & canals", "buffer_m": 20.0},
    "building": {"label": "Buildings", "buffer_m": 10.0},
    "facility": {"label": "Schools, hospitals & places of worship", "buffer_m": 30.0},
    "road": {"label": "Roads", "buffer_m": 8.0},
    "railway": {"label": "Railways", "buffer_m": 15.0},
    "settlement": {"label": "Residential areas", "buffer_m": 0.0},
    "well": {"label": "Wells & water points", "buffer_m": 15.0},
}
DEFAULT_CATEGORIES = tuple(CATEGORIES)
# Closed ways in these categories are areas; in the others they are lines.
AREA_CATEGORIES = {"water", "building", "facility", "settlement"}

FACILITY_AMENITIES = {"school", "college", "university", "kindergarten", "hospital", "clinic", "doctors", "place_of_worship", "community_centre"}
FACILITY_BUILDINGS = {"school", "hospital", "temple", "mosque", "church", "college"}
WATERWAYS = {"river", "stream", "canal", "drain", "ditch", "brook"}
ROADS = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "service", "living_street", "track"}

DEFAULT_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
REQUEST_TIMEOUT_S = 40  # server-side Overpass query timeout
LOOKUP_BUDGET_S = float(os.getenv("JALASETU_INFRA_BUDGET_S", "45"))
MIN_ATTEMPT_S = 5.0
COOLDOWN_S = 120.0
MAX_FEATURES = 4000
CACHE_TTL_S = 6 * 3600
CACHE_MAX = 64

_cache: Dict[Tuple[float, float, int], Tuple[float, Dict[str, Any]]] = {}
_cache_lock = threading.Lock()
_inflight: Dict[Tuple[float, float, int], threading.Event] = {}
_unavailable_until = 0.0


def classify(tags: Dict[str, str]) -> Optional[str]:
    """Map OSM tags to an exclusion category, or None if not relevant."""
    if not tags:
        return None
    amenity = tags.get("amenity", "")
    building = tags.get("building", "")
    if amenity in FACILITY_AMENITIES or building in FACILITY_BUILDINGS:
        return "facility"
    if tags.get("man_made") in ("water_well", "water_tower", "borehole") or amenity in ("drinking_water", "water_point"):
        return "well"
    if tags.get("natural") == "water" or tags.get("landuse") in ("reservoir", "basin") or "water" in tags and tags.get("natural") != "wetland":
        return "water"
    if tags.get("waterway") in WATERWAYS:
        return "waterway"
    if building:
        return "building"
    if tags.get("highway") in ROADS:
        return "road"
    if tags.get("railway") in ("rail", "light_rail", "narrow_gauge"):
        return "railway"
    if tags.get("landuse") == "residential":
        return "settlement"
    return None


def build_query(lat: float, lon: float, radius_m: float) -> str:
    around = f"(around:{int(round(radius_m))},{lat:.6f},{lon:.6f})"
    selectors = [
        'way["building"]', 'relation["building"]',
        'way["natural"="water"]', 'relation["natural"="water"]', 'way["landuse"~"^(reservoir|basin)$"]',
        'way["waterway"~"^(river|stream|canal|drain|ditch|brook)$"]',
        'node["amenity"~"^(school|college|university|kindergarten|hospital|clinic|doctors|place_of_worship|community_centre)$"]',
        'way["amenity"~"^(school|college|university|kindergarten|hospital|clinic|place_of_worship|community_centre)$"]',
        'node["man_made"~"^(water_well|water_tower|borehole)$"]', 'node["amenity"="drinking_water"]',
        f'way["highway"~"^({"|".join(sorted(ROADS))})$"]',
        'way["railway"~"^(rail|light_rail|narrow_gauge)$"]',
        'way["landuse"="residential"]',
    ]
    body = "".join(f"{sel}{around};" for sel in selectors)
    return f"[out:json][timeout:{REQUEST_TIMEOUT_S}];({body});out geom;"


def _ring(points: List[Dict[str, float]]) -> List[List[float]]:
    return [[round(p["lon"], 7), round(p["lat"], 7)] for p in points if "lon" in p and "lat" in p]


def element_to_feature(element: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    tags = element.get("tags") or {}
    category = classify(tags)
    if category is None:
        return None
    kind = element.get("type")
    geometry: Optional[Dict[str, Any]] = None
    if kind == "node" and "lat" in element:
        geometry = {"type": "Point", "coordinates": [element["lon"], element["lat"]]}
    elif kind == "way" and element.get("geometry"):
        coords = _ring(element["geometry"])
        closed = len(coords) >= 4 and coords[0] == coords[-1]
        if closed and category in AREA_CATEGORIES:
            geometry = {"type": "Polygon", "coordinates": [coords]}
        elif len(coords) >= 2:
            geometry = {"type": "LineString", "coordinates": coords}
    elif kind == "relation":
        rings = []
        for member in element.get("members") or []:
            if member.get("role") == "outer" and member.get("geometry"):
                coords = _ring(member["geometry"])
                if len(coords) >= 4 and coords[0] == coords[-1]:
                    rings.append([coords])
        if rings:
            geometry = {"type": "MultiPolygon", "coordinates": rings}
    if geometry is None:
        return None
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "category": category,
            "name": tags.get("name") or tags.get("name:en"),
            "osm": f"{kind}/{element.get('id')}",
        },
    }


def parse_overpass(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    features = []
    for element in payload.get("elements") or []:
        feature = element_to_feature(element)
        if feature is not None:
            features.append(feature)
            if len(features) >= MAX_FEATURES:
                break
    return features


def _endpoints() -> List[str]:
    configured = os.getenv("JALASETU_OVERPASS_URLS", "")
    urls = [u.strip() for u in configured.split(",") if u.strip()]
    return urls or list(DEFAULT_ENDPOINTS)


def _fetch(query: str, budget_s: float) -> Tuple[Dict[str, Any], str]:
    errors = []
    deadline = time.monotonic() + budget_s
    for endpoint in _endpoints():
        remaining = deadline - time.monotonic()
        if remaining < MIN_ATTEMPT_S:
            errors.append("time budget exhausted")
            break
        try:
            request = urllib.request.Request(
                endpoint,
                data=urllib.parse.urlencode({"data": query}).encode("utf-8"),
                headers={"User-Agent": "JalaSetu/1.0 (farm pond siting)"},
            )
            with urllib.request.urlopen(request, timeout=remaining) as response:
                payload = json.load(response)
            remark = payload.get("remark") or ""
            if "runtime error" in remark.lower() or "timed out" in remark.lower():
                raise RuntimeError(remark[:120])
            return payload, endpoint
        except (urllib.error.URLError, OSError, ValueError, RuntimeError) as exc:
            errors.append(f"{urllib.parse.urlsplit(endpoint).netloc}: {exc}")
            logger.warning("Overpass endpoint %s failed: %s", endpoint, exc)
    raise RuntimeError("; ".join(errors) or "no Overpass endpoint configured")


def _unavailable(radius_m: float, message: str) -> Dict[str, Any]:
    return {
        "status": "unavailable",
        "source": "OpenStreetMap (Overpass API)",
        "message": message,
        "radius_m": radius_m,
        "features": {"type": "FeatureCollection", "features": []},
        "counts": {},
        "categories": CATEGORIES,
    }


def fetch_infrastructure(lat: float, lon: float, radius_m: float, budget_s: Optional[float] = None) -> Dict[str, Any]:
    """Infrastructure features within ``radius_m`` of a point, as GeoJSON.

    Never raises for network problems; check ``status`` instead.
    """
    global _unavailable_until
    radius_m = max(50.0, min(float(radius_m), 3000.0))
    budget_s = LOOKUP_BUDGET_S if budget_s is None else float(budget_s)
    key = (round(lat, 4), round(lon, 4), int(round(radius_m, -1)))

    while True:
        with _cache_lock:
            hit = _cache.get(key)
            if hit and time.time() - hit[0] < CACHE_TTL_S:
                return {**hit[1], "cached": True}
            if time.time() < _unavailable_until:
                return _unavailable(radius_m, "Infrastructure data could not be retrieved: OpenStreetMap did not respond recently.")
            waiting = _inflight.get(key)
            if waiting is None:
                _inflight[key] = threading.Event()
                break
        # Another request is already fetching this area; reuse its result.
        if not waiting.wait(timeout=budget_s + 5):
            return _unavailable(radius_m, "Infrastructure data could not be retrieved: lookup timed out.")

    started = time.perf_counter()
    try:
        try:
            payload, endpoint = _fetch(build_query(lat, lon, radius_m), budget_s)
        except RuntimeError as exc:
            with _cache_lock:
                _unavailable_until = time.time() + COOLDOWN_S
            return _unavailable(radius_m, f"Infrastructure data could not be retrieved: {exc}")
        return _store(key, payload, endpoint, radius_m, started)
    finally:
        with _cache_lock:
            _inflight.pop(key).set()


def _store(key, payload: Dict[str, Any], endpoint: str, radius_m: float, started: float) -> Dict[str, Any]:
    features = parse_overpass(payload)
    counts: Dict[str, int] = {}
    for feature in features:
        category = feature["properties"]["category"]
        counts[category] = counts.get(category, 0) + 1
    result = {
        "status": "ok",
        "source": "OpenStreetMap (Overpass API)",
        "endpoint": urllib.parse.urlsplit(endpoint).netloc,
        "osm_timestamp": (payload.get("osm3s") or {}).get("timestamp_osm_base"),
        "fetch_ms": round((time.perf_counter() - started) * 1000, 1),
        "radius_m": radius_m,
        "features": {"type": "FeatureCollection", "features": features},
        "counts": counts,
        "categories": CATEGORIES,
        "message": (
            f"Found {len(features)} mapped infrastructure feature(s) within {radius_m:.0f} m."
            if features
            else f"No mapped infrastructure within {radius_m:.0f} m; OpenStreetMap coverage may be incomplete here."
        ),
    }
    with _cache_lock:
        if len(_cache) >= CACHE_MAX:
            _cache.pop(min(_cache, key=lambda k: _cache[k][0]))
        _cache[key] = (time.time(), result)
    return result
