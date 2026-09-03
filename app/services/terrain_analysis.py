"""
Terrain Analysis Service.

Responsibility:
- Calculate slope raster (in degrees and percentage) from DEM using finite-difference gradients,
  correctly derived from geotransform cell resolution.
- Calculate local depression index and Topographic Position Index (TPI) using neighborhood filters
  to detect hollows, swales, and natural low points.
- Compute composite pond siting suitability score (0-100) using configurable weighted metrics.
- Expose all thresholds, window radii, and weights as configurable parameters with data-driven defaults.
- Export slope, depression, and suitability rasters to GeoTIFF and multi-panel debug visualizations.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Union

import numpy as np
from scipy.ndimage import minimum_filter, maximum_filter, uniform_filter

from app.services.dem_builder import DEMData

logger = logging.getLogger(__name__)


@dataclass
class TerrainAnalysisResult:
    """
    Container for computed terrain derivatives and pond suitability metrics.
    """
    slope_degrees: np.ndarray       # 2D array of slope in degrees [0, 90]
    slope_percent: np.ndarray       # 2D array of slope in percent [0, inf)
    depression_index: np.ndarray    # 2D array of relative depression score [0, 100] (100 = deepest local hollow)
    tpi: np.ndarray                 # Topographic Position Index in meters (negative = valley/depression)
    suitability_score: np.ndarray   # Composite pond suitability score [0, 100]
    suitable_mask: np.ndarray       # Boolean mask of highly suitable candidate pond excavation zones
    dem_data: DEMData               # Source DEM reference
    twi: Optional[np.ndarray] = None        # Topographic Wetness Index (ln(a / tan(beta)))
    twi_score: Optional[np.ndarray] = None  # Normalized TWI score [0, 100]
    flow_accum: Optional[np.ndarray] = None  # Pre-computed D8 flow accumulation grid (reused by catchment delineation)
    flow_dir: Optional[np.ndarray] = None    # Pre-computed D8 flow direction grid (reused by catchment delineation)

    @property
    def shape(self) -> Tuple[int, int]:
        return self.slope_degrees.shape

    @property
    def mean_slope_deg(self) -> float:
        return float(np.nanmean(self.slope_degrees))

    @property
    def max_slope_deg(self) -> float:
        return float(np.nanmax(self.slope_degrees))

    @property
    def mean_suitability(self) -> float:
        return float(np.nanmean(self.suitability_score))

    @property
    def mean_twi(self) -> float:
        if self.twi is not None:
            return float(np.nanmean(self.twi))
        return 0.0

    @property
    def suitable_area_percentage(self) -> float:
        """Percentage of total area meeting the suitability criteria."""
        return float(np.count_nonzero(self.suitable_mask) / self.suitable_mask.size * 100.0)


class TerrainAnalysisService:
    """
    Service for computing slope, topographic depressions, and water harvesting suitability rasters.
    """

    def __init__(self):
        pass

    def compute_slope(
        self,
        dem_data: DEMData,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute slope grid in degrees and percentage using finite-difference gradient.
        Correctly derives cell size from the affine transform.

        Args:
            dem_data (DEMData): Input DEM data object.

        Returns:
            Tuple[np.ndarray, np.ndarray]: (slope_degrees, slope_percent)
        """
        # Extract true pixel spacing in meters from affine transform
        dx = abs(dem_data.transform.a) if hasattr(dem_data.transform, "a") else dem_data.resolution
        dy = abs(dem_data.transform.e) if hasattr(dem_data.transform, "e") else dem_data.resolution

        if dx <= 0 or dy <= 0:
            dx = dy = dem_data.resolution

        # Compute gradient (northing decreases with row index, so dy spacing is positive)
        grad_y, grad_x = np.gradient(dem_data.array, dy, dx)

        # Vector magnitude (rise / run)
        rise_run = np.sqrt(grad_x ** 2 + grad_y ** 2)

        # Slope in radians, degrees, and percentage
        slope_rad = np.arctan(rise_run)
        slope_deg = np.degrees(slope_rad)
        slope_pct = rise_run * 100.0

        return slope_deg.astype(np.float64), slope_pct.astype(np.float64)

    def compute_depression_metrics(
        self,
        dem_data: DEMData,
        neighborhood_radius_m: Optional[float] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute local depression index (0-100) and Topographic Position Index (TPI).

        Args:
            dem_data (DEMData): Input DEM data object.
            neighborhood_radius_m (Optional[float]): Radius in meters for local filter window.
                If None, defaults to max(30m, 6 * resolution).

        Returns:
            Tuple[np.ndarray, np.ndarray]: (depression_index_score, tpi_meters)
        """
        res = dem_data.resolution

        # Data-driven default neighborhood radius
        if neighborhood_radius_m is None or neighborhood_radius_m <= 0:
            neighborhood_radius_m = max(30.0, res * 6.0)

        # Compute window size in pixels (must be odd)
        window_size = int(np.round(neighborhood_radius_m / res)) * 2 + 1
        window_size = max(3, window_size)

        logger.info(
            "Computing depression metrics: radius=%.1fm, window_size=%dx%d pixels",
            neighborhood_radius_m,
            window_size,
            window_size,
        )

        dem_arr = dem_data.array

        # Local neighbourhood statistics
        local_mean = uniform_filter(dem_arr, size=window_size, mode="reflect")
        local_min = minimum_filter(dem_arr, size=window_size, mode="reflect")
        local_max = maximum_filter(dem_arr, size=window_size, mode="reflect")

        # Topographic Position Index (TPI): difference from local mean in meters
        tpi = dem_arr - local_mean

        # Relative Elevation Position within local relief [0.0 = bottom of hollow, 1.0 = hilltop]
        relief_range = local_max - local_min
        # Add epsilon to prevent division by zero in perfectly flat areas
        relative_pos = (dem_arr - local_min) / (relief_range + 1e-6)

        # Depression score (0 to 100): inverted relative position + boost for negative TPI
        # 100 = ideal low point / basin floor, 0 = ridge crest / hilltop
        base_depression_score = (1.0 - relative_pos) * 100.0

        # Further enhance scores where TPI is noticeably negative (valley floors / hollows)
        tpi_normalized = np.clip(-tpi / (relief_range + 1e-6) * 2.0, -0.2, 1.0)
        depression_score = np.clip(base_depression_score * 0.8 + np.maximum(0.0, tpi_normalized) * 20.0, 0.0, 100.0)

        return depression_score.astype(np.float64), tpi.astype(np.float64)

    def compute_twi(
        self,
        dem_data: DEMData,
        slope_deg: Optional[np.ndarray] = None,
        flow_accum: Optional[np.ndarray] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute Topographic Wetness Index (TWI = ln(a / tan(beta))) and normalized 0-100 score.
        Identifies natural saturation zones and soil water accumulation convergence zones.

        Args:
            dem_data (DEMData): Input DEM data object.
            slope_deg (Optional[np.ndarray]): Pre-computed slope in degrees.
            flow_accum (Optional[np.ndarray]): Pre-computed flow accumulation grid.

        Returns:
            Tuple[np.ndarray, np.ndarray]: (twi_raw, twi_score_0_to_100)
        """
        dx = abs(dem_data.transform.a) if hasattr(dem_data.transform, "a") else dem_data.resolution
        dy = abs(dem_data.transform.e) if hasattr(dem_data.transform, "e") else dem_data.resolution
        if dx <= 0 or dy <= 0:
            dx = dy = dem_data.resolution

        if slope_deg is None:
            slope_deg, _ = self.compute_slope(dem_data)

        if flow_accum is None:
            from app.services.catchment_delineation import (
                compute_native_d8_flow_direction,
                compute_native_d8_flow_accumulation,
            )
            fdir = compute_native_d8_flow_direction(dem_data.array, dx, dy)
            flow_accum = compute_native_d8_flow_accumulation(fdir)

        # Specific catchment area per unit contour width (m²/m)
        specific_area = np.maximum(1.0, flow_accum * dx)

        # Local slope in radians (bounded to avoid tan(0) division or inf)
        slope_rad = np.radians(np.clip(slope_deg, 0.2, 85.0))
        tan_slope = np.maximum(0.0035, np.tan(slope_rad))

        # Raw TWI
        twi_raw = np.log(specific_area / tan_slope)

        # Robust percentile normalization to 0-100 score
        p5 = float(np.percentile(twi_raw, 5))
        p95 = float(np.percentile(twi_raw, 95))
        twi_range = max(1e-3, p95 - p5)

        twi_score = np.clip((twi_raw - p5) / twi_range * 100.0, 0.0, 100.0)

        return twi_raw.astype(np.float64), twi_score.astype(np.float64)

    def analyze_terrain(
        self,
        dem_data: DEMData,
        ideal_slope_deg: float = 3.0,
        max_slope_deg: float = 8.0,
        neighborhood_radius_m: Optional[float] = None,
        weight_slope: float = 0.35,
        weight_depression: float = 0.35,
        weight_twi: float = 0.30,
        suitability_threshold: float = 60.0,
    ) -> TerrainAnalysisResult:
        """
        Run complete terrain analysis and pond suitability scoring.

        Args:
            dem_data (DEMData): Input DEM data object.
            ideal_slope_deg (float): Maximum slope angle (in degrees) for 100% slope score.
            max_slope_deg (float): Upper slope angle threshold; slopes above this receive 0 score.
            neighborhood_radius_m (Optional[float]): Radius for local depression window.
            weight_slope (float): Weight for slope factor in composite score.
            weight_depression (float): Weight for depression factor in composite score.
            weight_twi (float): Weight for Topographic Wetness Index (TWI) in composite score.
            suitability_threshold (float): Minimum score (0-100) to classify cell as suitable.

        Returns:
            TerrainAnalysisResult: Computed terrain grids, scores, and suitability mask.
        """
        if max_slope_deg <= ideal_slope_deg:
            raise ValueError(f"max_slope_deg ({max_slope_deg}) must be greater than ideal_slope_deg ({ideal_slope_deg})")

        # 1. Slope computation
        slope_deg, slope_pct = self.compute_slope(dem_data)

        # 2. Depression computation
        depression_score, tpi = self.compute_depression_metrics(
            dem_data, neighborhood_radius_m=neighborhood_radius_m
        )

        # 3. Compute D8 flow direction and accumulation once here so they can be
        #    (a) passed into compute_twi (avoids internal recomputation) and
        #    (b) stored on the result for reuse by CatchmentDelineationService.
        dx = abs(dem_data.transform.a) if hasattr(dem_data.transform, "a") else dem_data.resolution
        dy = abs(dem_data.transform.e) if hasattr(dem_data.transform, "e") else dem_data.resolution
        if dx <= 0 or dy <= 0:
            dx = dy = dem_data.resolution

        from app.services.catchment_delineation import (
            compute_native_d8_flow_direction,
            compute_native_d8_flow_accumulation,
        )
        flow_dir_arr = compute_native_d8_flow_direction(dem_data.array, dx, dy)
        flow_accum_arr = compute_native_d8_flow_accumulation(flow_dir_arr)

        # 4. Topographic Wetness Index (TWI) — reuse already-computed flow_accum
        twi_raw, twi_score = self.compute_twi(dem_data, slope_deg=slope_deg, flow_accum=flow_accum_arr)

        # 5. Slope scoring function [0 - 100]
        # Slopes <= ideal_slope_deg get 100
        # Slopes between ideal and max decay linearly from 100 to 0
        # Slopes > max_slope_deg get 0
        slope_score = np.where(
            slope_deg <= ideal_slope_deg,
            100.0,
            np.where(
                slope_deg >= max_slope_deg,
                0.0,
                100.0 * (1.0 - (slope_deg - ideal_slope_deg) / (max_slope_deg - ideal_slope_deg)),
            ),
        )

        # 6. Normalize weights
        total_weight = weight_slope + weight_depression + weight_twi
        if total_weight <= 0:
            w_slope, w_dep, w_twi = 0.35, 0.35, 0.30
        else:
            w_slope = weight_slope / total_weight
            w_dep = weight_depression / total_weight
            w_twi = weight_twi / total_weight

        # 7. Composite Multi-Criteria Suitability Score [0 - 100]
        suitability = w_slope * slope_score + w_dep * depression_score + w_twi * twi_score
        suitability = np.clip(suitability, 0.0, 100.0)

        # 8. Binary Suitability Mask
        # Must exceed suitability threshold AND be within allowable slope limit
        suitable_mask = (suitability >= suitability_threshold) & (slope_deg <= max_slope_deg)

        logger.info(
            "Terrain analysis complete: mean slope=%.1f°, mean TWI=%.2f, mean suitability=%.1f, suitable area=%.1f%%",
            float(np.mean(slope_deg)),
            float(np.mean(twi_raw)),
            float(np.mean(suitability)),
            float(np.count_nonzero(suitable_mask) / suitable_mask.size * 100.0),
        )

        return TerrainAnalysisResult(
            slope_degrees=slope_deg.astype(np.float32),
            slope_percent=slope_pct.astype(np.float32),
            depression_index=depression_score.astype(np.float32),
            tpi=tpi.astype(np.float32),
            suitability_score=suitability.astype(np.float32),
            suitable_mask=suitable_mask,
            dem_data=dem_data,
            twi=twi_raw.astype(np.float32),
            twi_score=twi_score.astype(np.float32),
            flow_accum=flow_accum_arr.astype(np.float32),
            flow_dir=flow_dir_arr,
        )

    def save_geotiff(
        self,
        raster_array: np.ndarray,
        dem_data: DEMData,
        output_path: Union[str, Path],
        nodata: float = -9999.0,
    ) -> Path:
        """
        Save an analysis raster (e.g. slope or suitability) as a georeferenced GeoTIFF.
        """
        import rasterio
        from rasterio.crs import CRS

        path = Path(output_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        height, width = raster_array.shape
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
            nodata=nodata,
            compress="lzw",
        ) as dst:
            dst.write(raster_array.astype(np.float32), 1)

        logger.info("Saved GeoTIFF raster to %s", path)
        return path

    def save_analysis_visualization(
        self,
        analysis: TerrainAnalysisResult,
        output_path: Union[str, Path],
        title: Optional[str] = None,
    ) -> Path:
        """
        Generate and save a 4-panel visual summary of the terrain analysis:
        1. Elevation DEM + Hillshade
        2. Slope in Degrees
        3. Local Depression / TPI Map
        4. Pond Siting Suitability Map (0-100) with candidate sweet-spots
        """
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import LightSource

        path = Path(output_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        dem_data = analysis.dem_data
        minx, miny, maxx, maxy = dem_data.bounds
        extent = [minx, maxx, miny, maxy]

        fig, axs = plt.subplots(2, 2, figsize=(18, 14), constrained_layout=True)

        # --- Panel 1: Shaded Relief Elevation DEM ---
        ls = LightSource(azdeg=315, altdeg=45)
        rgb_blend = ls.shade(
            dem_data.array,
            cmap=plt.cm.terrain,
            blend_mode="overlay",
            vert_exag=1.5,
            dx=dem_data.resolution,
            dy=dem_data.resolution,
        )
        im1 = axs[0, 0].imshow(rgb_blend, extent=extent, origin="upper")
        axs[0, 0].set_title("1. Elevation & Shaded Relief", fontsize=13, fontweight="bold")
        axs[0, 0].set_xlabel("UTM Easting (m)")
        axs[0, 0].set_ylabel("UTM Northing (m)")
        axs[0, 0].grid(True, linestyle="--", alpha=0.3)

        # --- Panel 2: Slope Map (Degrees) ---
        im2 = axs[0, 1].imshow(
            analysis.slope_degrees,
            cmap="RdYlGn_r",  # Green = flat/gentle, Red = steep
            vmin=0.0,
            vmax=max(15.0, float(np.percentile(analysis.slope_degrees, 95))),
            extent=extent,
            origin="upper",
        )
        cbar2 = fig.colorbar(im2, ax=axs[0, 1], fraction=0.046, pad=0.04)
        cbar2.set_label("Slope (Degrees)", fontsize=11, fontweight="bold")
        axs[0, 1].set_title(f"2. Terrain Slope (Mean: {analysis.mean_slope_deg:.1f}°)", fontsize=13, fontweight="bold")
        axs[0, 1].set_xlabel("UTM Easting (m)")
        axs[0, 1].set_ylabel("UTM Northing (m)")
        axs[0, 1].grid(True, linestyle="--", alpha=0.3)

        # --- Panel 3: Local Depression / TPI Map ---
        im3 = axs[1, 0].imshow(
            analysis.depression_index,
            cmap="Blues",  # Darker blue = deeper depression/hollow
            vmin=0,
            vmax=100,
            extent=extent,
            origin="upper",
        )
        cbar3 = fig.colorbar(im3, ax=axs[1, 0], fraction=0.046, pad=0.04)
        cbar3.set_label("Depression Index (0-100)", fontsize=11, fontweight="bold")
        axs[1, 0].set_title("3. Topographic Depression Index (Low Points)", fontsize=13, fontweight="bold")
        axs[1, 0].set_xlabel("UTM Easting (m)")
        axs[1, 0].set_ylabel("UTM Northing (m)")
        axs[1, 0].grid(True, linestyle="--", alpha=0.3)

        # --- Panel 4: Composite Pond Suitability Map ---
        im4 = axs[1, 1].imshow(
            analysis.suitability_score,
            cmap="viridis",
            vmin=0,
            vmax=100,
            extent=extent,
            origin="upper",
        )
        cbar4 = fig.colorbar(im4, ax=axs[1, 1], fraction=0.046, pad=0.04)
        cbar4.set_label("Suitability Score (0-100)", fontsize=11, fontweight="bold")

        # Highlight suitable candidate threshold boundaries
        if np.any(analysis.suitable_mask):
            axs[1, 1].contour(
                analysis.suitable_mask.astype(int),
                levels=[0.5],
                colors="red",
                linewidths=1.5,
                extent=extent,
                origin="upper",
            )

        axs[1, 1].set_title(
            f"4. Pond Siting Suitability (Suitable Area: {analysis.suitable_area_percentage:.1f}%)",
            fontsize=13,
            fontweight="bold",
        )
        axs[1, 1].set_xlabel("UTM Easting (m)")
        axs[1, 1].set_ylabel("UTM Northing (m)")
        axs[1, 1].grid(True, linestyle="--", alpha=0.3)

        main_title = title or (
            f"Terrain & Pond Suitability Analysis — Mean Suitability: {analysis.mean_suitability:.1f}/100 "
            f"({dem_data.crs}, Res: {dem_data.resolution:.1f}m)"
        )
        fig.suptitle(main_title, fontsize=16, fontweight="bold")

        plt.savefig(path, dpi=200, bbox_inches="tight")
        plt.close(fig)

        logger.info("Saved terrain analysis visualization PNG to %s", path)
        return path


# Convenience function
def analyze_terrain(
    dem_data: DEMData,
    ideal_slope_deg: float = 3.0,
    max_slope_deg: float = 8.0,
    neighborhood_radius_m: Optional[float] = None,
    weight_slope: float = 0.35,
    weight_depression: float = 0.35,
    weight_twi: float = 0.30,
    suitability_threshold: float = 60.0,
) -> TerrainAnalysisResult:
    """Convenience helper to run full terrain analysis on a DEMData object."""
    service = TerrainAnalysisService()
    return service.analyze_terrain(
        dem_data=dem_data,
        ideal_slope_deg=ideal_slope_deg,
        max_slope_deg=max_slope_deg,
        neighborhood_radius_m=neighborhood_radius_m,
        weight_slope=weight_slope,
        weight_depression=weight_depression,
        weight_twi=weight_twi,
        suitability_threshold=suitability_threshold,
    )
