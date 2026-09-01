"""
Pond Site Identification and Siting Service.

Responsibility:
- Detect candidate farm pond excavation sites from terrain suitability score rasters.
- Connected-component segmentation using scipy.ndimage.label (8-connectivity).
- Filter candidate regions by configurable minimum and maximum footprint areas.
- Compute real-world geographic (WGS84) and projected (UTM) coordinates via DEM affine transform.
- Compute site morphometrics: area (m² / ha), mean elevation, min/max depth, mean slope, and suitability ranking.
- Export ranked candidate list and annotated visual debug maps.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Union, Dict, Any

import numpy as np
from pyproj import Transformer
import scipy.ndimage as ndi
from shapely.geometry import Polygon, MultiPolygon, Point, shape, mapping
from shapely.ops import unary_union

from app.services.dem_builder import DEMData
from app.services.terrain_analysis import TerrainAnalysisResult
from app.utils.geometry import (
    rowcol_to_utm,
    vectorize_mask_to_polygon,
    reproject_geometry,
)

logger = logging.getLogger(__name__)


@dataclass
class PondSiteCandidate:
    """
    Detailed attributes and morphometrics for an identified candidate pond location.
    """
    rank: int
    site_id: str
    utm_x: float                    # Centroid Easting (meters)
    utm_y: float                    # Centroid Northing (meters)
    longitude: float                # Centroid Longitude (WGS84 degrees)
    latitude: float                 # Centroid Latitude (WGS84 degrees)
    area_m2: float                  # Footprint area in square meters
    area_ha: float                  # Footprint area in hectares
    mean_suitability: float         # Average suitability score (0-100)
    max_suitability: float          # Peak suitability score within region
    mean_elevation: float           # Average terrain elevation in meters
    min_elevation: float            # Lowest point in the region (meters)
    max_elevation: float            # Highest rim point in the region (meters)
    mean_slope_deg: float           # Average slope in degrees
    mean_slope_pct: float           # Average slope in percent
    cell_count: int                 # Number of raster grid cells
    raster_centroid_row: float      # Raster row index
    raster_centroid_col: float      # Raster column index
    elongation_ratio: float = 1.0   # Major-to-minor axis length ratio
    major_axis_m: float = 0.0       # Equivalent major axis length in meters
    minor_axis_m: float = 0.0       # Equivalent minor axis length in meters
    inscribed_width_m: float = 0.0  # Maximum inscribed circle diameter in meters
    polygon_utm: Optional[Any] = None    # Shapely Polygon in UTM CRS
    polygon_wgs84: Optional[Any] = None  # Shapely Polygon in WGS84 CRS
    storage_capacity_m3: float = 0.0     # Water storage capacity at design depth (m³)
    cut_volume_m3: float = 0.0           # Earthwork excavation cut volume (m³)
    storage_efficiency_ratio: float = 1.0  # Storage-to-excavation ratio
    mean_twi: float = 0.0                # Mean Topographic Wetness Index across the site
    stage_storage_curve: List[Dict[str, float]] = field(default_factory=list)  # H-A-V depth increments
    composite_mcdm_score: float = 0.0    # Composite Multi-Criteria Decision Score (0-100)

    def to_boundary_geojson_dict(self) -> Optional[Dict[str, Any]]:
        """Convert candidate suitability region polygon to GeoJSON FeatureCollection dict."""
        if self.polygon_wgs84 is None or self.polygon_wgs84.is_empty:
            return None
        geom_dict = mapping(self.polygon_wgs84)
        feature = {
            "type": "Feature",
            "geometry": geom_dict,
            "properties": {
                "site_id": self.site_id,
                "rank": self.rank,
                "area_m2": round(self.area_m2, 1),
                "area_ha": round(self.area_ha, 3),
                "mean_suitability_score": round(self.mean_suitability, 1),
                "peak_suitability_score": round(self.max_suitability, 1),
                "composite_mcdm_score": round(self.composite_mcdm_score, 1),
                "elevation_m": round(self.mean_elevation, 2),
                "slope_deg": round(self.mean_slope_deg, 2),
                "storage_capacity_m3": round(self.storage_capacity_m3, 1),
                "cut_volume_m3": round(self.cut_volume_m3, 1),
                "storage_efficiency_ratio": round(self.storage_efficiency_ratio, 2),
                "mean_twi": round(self.mean_twi, 2),
                "centroid": {
                    "latitude": round(self.latitude, 6),
                    "longitude": round(self.longitude, 6),
                },
            },
        }
        return {
            "type": "FeatureCollection",
            "features": [feature],
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert candidate metrics to JSON-serializable dictionary."""
        d = {
            "rank": self.rank,
            "site_id": self.site_id,
            "coordinates": {
                "latitude": round(self.latitude, 6),
                "longitude": round(self.longitude, 6),
                "utm_easting": round(self.utm_x, 2),
                "utm_northing": round(self.utm_y, 2),
            },
            "area_m2": round(self.area_m2, 1),
            "area_ha": round(self.area_ha, 3),
            "mean_suitability_score": round(self.mean_suitability, 1),
            "peak_suitability_score": round(self.max_suitability, 1),
            "composite_mcdm_score": round(self.composite_mcdm_score, 1),
            "elevation_meters": {
                "mean": round(self.mean_elevation, 2),
                "min": round(self.min_elevation, 2),
                "max": round(self.max_elevation, 2),
            },
            "slope_degrees": round(self.mean_slope_deg, 2),
            "slope_percent": round(self.mean_slope_pct, 2),
            "storage_metrics": {
                "storage_capacity_m3": round(self.storage_capacity_m3, 1),
                "cut_volume_m3": round(self.cut_volume_m3, 1),
                "storage_efficiency_ratio": round(self.storage_efficiency_ratio, 2),
                "stage_storage_curve": self.stage_storage_curve,
            },
            "hydrology_metrics": {
                "mean_twi": round(self.mean_twi, 2),
            },
            "shape_metrics": {
                "elongation_ratio": round(self.elongation_ratio, 2),
                "major_axis_m": round(self.major_axis_m, 1),
                "minor_axis_m": round(self.minor_axis_m, 1),
                "inscribed_width_m": round(self.inscribed_width_m, 1),
            },
            "cell_count": self.cell_count,
        }
        boundary_geojson = self.to_boundary_geojson_dict()
        if boundary_geojson:
            d["boundary_geojson"] = boundary_geojson
        return d


