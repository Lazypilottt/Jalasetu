"""
Geometry and Coordinate Reference System (CRS) Utilities.

Responsibility:
- Reprojection between Geographic (WGS84 EPSG:4326) and Projected (UTM / local metric) coordinate reference systems.
- Auto-detecting the optimal UTM zone from longitude/latitude centroid for accurate metric distance/area computations.
- Reprojecting GeoDataFrames and Shapely geometries.
- Geometric transformations and spatial helpers.
"""

import math
from typing import Tuple, Optional, Union, List
import numpy as np
import geopandas as gpd
from affine import Affine
from pyproj import Transformer
import rasterio.features
from shapely.geometry import Polygon, MultiPolygon, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union, transform as shapely_transform


def get_utm_epsg_from_lon_lat(lon: float, lat: float) -> int:
    """
    Determine the appropriate UTM EPSG code based on WGS84 longitude and latitude.

    Args:
        lon (float): Longitude in degrees (-180 to 180).
        lat (float): Latitude in degrees (-90 to 90).

    Returns:
        int: EPSG code for the corresponding UTM zone (e.g., 32644 for UTM zone 44N).
    """
    # Clamp longitude to [-180, 180)
    clamped_lon = ((lon + 180.0) % 360.0) - 180.0
    zone_number = int((clamped_lon + 180.0) / 6.0) + 1
    zone_number = max(1, min(60, zone_number))

    if lat >= 0:
        return 32600 + zone_number  # WGS 84 / UTM zone 1N to 60N
    else:
        return 32700 + zone_number  # WGS 84 / UTM zone 1S to 60S


def calculate_utm_crs_from_gdf(gdf: gpd.GeoDataFrame) -> int:
    """
    Calculate the optimal UTM EPSG code from the bounding box centroid of a GeoDataFrame.

    Args:
        gdf (gpd.GeoDataFrame): GeoDataFrame in EPSG:4326.

    Returns:
        int: Optimal UTM EPSG code.

    Raises:
        ValueError: If GeoDataFrame is empty or has invalid bounds.
    """
    if gdf.empty:
        raise ValueError("Cannot compute UTM CRS for an empty GeoDataFrame.")

    minx, miny, maxx, maxy = gdf.total_bounds
    center_lon = (minx + maxx) / 2.0
    center_lat = (miny + maxy) / 2.0
    return get_utm_epsg_from_lon_lat(center_lon, center_lat)


def reproject_to_utm(gdf: gpd.GeoDataFrame) -> Tuple[gpd.GeoDataFrame, int]:
    """
    Reproject a GeoDataFrame from EPSG:4326 to its auto-calculated local UTM zone.

    Args:
        gdf (gpd.GeoDataFrame): Input GeoDataFrame (assumed EPSG:4326 if not set).

    Returns:
        Tuple[gpd.GeoDataFrame, int]: (Reprojected GeoDataFrame, UTM EPSG code).
    """
    if gdf.empty:
        return gdf.copy(), 4326

    # Ensure input CRS is EPSG:4326
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs("EPSG:4326")

    utm_epsg = calculate_utm_crs_from_gdf(gdf)
    reprojected_gdf = gdf.to_crs(epsg=utm_epsg)
    return reprojected_gdf, utm_epsg


def rowcol_to_utm(
    transform: Affine,
    row: float,
    col: float,
    offset: str = "center",
) -> Tuple[float, float]:
    """
    Convert raster row and column continuous indices to real-world UTM coordinates.

    Args:
        transform (Affine): DEM raster affine transform matrix.
        row (float): Raster row index (0-indexed).
        col (float): Raster column index (0-indexed).
        offset (str): Pixel offset position - 'center' (default) for (col+0.5, row+0.5)
                      or 'corner' / 'ul' for (col, row).

    Returns:
        Tuple[float, float]: Real-world (utm_x, utm_y) coordinates in UTM CRS.
    """
    if offset == "center":
        c_off = col + 0.5
        r_off = row + 0.5
    else:
        c_off = col
        r_off = row
    utm_x = transform.c + transform.a * c_off + transform.b * r_off
    utm_y = transform.f + transform.d * c_off + transform.e * r_off
    return float(utm_x), float(utm_y)


def utm_to_rowcol(
    transform: Affine,
    utm_x: float,
    utm_y: float,
    height: Optional[int] = None,
    width: Optional[int] = None,
) -> Tuple[int, int]:
    """
    Convert real-world UTM coordinates to integer raster row and column indices.
    Uses floor-based spatial mapping to correctly map continuous coordinates inside
    pixel bounds [c, c+1) and [r, r+1) without round-half-to-even half-cell shifts.

    Args:
        transform (Affine): DEM raster affine transform matrix.
        utm_x (float): Real-world Easting coordinate.
        utm_y (float): Real-world Northing coordinate.
        height (Optional[int]): Maximum raster height for clipping.
        width (Optional[int]): Maximum raster width for clipping.

    Returns:
        Tuple[int, int]: (row, col) integer raster indices.
    """
    inv_transform = ~transform
    col_float = inv_transform.c + inv_transform.a * utm_x + inv_transform.b * utm_y
    row_float = inv_transform.f + inv_transform.d * utm_x + inv_transform.e * utm_y
    r = int(math.floor(row_float))
    c = int(math.floor(col_float))

    if height is not None:
        r = max(0, min(height - 1, r))
    if width is not None:
        c = max(0, min(width - 1, c))

    return r, c


def vectorize_mask_to_polygon(
    mask: np.ndarray,
    transform: Affine,
) -> Union[Polygon, MultiPolygon]:
    """
    Vectorize a binary raster mask into a clean Shapely Polygon or MultiPolygon.
    Uses pixel corners transformed by affine to ensure pixel centers fall strictly
    inside the vectorized polygon.

    Args:
        mask (np.ndarray): 2D binary boolean or integer mask.
        transform (Affine): Affine transform mapping pixel space to CRS coordinates.

    Returns:
        Union[Polygon, MultiPolygon]: Cleaned, unified Shapely geometry in target CRS.
    """
    if not np.any(mask):
        return Polygon()

    shapes_gen = rasterio.features.shapes(
        mask.astype(np.uint8),
        mask=mask,
        transform=transform,
        connectivity=8,
    )

    polygons: List[Polygon] = []
    for geom_dict, val in shapes_gen:
        if val == 1:
            poly = shape(geom_dict)
            if poly.is_valid and not poly.is_empty:
                polygons.append(poly)
            elif not poly.is_valid:
                poly_fixed = poly.buffer(0)
                if poly_fixed.is_valid and not poly_fixed.is_empty:
                    polygons.append(poly_fixed)

    if not polygons:
        return Polygon()

    unified = unary_union(polygons)
    return unified


def reproject_geometry(
    geom: BaseGeometry,
    src_crs: str,
    dst_crs: str = "EPSG:4326",
) -> BaseGeometry:
    """
    Reproject a Shapely geometry from src_crs to dst_crs.
    Ensures standard (x, y) coordinate ordering (e.g. lon, lat for EPSG:4326).

    Args:
        geom (BaseGeometry): Shapely geometry in src_crs.
        src_crs (str): Source CRS (e.g. 'EPSG:32644').
        dst_crs (str): Destination CRS (e.g. 'EPSG:4326').

    Returns:
        BaseGeometry: Reprojected Shapely geometry.
    """
    if geom is None or geom.is_empty:
        return geom

    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)

    def _transform_pt(x, y, z=None):
        return transformer.transform(x, y)

    return shapely_transform(_transform_pt, geom)

