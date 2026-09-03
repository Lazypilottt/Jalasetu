"""
Digital Elevation Model (DEM) Builder Service.

Responsibility:
- Convert discrete contour lines / elevation polygons into a regular 2D raster DEM.
- Automatically reproject input geometries into the local UTM CRS (in meters).
- Dense point sampling along contour lines and vertices.
- Spatial interpolation using scipy.interpolate (linear/cubic griddata with nearest-neighbor boundary fill).
- Data-driven adaptive resolution computation.
- Packaging raster arrays and spatial metadata into DEMData dataclass.
- Debug utilities: Export to GeoTIFF (rasterio) and hillshade/elevation heatmap visualization (matplotlib).
"""

import io
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Union

import geopandas as gpd
import numpy as np
from affine import Affine
from scipy.interpolate import griddata
from shapely.geometry import (
    LineString,
    MultiLineString,
    Polygon,
    MultiPolygon,
    Point,
    MultiPoint,
)
from shapely.geometry.base import BaseGeometry

from app.utils.geometry import reproject_to_utm

logger = logging.getLogger(__name__)


@dataclass
class DEMData:
    """
    Container for Digital Elevation Model raster data and spatial georeferencing metadata.
    """
    array: np.ndarray  # 2D numpy array [rows, cols] (float64 or float32)
    transform: Affine  # Affine geotransform
    crs: str  # EPSG string (e.g. 'EPSG:32643')
    nodata: float = -9999.0
    resolution: float = 5.0  # Cell size in meters
    bounds: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # (minx, miny, maxx, maxy) in UTM meters

    @property
    def shape(self) -> Tuple[int, int]:
        """Dimensions (rows, cols) of the raster."""
        return self.array.shape

    @property
    def height(self) -> int:
        """Number of rows (northing cells)."""
        return self.array.shape[0]

    @property
    def width(self) -> int:
        """Number of columns (easting cells)."""
        return self.array.shape[1]

    @property
    def min_elevation(self) -> float:
        """Minimum elevation value in the DEM raster."""
        return float(np.nanmin(self.array))

    @property
    def max_elevation(self) -> float:
        """Maximum elevation value in the DEM raster."""
        return float(np.nanmax(self.array))

    @property
    def mean_elevation(self) -> float:
        """Mean elevation value in the DEM raster."""
        return float(np.nanmean(self.array))

    @property
    def elevation_span(self) -> float:
        """Total relief / elevation span (max - min)."""
        return self.max_elevation - self.min_elevation


def _sample_points_along_geometry(
    geom: BaseGeometry,
    elevation: float,
    sample_spacing: float,
) -> List[Tuple[float, float, float]]:
    """
    Sample points along a Shapely geometry at regular intervals and include all vertices.
    """
    points: List[Tuple[float, float, float]] = []

    if geom is None or geom.is_empty:
        return points

    if isinstance(geom, LineString):
        # 1. Include all existing vertices
        for x, y in geom.coords:
            points.append((float(x), float(y), elevation))

        # 2. Sample along length at regular intervals
        length = geom.length
        if length > 0 and sample_spacing > 0:
            num_steps = max(2, int(np.ceil(length / sample_spacing)) + 1)
            for dist in np.linspace(0, length, num_steps):
                pt = geom.interpolate(dist)
                points.append((float(pt.x), float(pt.y), elevation))

    elif isinstance(geom, Polygon):
        # Sample exterior boundary
        points.extend(_sample_points_along_geometry(geom.exterior, elevation, sample_spacing))
        # Sample interior rings (holes)
        for interior in geom.interiors:
            points.extend(_sample_points_along_geometry(interior, elevation, sample_spacing))

    elif isinstance(geom, MultiLineString):
        for line in geom.geoms:
            points.extend(_sample_points_along_geometry(line, elevation, sample_spacing))

    elif isinstance(geom, MultiPolygon):
        for poly in geom.geoms:
            points.extend(_sample_points_along_geometry(poly, elevation, sample_spacing))

    elif isinstance(geom, Point):
        points.append((float(geom.x), float(geom.y), elevation))

    elif isinstance(geom, MultiPoint):
        for pt in geom.geoms:
            points.append((float(pt.x), float(pt.y), elevation))

    return points