@dataclass
class PondSitingResult:
    """
    Result container holding the collection of ranked pond candidate sites and labeled raster.
    """
    candidates: List[PondSiteCandidate] = field(default_factory=list)
    labeled_raster: np.ndarray = field(default_factory=lambda: np.zeros((0, 0), dtype=int))
    dem_data: Optional[DEMData] = None
    total_candidates_found: int = 0
    rejected_elongated_count: int = 0
    rejected_narrow_count: int = 0
    notes: List[str] = field(default_factory=list)

    @property
    def top_candidate(self) -> Optional[PondSiteCandidate]:
        """Return the highest-ranked (#1) candidate site, or None if none found."""
        return self.candidates[0] if self.candidates else None


class PondSiteService:
    """
    Service for extracting, evaluating, and ranking suitable farm pond sites.
    """

    def __init__(self):
        pass

    def compute_stage_storage_curve(
        self,
        dem_arr: np.ndarray,
        r_indices: np.ndarray,
        c_indices: np.ndarray,
        cell_area_m2: float,
        design_depth_m: float = 2.0,
        num_stages: int = 5,
    ) -> Tuple[float, float, float, List[Dict[str, float]]]:
        """
        Compute stage-storage-area (H-A-V) depth increments and cut-fill earthwork volume.

        Returns:
            Tuple[float, float, float, List[Dict[str, float]]]:
                (storage_capacity_m3, cut_volume_m3, storage_efficiency_ratio, stage_storage_curve)
        """
        region_elevs = dem_arr[r_indices, c_indices]
        min_elev = float(np.min(region_elevs))
        mean_elev = float(np.mean(region_elevs))
        max_elev = float(np.max(region_elevs))
        natural_relief = max(0.2, max_elev - min_elev)

        # 1. Discrete stage-storage increments (0.5m increments up to max depth)
        depth_steps = np.linspace(0.5, max(design_depth_m, natural_relief + 0.5), num_stages)
        curve = []
        for d in depth_steps:
            d_val = float(round(d, 2))
            water_level = min_elev + d_val
            submerged = region_elevs <= water_level
            submerged_count = int(np.count_nonzero(submerged))
            submerged_area = float(round(submerged_count * cell_area_m2, 1))
            water_depths = np.maximum(0.0, water_level - region_elevs[submerged])
            vol_m3 = float(round(np.sum(water_depths) * cell_area_m2, 1))
            curve.append({
                "depth_m": d_val,
                "surface_area_m2": submerged_area,
                "volume_m3": vol_m3,
            })

        # 2. Design storage capacity at design_depth_m
        water_level_design = min_elev + design_depth_m
        depths_design = np.maximum(0.0, water_level_design - region_elevs)
        natural_hollow_vol = float(np.sum(depths_design) * cell_area_m2)
        pond_area_m2 = len(region_elevs) * cell_area_m2
        storage_capacity_m3 = float(round(max(natural_hollow_vol, pond_area_m2 * design_depth_m * 0.75), 1))

        # 3. Excavation Cut Volume
        cut_depth_needed = np.maximum(0.0, (mean_elev - region_elevs) + design_depth_m * 0.5)
        cut_volume_m3 = float(round(np.sum(cut_depth_needed) * cell_area_m2, 1))
        cut_volume_m3 = max(10.0, cut_volume_m3)

        # 4. Storage-to-Excavation Efficiency Ratio
        storage_efficiency_ratio = float(round(storage_capacity_m3 / cut_volume_m3, 2))

        return storage_capacity_m3, cut_volume_m3, storage_efficiency_ratio, curve

    def identify_candidate_sites(
        self,
        analysis_result: TerrainAnalysisResult,
        min_suitability_threshold: float = 60.0,
        min_area_m2: float = 200.0,
        max_area_m2: Optional[float] = None,
        max_slope_deg: Optional[float] = None,
        max_elongation_ratio: Optional[float] = 3.5,
        min_width_m: Optional[float] = None,
        pond_design_depth_m: float = 2.0,
        top_n: Optional[int] = None,
    ) -> PondSitingResult:
        """
        Identify and rank candidate pond sites from terrain suitability raster.

        Filters candidate regions by area, slope, elongation aspect ratio (to exclude
        linear roads and drainage corridors), and minimum usable excavation width.

        Args:
            analysis_result (TerrainAnalysisResult): Terrain analysis output.
            min_suitability_threshold (float): Minimum score (0-100) for candidate cells.
            min_area_m2 (float): Minimum contiguous footprint in square meters (default 200m²).
            max_area_m2 (Optional[float]): Maximum contiguous area in square meters.
            max_slope_deg (Optional[float]): Hard upper limit on slope angle (degrees).
            max_elongation_ratio (Optional[float]): Maximum allowable major-to-minor axis ratio (defaults to 3.5).
                Rejects long narrow linear corridors such as roads, ditches, and pathways.
            min_width_m (Optional[float]): Minimum allowable region width in meters across its minor axis
                and inscribed circle. If None, derived adaptively from DEM grid resolution.
            top_n (Optional[int]): Maximum number of candidates to return (None for all).

        Returns:
            PondSitingResult: Ranked candidates with real-world coordinates and metrics.
        """
        dem_data = analysis_result.dem_data
        suitability = analysis_result.suitability_score
        slope_deg = analysis_result.slope_degrees
        slope_pct = analysis_result.slope_percent
        dem_arr = dem_data.array

        # Compute cell dimensions in meters from affine transform
        dx = abs(dem_data.transform.a) if hasattr(dem_data.transform, "a") else dem_data.resolution
        dy = abs(dem_data.transform.e) if hasattr(dem_data.transform, "e") else dem_data.resolution
        if dx <= 0 or dy <= 0:
            dx = dy = dem_data.resolution
        cell_area_m2 = dx * dy

        # Determine effective minimum width threshold derived from DEM cell size
        effective_min_width_m = min_width_m
        if effective_min_width_m is None or effective_min_width_m <= 0:
            effective_min_width_m = max(10.0, 2.0 * min(dx, dy))

        # 1. Binary masking of suitable cells
        mask = suitability >= min_suitability_threshold
        if max_slope_deg is not None:
            mask = mask & (slope_deg <= max_slope_deg)

        if not np.any(mask):
            logger.warning("No cells met the minimum suitability threshold (>= %.1f).", min_suitability_threshold)
            return PondSitingResult(
                candidates=[],
                labeled_raster=np.zeros(suitability.shape, dtype=int),
                dem_data=dem_data,
                total_candidates_found=0,
            )

        # 2. Connected component labeling (8-connectivity)
        structure_8 = np.ones((3, 3), dtype=int)
        labeled_array, num_features = ndi.label(mask, structure=structure_8)

        logger.info("Found %d raw contiguous suitable regions before shape and size filtering.", num_features)

        # Transformer to convert UTM coordinates to WGS84 (Lat, Lon)
        transformer = Transformer.from_crs(dem_data.crs, "EPSG:4326", always_xy=True)

        raw_candidates: List[PondSiteCandidate] = []
        rejected_elongated = 0
        rejected_narrow = 0
        siting_notes: List[str] = []

        # 3. Analyze each connected region
        for region_id in range(1, num_features + 1):
            r_indices, c_indices = np.where(labeled_array == region_id)
            cell_count = len(r_indices)
            region_area_m2 = cell_count * cell_area_m2

            # Filter by area constraints
            if region_area_m2 < min_area_m2:
                continue
            if max_area_m2 is not None and region_area_m2 > max_area_m2:
                continue

            # Compute shape morphometrics (Major / Minor axis, Elongation, Inscribed Width)
            y_m = r_indices * dy
            x_m = c_indices * dx
            cy_m = float(np.mean(y_m))
            cx_m = float(np.mean(x_m))
            yc = y_m - cy_m
            xc = x_m - cx_m

            # Second central moments with continuous cell variance correction
            mu_yy = float(np.mean(yc ** 2) + (dy ** 2) / 12.0)
            mu_xx = float(np.mean(xc ** 2) + (dx ** 2) / 12.0)
            mu_yx = float(np.mean(yc * xc))

            trace = mu_yy + mu_xx
            det = mu_yy * mu_xx - mu_yx ** 2
            discriminant = max(0.0, trace ** 2 - 4.0 * det)
            sqrt_disc = np.sqrt(discriminant)
            lambda1 = (trace + sqrt_disc) / 2.0
            lambda2 = max(1e-6, (trace - sqrt_disc) / 2.0)

            major_axis_m = float(4.0 * np.sqrt(max(lambda1, 1e-6)))
            minor_axis_m = float(4.0 * np.sqrt(max(lambda2, 1e-6)))
            elongation_ratio = float(major_axis_m / max(minor_axis_m, 1e-6))

            # Inscribed diameter via padded distance transform
            r_min, r_max = int(np.min(r_indices)), int(np.max(r_indices)) + 1
            c_min, c_max = int(np.min(c_indices)), int(np.max(c_indices)) + 1
            sub_mask = (labeled_array[r_min:r_max, c_min:c_max] == region_id)
            padded_mask = np.pad(sub_mask, 1, mode="constant", constant_values=False)
            dist_map = ndi.distance_transform_edt(padded_mask, sampling=(dy, dx))
            inscribed_width_m = float(2.0 * np.max(dist_map))

            # Filter out linear corridors (roads, paths, drainage lines)
            if max_elongation_ratio is not None and elongation_ratio > max_elongation_ratio:
                logger.debug(
                    "Region %d rejected: elongation ratio %.2f > max %.2f (linear road/corridor shape).",
                    region_id,
                    elongation_ratio,
                    max_elongation_ratio,
                )
                rejected_elongated += 1
                continue

            # Filter out regions with inadequate excavation width
            if effective_min_width_m is not None and min(minor_axis_m, inscribed_width_m) < effective_min_width_m:
                logger.debug(
                    "Region %d rejected: width (minor: %.1fm, inscribed: %.1fm) < min threshold %.1fm.",
                    region_id,
                    minor_axis_m,
                    inscribed_width_m,
                    effective_min_width_m,
                )
                rejected_narrow += 1
                continue

            region_suitability = suitability[r_indices, c_indices]
            region_elevations = dem_arr[r_indices, c_indices]
            region_slopes = slope_deg[r_indices, c_indices]
            region_slopes_pct = slope_pct[r_indices, c_indices]

            # Weighted centroid (weighted by suitability score)
            weights = np.maximum(0.1, region_suitability - min_suitability_threshold + 1.0)
            center_row = float(np.average(r_indices, weights=weights))
            center_col = float(np.average(c_indices, weights=weights))

            # Transform raster coordinates to UTM meters (cell centers)
            utm_x, utm_y = rowcol_to_utm(dem_data.transform, center_row, center_col, offset="center")

            # Transform UTM to Geographic WGS84
            lon, lat = transformer.transform(utm_x, utm_y)

            # Vectorize suitability region mask into UTM and WGS84 polygons
            region_mask = (labeled_array == region_id)
            poly_utm = vectorize_mask_to_polygon(region_mask, dem_data.transform)
            poly_wgs84 = reproject_geometry(poly_utm, dem_data.crs, "EPSG:4326")

            mean_suit = float(np.mean(region_suitability))
            max_suit = float(np.max(region_suitability))

            # Stage-Storage and Earthwork Excavation Metrics
            storage_cap_m3, cut_vol_m3, storage_eff_ratio, stage_curve = self.compute_stage_storage_curve(
                dem_arr=dem_arr,
                r_indices=r_indices,
                c_indices=c_indices,
                cell_area_m2=cell_area_m2,
                design_depth_m=pond_design_depth_m,
            )

            # Topographic Wetness Index (TWI) across site
            if analysis_result.twi is not None:
                site_mean_twi = float(np.mean(analysis_result.twi[r_indices, c_indices]))
            else:
                site_mean_twi = 0.0

            # Multi-Criteria Decision Making (MCDM) Composite Score [0 - 100]:
            # - Suitability score (35%)
            # - Peak suitability (15%)
            # - Compactness / Aspect ratio (20%)
            # - Storage efficiency (15%)
            # - Topographic Wetness (15%)
            compactness_score = float(np.clip((1.0 / max(1.0, elongation_ratio)) * 100.0, 0.0, 100.0))
            storage_eff_score = float(np.clip(storage_eff_ratio * 50.0, 0.0, 100.0))
            twi_score_val = float(np.mean(analysis_result.twi_score[r_indices, c_indices])) if analysis_result.twi_score is not None else 50.0

            composite_mcdm = (
                0.35 * mean_suit
                + 0.15 * max_suit
                + 0.20 * compactness_score
                + 0.15 * storage_eff_score
                + 0.15 * twi_score_val
            )
            composite_mcdm = float(np.clip(composite_mcdm, 0.0, 100.0))

            candidate = PondSiteCandidate(
                rank=0,  # Assigned after sorting
                site_id="",
                utm_x=float(utm_x),
                utm_y=float(utm_y),
                longitude=float(lon),
                latitude=float(lat),
                area_m2=float(region_area_m2),
                area_ha=float(region_area_m2 / 10000.0),
                mean_suitability=mean_suit,
                max_suitability=max_suit,
                mean_elevation=float(np.mean(region_elevations)),
                min_elevation=float(np.min(region_elevations)),
                max_elevation=float(np.max(region_elevations)),
                mean_slope_deg=float(np.mean(region_slopes)),
                mean_slope_pct=float(np.mean(region_slopes_pct)),
                cell_count=int(cell_count),
                raster_centroid_row=center_row,
                raster_centroid_col=center_col,
                elongation_ratio=round(elongation_ratio, 2),
                major_axis_m=round(major_axis_m, 1),
                minor_axis_m=round(minor_axis_m, 1),
                inscribed_width_m=round(inscribed_width_m, 1),
                polygon_utm=poly_utm,
                polygon_wgs84=poly_wgs84,
                storage_capacity_m3=storage_cap_m3,
                cut_volume_m3=cut_vol_m3,
                storage_efficiency_ratio=storage_eff_ratio,
                mean_twi=site_mean_twi,
                stage_storage_curve=stage_curve,
                composite_mcdm_score=composite_mcdm,
            )
            raw_candidates.append(candidate)

        if rejected_elongated > 0:
            siting_notes.append(
                f"Filtered out {rejected_elongated} linear candidate region(s) exceeding max elongation ratio "
                f"({max_elongation_ratio:.1f}) as road/corridor shapes."
            )
        if rejected_narrow > 0:
            siting_notes.append(
                f"Filtered out {rejected_narrow} narrow candidate region(s) below minimum width threshold "
                f"({effective_min_width_m:.1f}m)."
            )

        # 4. Rank candidates by composite score: 70% mean suitability + 30% peak suitability (and tie-breaking by area)
        raw_candidates.sort(
            key=lambda c: (c.composite_mcdm_score * 0.5 + (c.mean_suitability * 0.7 + c.max_suitability * 0.3) * 0.5, c.area_m2),
            reverse=True,
        )

        # Assign ranks and IDs
        final_candidates: List[PondSiteCandidate] = []
        for idx, cand in enumerate(raw_candidates, start=1):
            cand.rank = idx
            cand.site_id = f"site_{idx}"
            final_candidates.append(cand)
            if top_n is not None and idx >= top_n:
                break

        logger.info(
            "Identified %d qualified candidate pond sites (Top site #1: Suitability=%.1f, Area=%.1fm², Elongation=%.2f, Rejected: %d elongated, %d narrow)",
            len(final_candidates),
            final_candidates[0].mean_suitability if final_candidates else 0.0,
            final_candidates[0].area_m2 if final_candidates else 0.0,
            final_candidates[0].elongation_ratio if final_candidates else 0.0,
            rejected_elongated,
            rejected_narrow,
        )

        return PondSitingResult(
            candidates=final_candidates,
            labeled_raster=labeled_array,
            dem_data=dem_data,
            total_candidates_found=len(final_candidates),
            rejected_elongated_count=rejected_elongated,
            rejected_narrow_count=rejected_narrow,
            notes=siting_notes,
        )

    def save_candidate_sites_visualization(
        self,
        siting_result: PondSitingResult,
        analysis_result: TerrainAnalysisResult,
        output_path: Union[str, Path],
        max_labels_to_show: int = 5,
    ) -> Path:
        """
        Generate and save a high-resolution visual plot of candidate pond locations
        overlaid on the suitability raster and shaded terrain relief.
        """
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import LightSource

        path = Path(output_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        dem_data = analysis_result.dem_data
        minx, miny, maxx, maxy = dem_data.bounds
        extent = [minx, maxx, miny, maxy]

        fig, ax = plt.subplots(figsize=(12, 10), constrained_layout=True)

        # Background: Shaded Relief blended with Suitability Heatmap
        ls = LightSource(azdeg=315, altdeg=45)
        shaded_suitability = ls.shade(
            analysis_result.suitability_score,
            cmap=plt.cm.viridis,
            blend_mode="overlay",
            vert_exag=1.2,
            dx=dem_data.resolution,
            dy=dem_data.resolution,
        )

        im = ax.imshow(shaded_suitability, extent=extent, origin="upper")
        cbar = fig.colorbar(
            plt.cm.ScalarMappable(
                norm=plt.Normalize(vmin=0, vmax=100), cmap=plt.cm.viridis
            ),
            ax=ax,
            fraction=0.046,
            pad=0.04,
        )
        cbar.set_label("Terrain Suitability Score (0-100)", fontsize=11, fontweight="bold")

        # Mark candidate pond sites
        candidates = siting_result.candidates[:max_labels_to_show]
        colors = ["#FF2D55", "#FF9500", "#FFCC00", "#34C759", "#007AFF"]

        for i, cand in enumerate(candidates):
            color = colors[i % len(colors)]
            is_top = (cand.rank == 1)

            # Marker
            marker_style = "*" if is_top else "o"
            marker_size = 180 if is_top else 100

            ax.scatter(
                cand.utm_x,
                cand.utm_y,
                marker=marker_style,
                s=marker_size,
                color=color,
                edgecolors="white",
                linewidths=1.5,
                zorder=10,
                label=f"Rank #{cand.rank} ({cand.site_id})",
            )

            # Annotation text box
            label_text = (
                f"#{cand.rank} {cand.site_id.upper()}\n"
                f"Score: {cand.mean_suitability:.1f}\n"
                f"Area: {cand.area_m2:.0f}m²\n"
                f"Elev: {cand.mean_elevation:.1f}m\n"
                f"Slope: {cand.mean_slope_deg:.1f}°"
            )

            ax.annotate(
                label_text,
                xy=(cand.utm_x, cand.utm_y),
                xytext=(15, 15),
                textcoords="offset points",
                bbox=dict(boxstyle="round,pad=0.4", fc="black", ec=color, lw=1.5, alpha=0.85),
                fontsize=9,
                fontweight="bold",
                color="white",
                arrowprops=dict(arrowstyle="->", connectionstyle="arc3,rad=0.2", color=color, lw=1.5),
                zorder=12,
            )

        ax.set_title(
            f"Optimal Farm Pond Siting Analysis — {len(siting_result.candidates)} Candidate Sites Identified\n"
            f"Top Site Centroid: {siting_result.top_candidate.latitude:.5f}°N, {siting_result.top_candidate.longitude:.5f}°E"
            if siting_result.top_candidate else "No Candidate Sites Found",
            fontsize=13,
            fontweight="bold",
        )
        ax.set_xlabel("UTM Easting (m)", fontsize=10)
        ax.set_ylabel("UTM Northing (m)", fontsize=10)
        ax.grid(True, linestyle="--", alpha=0.3)

        if candidates:
            ax.legend(loc="upper right", framealpha=0.9)

        plt.savefig(path, dpi=200, bbox_inches="tight")
        plt.close(fig)

        logger.info("Saved candidate pond sites visualization to %s", path)
        return path


# Convenience function
def find_candidate_pond_sites(
    analysis_result: TerrainAnalysisResult,
    min_suitability_threshold: float = 60.0,
    min_area_m2: float = 200.0,
    max_slope_deg: Optional[float] = None,
    max_elongation_ratio: Optional[float] = 3.5,
    min_width_m: Optional[float] = None,
    top_n: Optional[int] = 5,
) -> PondSitingResult:
    """Convenience helper to extract ranked candidate pond sites."""
    service = PondSiteService()
    return service.identify_candidate_sites(
        analysis_result=analysis_result,
        min_suitability_threshold=min_suitability_threshold,
        min_area_m2=min_area_m2,
        max_slope_deg=max_slope_deg,
        max_elongation_ratio=max_elongation_ratio,
        min_width_m=min_width_m,
        top_n=top_n,
    )

