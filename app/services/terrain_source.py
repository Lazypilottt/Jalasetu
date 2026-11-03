"""
Global elevation source for analyses without a contour file.

When the user clicks a point outside every available contour map, the DEM is
built from public Terrarium elevation tiles (AWS Open Data "Terrain Tiles",
SRTM/NED-derived, about 30 m native resolution). Tiles are mosaicked in Web
Mercator, resampled bilinearly onto a local UTM grid centred on the point, and
lightly smoothed to soften SRTM's 1 m vertical quantisation. The result is an
ordinary ``DEMData``, so terrain analysis, ranking and catchment delineation
run unchanged.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional, Tuple

import numpy as np
from affine import Affine
from pyproj import Transformer
from scipy import ndimage

from app.services.dem_builder import DEMData
from app.utils.geometry import get_utm_epsg_from_lon_lat

logger = logging.getLogger(__name__)

TILE_URL = os.getenv(
    "JALASETU_TERRAIN_TILE_URL",
    "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
)
TILE_SIZE = 256
DEFAULT_ZOOM = 14  # ~9 m/pixel at 21° N; finer zooms only upsample the 30 m source
DEFAULT_RESOLUTION_M = 10.0
MAX_TILES = 16
SOURCE_LABEL = "Global DEM (Terrarium terrain tiles, SRTM-derived ~30 m)"

# Extent of the bundled demonstration contours (contours_1m.kml), WGS84.
BUNDLED_CONTOUR_BOUNDS = (81.2814, 21.23982, 81.31265, 21.26358)

_tile_cache: Dict[Tuple[int, int, int], np.ndarray] = {}
_cache_lock = threading.Lock()
_CACHE_MAX = 16  # 16 float32 tiles = 4 MB


def point_in_bundled_extent(lat: float, lon: float, margin_deg: float = 0.0) -> bool:
    min_lon, min_lat, max_lon, max_lat = BUNDLED_CONTOUR_BOUNDS
    return (min_lon - margin_deg) <= lon <= (max_lon + margin_deg) and (min_lat - margin_deg) <= lat <= (max_lat + margin_deg)


def _lonlat_to_pixel(lon: np.ndarray, lat: np.ndarray, zoom: int) -> Tuple[np.ndarray, np.ndarray]:
    scale = TILE_SIZE * 2 ** zoom
    x = (lon + 180.0) / 360.0 * scale
    lat_rad = np.radians(np.clip(lat, -85.05112878, 85.05112878))
    y = (1.0 - np.arcsinh(np.tan(lat_rad)) / math.pi) / 2.0 * scale
    return x, y


def decode_terrarium(png_bytes: bytes) -> np.ndarray:
    """Terrarium PNG -> elevation metres: (R * 256 + G + B / 256) - 32768."""
    import warnings

    from rasterio.errors import NotGeoreferencedWarning
    from rasterio.io import MemoryFile

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with MemoryFile(png_bytes) as memfile, memfile.open() as dataset:
            rgb = dataset.read(out_dtype="float32")[:3]
    return rgb[0] * 256.0 + rgb[1] + rgb[2] / 256.0 - 32768.0


def _fetch_tile(z: int, x: int, y: int) -> np.ndarray:
    key = (z, x, y)
    with _cache_lock:
        if key in _tile_cache:
            return _tile_cache[key]
    url = TILE_URL.format(z=z, x=x, y=y)
    request = urllib.request.Request(url, headers={"User-Agent": "JalaSetu/1.0 (farm pond siting)"})
    with urllib.request.urlopen(request, timeout=20) as response:
        elevation = decode_terrarium(response.read())
    with _cache_lock:
        if len(_tile_cache) >= _CACHE_MAX:
            _tile_cache.pop(next(iter(_tile_cache)))
        _tile_cache[key] = elevation
    return elevation


def fetch_global_dem(
    latitude: float,
    longitude: float,
    half_size_m: float = 1000.0,
    resolution_m: Optional[float] = None,
    zoom: int = DEFAULT_ZOOM,
) -> DEMData:
    """Square DEM of side ``2 * half_size_m`` centred on the point, in local UTM."""
    resolution = float(resolution_m or DEFAULT_RESOLUTION_M)
    resolution = max(5.0, min(resolution, 30.0))
    half_size_m = max(300.0, min(float(half_size_m), 3000.0))

    epsg = get_utm_epsg_from_lon_lat(longitude, latitude)
    crs = f"EPSG:{epsg}"
    to_utm = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    cx, cy = to_utm.transform(longitude, latitude)
    n = int(math.ceil(2 * half_size_m / resolution))
    minx, maxy = cx - n * resolution / 2.0, cy + n * resolution / 2.0
    transform = Affine(resolution, 0.0, minx, 0.0, -resolution, maxy)

    cols, rows = np.meshgrid(np.arange(n) + 0.5, np.arange(n) + 0.5)
    xs = minx + cols * resolution
    ys = maxy - rows * resolution
    lons, lats = to_wgs.transform(xs, ys)
    px, py = _lonlat_to_pixel(np.asarray(lons), np.asarray(lats), zoom)

    tx0, tx1 = int(np.floor(px.min() / TILE_SIZE)), int(np.floor(px.max() / TILE_SIZE))
    ty0, ty1 = int(np.floor(py.min() / TILE_SIZE)), int(np.floor(py.max() / TILE_SIZE))
    tiles = [(tx, ty) for ty in range(ty0, ty1 + 1) for tx in range(tx0, tx1 + 1)]
    if len(tiles) > MAX_TILES:
        raise ValueError("Requested area is too large for the global elevation source.")
    try:
        with ThreadPoolExecutor(max_workers=min(4, len(tiles))) as pool:
            arrays = list(pool.map(lambda t: _fetch_tile(zoom, t[0], t[1]), tiles))
    except Exception as exc:
        raise ValueError(
            "Global elevation data is unavailable right now. Upload a .kml/.kmz contour file "
            f"for this area instead. ({exc})"
        ) from exc

    mosaic = np.zeros(((ty1 - ty0 + 1) * TILE_SIZE, (tx1 - tx0 + 1) * TILE_SIZE), dtype="float32")
    for (tx, ty), arr in zip(tiles, arrays):
        r, c = (ty - ty0) * TILE_SIZE, (tx - tx0) * TILE_SIZE
        mosaic[r:r + TILE_SIZE, c:c + TILE_SIZE] = arr

    local_x = px - tx0 * TILE_SIZE - 0.5
    local_y = py - ty0 * TILE_SIZE - 0.5
    elevation = ndimage.map_coordinates(mosaic, [local_y, local_x], order=1, mode="nearest").astype("float64")
    # The source is integer metres at ~30 m; a 1-cell blur removes terracing
    # that would otherwise read as spurious flats and steps.
    elevation = ndimage.gaussian_filter(elevation, sigma=max(0.8, 15.0 / resolution))
    if not np.isfinite(elevation).all() or float(elevation.max() - elevation.min()) > 9000:
        raise ValueError("Global elevation tiles returned invalid data for this location.")

    logger.info(
        "Built global DEM %dx%d at %.0f m around (%.5f, %.5f) from %d tile(s)",
        n, n, resolution, latitude, longitude, len(tiles),
    )
    return DEMData(
        array=elevation,
        transform=transform,
        crs=crs,
        nodata=-9999.0,
        resolution=resolution,
        bounds=(minx, maxy - n * resolution, minx + n * resolution, maxy),
    )


def dem_bounds_wgs84(dem: DEMData) -> Tuple[float, float, float, float]:
    """(min_lon, min_lat, max_lon, max_lat) of a UTM DEM."""
    to_wgs = Transformer.from_crs(dem.crs, "EPSG:4326", always_xy=True)
    minx, miny, maxx, maxy = dem.bounds
    lons, lats = to_wgs.transform([minx, maxx, minx, maxx], [miny, miny, maxy, maxy])
    return min(lons), min(lats), max(lons), max(lats)