def estimate_adaptive_resolution(gdf_utm: gpd.GeoDataFrame) -> float:
    """
    Derive a sensible, data-driven raster resolution (in meters) based on the spatial
    extent and contour density, avoiding magic numbers.
    """
    if gdf_utm.empty:
        return 5.0

    minx, miny, maxx, maxy = gdf_utm.total_bounds
    width = max(maxx - minx, 1.0)
    height = max(maxy - miny, 1.0)
    max_dim = max(width, height)

    # Target ~250-400 grid cells along the maximum dimension for optimal balance
    # between topographic detail and interpolation speed.
    raw_res = max_dim / 300.0

    # Clamp between 1.0 meter (for small farm plots) and 50.0 meters (for large regional basins)
    clamped_res = float(np.clip(raw_res, 1.0, 50.0))

    # Round to clean standard intervals (e.g. 1.0, 2.0, 2.5, 5.0, 10.0, 20.0, etc.)
    standard_steps = [1.0, 2.0, 2.5, 5.0, 10.0, 15.0, 20.0, 25.0, 50.0]
    best_res = min(standard_steps, key=lambda s: abs(s - clamped_res))
    return float(best_res)


def compute_hillshade(
    dem_array: np.ndarray,
    resolution: float,
    azimuth: float = 315.0,
    altitude: float = 45.0,
) -> np.ndarray:
    """
    Calculate an analytical shaded relief (hillshade) from a 2D elevation grid.

    Args:
        dem_array (np.ndarray): 2D elevation array.
        resolution (float): Pixel cell size in meters.
        azimuth (float): Sun illumination azimuth in degrees (315° = Northwest).
        altitude (float): Sun illumination altitude angle in degrees above horizon.

    Returns:
        np.ndarray: Hillshade array scaled from 0 (dark shadow) to 255 (bright highlight).
    """
    # Compute horizontal and vertical elevation gradients
    dy, dx = np.gradient(dem_array, resolution, resolution)

    # Slope angle in radians
    slope = np.pi / 2.0 - np.arctan(np.sqrt(dx * dx + dy * dy))

    # Aspect angle in radians
    aspect = np.arctan2(-dx, dy)

    azimuth_rad = np.radians(360.0 - azimuth + 90.0)
    altitude_rad = np.radians(altitude)

    # Shading equation
    shaded = (
        np.sin(altitude_rad) * np.sin(slope)
        + np.cos(altitude_rad) * np.cos(slope) * np.cos(azimuth_rad - aspect)
    )

    hillshade = 255.0 * np.clip(shaded, 0.0, 1.0)
    return hillshade.astype(np.uint8)


class DEMBuilderService:
    """
    Service for constructing Digital Elevation Models from contour GeoDataFrames.
    """

    def __init__(self):
        pass

    def build_dem(
        self,
        contours_gdf: gpd.GeoDataFrame,
        resolution: Optional[float] = None,
        sample_spacing: Optional[float] = None,
        method: str = "linear",
    ) -> DEMData:
        """
        Convert contour GeoDataFrame into a regular elevation raster (DEM).

        Args:
            contours_gdf (gpd.GeoDataFrame): Contours with ['elevation', 'geometry'].
            resolution (Optional[float]): Raster cell size in meters. If None, derived adaptively.
            sample_spacing (Optional[float]): Distance in meters between sampling points along contour lines.
            method (str): Scipy interpolation method ('linear' or 'cubic').

        Returns:
            DEMData: Dataclass holding the elevation array, affine transform, CRS, and bounds.
        """
        if contours_gdf.empty:
            raise ValueError("Cannot build DEM from an empty contour GeoDataFrame.")

        # 1. Reproject contours to local UTM metric CRS
        gdf_utm, utm_epsg = reproject_to_utm(contours_gdf)
        crs_str = f"EPSG:{utm_epsg}"

        # 2. Determine cell resolution & sample spacing
        if resolution is None or resolution <= 0:
            resolution = estimate_adaptive_resolution(gdf_utm)

        if sample_spacing is None or sample_spacing <= 0:
            # Sample spacing equal to half of grid cell resolution for high fidelity
            sample_spacing = max(1.0, resolution / 2.0)

        logger.info(
            "Building DEM: resolution=%.2fm, sample_spacing=%.2fm, CRS=%s",
            resolution,
            sample_spacing,
            crs_str,
        )

        # 3. Dense point sampling along contour lines
        pts_list: List[Tuple[float, float, float]] = []
        for _, row in gdf_utm.iterrows():
            geom = row["geometry"]
            elev = float(row["elevation"])
            if geom is not None and not geom.is_empty:
                sampled = _sample_points_along_geometry(geom, elev, sample_spacing)
                pts_list.extend(sampled)

        if not pts_list:
            raise ValueError("No valid points could be sampled from contour geometries.")

        pts_array = np.array(pts_list, dtype=np.float64)
        x_pts = pts_array[:, 0]
        y_pts = pts_array[:, 1]
        z_pts = pts_array[:, 2]

        logger.info("Sampled %d point cloud vertices across %d contour features.", len(pts_array), len(gdf_utm))

        # 4. Set up regular grid and geotransform
        minx, miny, maxx, maxy = gdf_utm.total_bounds

        # Add half-cell buffer to bounds
        pad = resolution * 0.5
        minx -= pad
        maxx += pad
        miny -= pad
        maxy += pad

        cols = max(2, int(np.ceil((maxx - minx) / resolution)))
        rows = max(2, int(np.ceil((maxy - miny) / resolution)))

        # Exact grid aligned bounds
        maxx = minx + cols * resolution
        miny = maxy - rows * resolution

        # Affine geotransform: (x_res, 0, top_left_x, 0, -y_res, top_left_y)
        transform = Affine(resolution, 0.0, minx, 0.0, -resolution, maxy)

        # Compute grid cell center coordinates
        grid_x_coords = minx + (np.arange(cols) + 0.5) * resolution
        grid_y_coords = maxy - (np.arange(rows) + 0.5) * resolution  # Descending northing (row 0 = top)
        grid_x, grid_y = np.meshgrid(grid_x_coords, grid_y_coords)

        # 5. Interpolation (Linear/Cubic with Nearest-neighbor fallback for hull edges)
        points_xy = np.column_stack((x_pts, y_pts))

        # Primary smooth surface interpolation
        interp_method = method if method in ("linear", "cubic") else "linear"
        try:
            dem_primary = griddata(points_xy, z_pts, (grid_x, grid_y), method=interp_method)
        except Exception as e:
            logger.warning("Primary interpolation (%s) failed (%s), falling back to 'linear'", interp_method, e)
            dem_primary = griddata(points_xy, z_pts, (grid_x, grid_y), method="linear")

        # Lazy nearest-neighbor fill: only interpolate the NaN pixels instead of
        # allocating a second full-sized grid (saves ~1x DEM worth of RAM).
        nan_mask = np.isnan(dem_primary)
        if np.any(nan_mask):
            dem_primary[nan_mask] = griddata(
                points_xy,
                z_pts,
                (grid_x[nan_mask], grid_y[nan_mask]),
                method="nearest",
            )
        dem_array = dem_primary  # no second full-grid copy needed

        # Sanity check: replace any persistent NaNs with median elevation
        if np.isnan(dem_array).any():
            median_elev = float(np.median(z_pts))
            dem_array = np.nan_to_num(dem_array, nan=median_elev)

        dem_data = DEMData(
            array=dem_array.astype(np.float32),  # float32 halves DEM memory vs float64
            transform=transform,
            crs=crs_str,
            nodata=-9999.0,
            resolution=float(resolution),
            bounds=(minx, miny, maxx, maxy),
        )

        logger.info(
            "DEM generated successfully: shape=(%d, %d), elevation range=[%.2fm, %.2fm]",
            rows,
            cols,
            dem_data.min_elevation,
            dem_data.max_elevation,
        )
        return dem_data

    def save_geotiff(
        self,
        dem_data: DEMData,
        output_path: Union[str, Path],
    ) -> Path:
        """
        Save the DEM raster as a georeferenced GeoTIFF file.

        Args:
            dem_data (DEMData): DEM data object.
            output_path (Union[str, Path]): Target output file path.

        Returns:
            Path: Absolute path of saved GeoTIFF.
        """
        import rasterio
        from rasterio.crs import CRS

        path = Path(output_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        height, width = dem_data.shape
        raster_crs = CRS.from_string(dem_data.crs)

        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=height,
            width=width,
            count=1,
            dtype=rasterio.float32,
            crs=raster_crs,
            transform=dem_data.transform,
            nodata=dem_data.nodata,
            compress="lzw",
        ) as dst:
            dst.write(dem_data.array.astype(np.float32), 1)

        logger.info("Saved DEM GeoTIFF to %s", path)
        return path

    def save_visualization(
        self,
        dem_data: DEMData,
        output_path: Union[str, Path],
        contours_gdf: Optional[gpd.GeoDataFrame] = None,
        title: Optional[str] = None,
    ) -> Path:
        """
        Generate and save a visual debug plot showing the shaded relief (hillshade),
        elevation heatmap, and optional contour lines overlay.

        Args:
            dem_data (DEMData): DEM data object.
            output_path (Union[str, Path]): Target output image path (.png).
            contours_gdf (Optional[gpd.GeoDataFrame]): Contours to overlay.
            title (Optional[str]): Plot title.

        Returns:
            Path: Absolute path of saved PNG image.
        """
        import matplotlib
        matplotlib.use("Agg")  # Non-interactive backend
        import matplotlib.pyplot as plt
        from matplotlib.colors import LightSource

        path = Path(output_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        minx, miny, maxx, maxy = dem_data.bounds
        extent = [minx, maxx, miny, maxy]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7), constrained_layout=True)

        # 1. Left Panel: Elevation Heatmap with Contours
        im1 = ax1.imshow(
            dem_data.array,
            cmap="terrain",
            extent=extent,
            origin="upper",
        )
        cbar1 = fig.colorbar(im1, ax=ax1, fraction=0.046, pad=0.04)
        cbar1.set_label("Elevation (m)", fontsize=11, fontweight="bold")
        ax1.set_title("Interpolated Elevation Grid (DEM)", fontsize=13, fontweight="bold")
        ax1.set_xlabel("UTM Easting (m)")
        ax1.set_ylabel("UTM Northing (m)")
        ax1.grid(True, linestyle="--", alpha=0.4)

        # Overlay contours if provided
        if contours_gdf is not None and not contours_gdf.empty:
            gdf_utm, _ = reproject_to_utm(contours_gdf)
            gdf_utm.plot(ax=ax1, color="black", linewidth=0.7, alpha=0.6)

        # 2. Right Panel: Shaded Relief (Hillshade) with Colored Terrain Blend
        ls = LightSource(azdeg=315, altdeg=45)
        rgb_blend = ls.shade(
            dem_data.array,
            cmap=plt.cm.terrain,
            blend_mode="overlay",
            vert_exag=1.5,
            dx=dem_data.resolution,
            dy=dem_data.resolution,
        )

        ax2.imshow(rgb_blend, extent=extent, origin="upper")
        ax2.set_title("3D Shaded Relief / Hillshade (315° NW)", fontsize=13, fontweight="bold")
        ax2.set_xlabel("UTM Easting (m)")
        ax2.set_ylabel("UTM Northing (m)")
        ax2.grid(True, linestyle="--", alpha=0.4)

        fig_title = title or (
            f"DEM Terrain Analysis — Resolution: {dem_data.resolution:.1f}m | "
            f"Elevation Range: {dem_data.min_elevation:.1f}m – {dem_data.max_elevation:.1f}m ({dem_data.crs})"
        )
        fig.suptitle(fig_title, fontsize=15, fontweight="bold")

        plt.savefig(path, dpi=200, bbox_inches="tight")
        plt.close(fig)

        logger.info("Saved DEM visualization PNG to %s", path)
        return path


# Convenience function
def build_dem_from_contours(
    contours_gdf: gpd.GeoDataFrame,
    resolution: Optional[float] = None,
    sample_spacing: Optional[float] = None,
) -> DEMData:
    """Build a DEMData raster object from a contour GeoDataFrame."""
    builder = DEMBuilderService()
    return builder.build_dem(contours_gdf, resolution=resolution, sample_spacing=sample_spacing)
