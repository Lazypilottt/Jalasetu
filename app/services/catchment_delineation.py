"""
Catchment / Watershed Delineation Service.

Responsibility:
- Delineate upstream contributing drainage areas (catchment/watershed) for a target pour point.
- Hydrological routing using D8 flow direction and flow accumulation.
- Support pysheds when available, with a robust native D8 BFS reverse flow-routing fallback.
- Snapping pour points to high-accumulation drainage channels within a configurable search radius.
- Vectorizing catchment raster masks into Shapely/GeoJSON polygons via rasterio.features.shapes.
- Computing exact watershed morphometrics: area (m² & ha), elevation range, and mean basin slope.
- Exporting GeoJSON boundary geometries and multi-panel overlay visualizations.
"""

import collections
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from pyproj import Transformer
import rasterio.features
from shapely.geometry import Polygon, MultiPolygon, Point, shape, mapping
from shapely.ops import unary_union, transform as shapely_transform

from app.services.dem_builder import DEMData
from app.services.terrain_analysis import TerrainAnalysisResult, TerrainAnalysisService
from app.services.pond_site import PondSiteCandidate
from app.utils.geometry import (
    rowcol_to_utm,
    utm_to_rowcol,
    vectorize_mask_to_polygon,
    reproject_geometry,
)

logger = logging.getLogger(__name__)

# Try importing pysheds
try:
    from pysheds.grid import Grid
    HAS_PYSHEDS = True
except ImportError:
    HAS_PYSHEDS = False

# D8 8-neighbor directional offsets (d_row, d_col)
# Index: 0:East, 1:NorthEast, 2:North, 3:NorthWest, 4:West, 5:SouthWest, 6:South, 7:SouthEast
D8_OFFSETS = [
    (0, 1),    # 0: East
    (-1, 1),   # 1: North-East
    (-1, 0),   # 2: North
    (-1, -1),  # 3: North-West
    (0, -1),   # 4: West
    (1, -1),   # 5: South-West
    (1, 0),    # 6: South
    (1, 1),    # 7: South-East
]


@dataclass
class CatchmentResult:
    """
    Result container holding the delineated catchment boundary, metrics, and raster masks.
    """
    pour_point_utm: Tuple[float, float]
    pour_point_wgs84: Tuple[float, float]
    snapped_pour_point_utm: Tuple[float, float]
    snapped_pour_point_wgs84: Tuple[float, float]
    area_m2: float
    area_ha: float
    cell_count: int
    mean_elevation: float
    min_elevation: float
    max_elevation: float
    elevation_span: float
    mean_slope_deg: float
    mean_slope_pct: float
    catchment_mask: np.ndarray
    flow_accumulation: Optional[np.ndarray]
    flow_direction: Optional[np.ndarray]
    polygon_utm: Union[Polygon, MultiPolygon]
    polygon_wgs84: Union[Polygon, MultiPolygon]
    method_used: str  # 'flow_accumulation' (pysheds) or 'basin_approximation' (native D8 BFS)
    dem_data: DEMData
    scs_runoff: Optional[Dict[str, Any]] = None
    feasibility: Optional[Dict[str, Any]] = None
    erosion_metrics: Optional[Dict[str, Any]] = None

    def to_geojson_dict(self) -> Dict[str, Any]:
        """Convert catchment boundary and properties to GeoJSON FeatureCollection."""
        geom_dict = mapping(self.polygon_wgs84)
        props: Dict[str, Any] = {
            "delineation_method": self.method_used,
            "area_m2": round(self.area_m2, 1),
            "area_ha": round(self.area_ha, 3),
            "cell_count": self.cell_count,
            "elevation_meters": {
                "min": round(self.min_elevation, 2),
                "max": round(self.max_elevation, 2),
                "mean": round(self.mean_elevation, 2),
                "relief_span": round(self.elevation_span, 2),
            },
            "mean_slope_degrees": round(self.mean_slope_deg, 2),
            "mean_slope_percent": round(self.mean_slope_pct, 2),
            "pour_point": {
                "input_wgs84": [round(self.pour_point_wgs84[1], 6), round(self.pour_point_wgs84[0], 6)],
                "snapped_wgs84": [round(self.snapped_pour_point_wgs84[1], 6), round(self.snapped_pour_point_wgs84[0], 6)],
                "input_utm": [round(self.pour_point_utm[0], 2), round(self.pour_point_utm[1], 2)],
                "snapped_utm": [round(self.snapped_pour_point_utm[0], 2), round(self.snapped_pour_point_utm[1], 2)],
            },
        }
        if self.scs_runoff:
            props["scs_runoff_modeling"] = self.scs_runoff
        if self.feasibility:
            props["hydrological_feasibility"] = self.feasibility
        if self.erosion_metrics:
            props["soil_erosion_metrics"] = self.erosion_metrics

        feature = {
            "type": "Feature",
            "geometry": geom_dict,
            "properties": props,
        }
        return {
            "type": "FeatureCollection",
            "features": [feature],
        }


# =====================================================================
# Native D8 Hydrological Engine (Robust Fallback)
# =====================================================================

def compute_native_d8_flow_direction(
    dem_arr: np.ndarray,
    dx: float,
    dy: float,
) -> np.ndarray:
    """
    Compute D8 steepest descent flow direction grid.
    Returns:
        np.ndarray: Integer array with indices 0..7 pointing to steepest downslope neighbor,
                    or -1 for local pits/sinks.
    """
    rows, cols = dem_arr.shape
    fdir = np.full((rows, cols), -1, dtype=np.int8)
    max_gradient = np.zeros((rows, cols), dtype=np.float64)

    diag_dist = np.sqrt(dx * dx + dy * dy)
    dist_map = [dx, diag_dist, dy, diag_dist, dx, diag_dist, dy, diag_dist]

    for k, (dr, dc) in enumerate(D8_OFFSETS):
        dist = dist_map[k]

        r_src_start = max(0, -dr)
        r_src_end = rows - max(0, dr)
        c_src_start = max(0, -dc)
        c_src_end = cols - max(0, dc)

        r_dst_start = max(0, dr)
        r_dst_end = rows - max(0, -dr)
        c_dst_start = max(0, dc)
        c_dst_end = cols - max(0, -dc)

        diff = dem_arr[r_src_start:r_src_end, c_src_start:c_src_end] - dem_arr[r_dst_start:r_dst_end, c_dst_start:c_dst_end]
        gradient = diff / dist

        sub_max_grad = max_gradient[r_src_start:r_src_end, c_src_start:c_src_end]
        sub_fdir = fdir[r_src_start:r_src_end, c_src_start:c_src_end]

        better_mask = (gradient > sub_max_grad) & (gradient > 0)
        sub_max_grad[better_mask] = gradient[better_mask]
        sub_fdir[better_mask] = k

    return fdir


def compute_native_d8_flow_accumulation(fdir: np.ndarray) -> np.ndarray:
    """
    Compute total contributing cell accumulation from D8 flow direction matrix.
    Uses in-degree topological sorting for linear O(N) complexity without recursion depth limits.
    """
    rows, cols = fdir.shape
    in_degree = np.zeros((rows, cols), dtype=np.int32)

    # 1. Count incoming flow edges for each cell
    for r in range(rows):
        for c in range(cols):
            k = fdir[r, c]
            if k >= 0:
                dr, dc = D8_OFFSETS[k]
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    in_degree[nr, nc] += 1

    # 2. Queue all headwater cells (in_degree == 0)
    queue = collections.deque()
    for r in range(rows):
        for c in range(cols):
            if in_degree[r, c] == 0:
                queue.append((r, c))

    # 3. Accumulate flow (each cell starts with its own weight of 1)
    accum = np.ones((rows, cols), dtype=np.float64)

    while queue:
        r, c = queue.popleft()
        k = fdir[r, c]
        if k >= 0:
            dr, dc = D8_OFFSETS[k]
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols:
                accum[nr, nc] += accum[r, c]
                in_degree[nr, nc] -= 1
                if in_degree[nr, nc] == 0:
                    queue.append((nr, nc))

    return accum


def delineate_catchment_d8_bfs(
    fdir: np.ndarray,
    pour_row: int,
    pour_col: int,
    dem_arr: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Trace upstream contributing watershed from a pour point cell via reverse-flow BFS.
    """
    rows, cols = fdir.shape
    catchment_mask = np.zeros((rows, cols), dtype=bool)

    if not (0 <= pour_row < rows and 0 <= pour_col < cols):
        return catchment_mask

    queue = collections.deque([(pour_row, pour_col)])
    catchment_mask[pour_row, pour_col] = True

    while queue:
        cr, cc = queue.popleft()

        # Check all 8 incoming neighbors
        for k, (dr, dc) in enumerate(D8_OFFSETS):
            nr, nc = cr + dr, cc + dc
            if 0 <= nr < rows and 0 <= nc < cols and not catchment_mask[nr, nc]:
                neighbor_k = fdir[nr, nc]
                if neighbor_k >= 0:
                    ndr, ndc = D8_OFFSETS[neighbor_k]
                    if (nr + ndr == cr) and (nc + ndc == cc):
                        catchment_mask[nr, nc] = True
                        queue.append((nr, nc))

    return catchment_mask


def snap_pour_point_to_stream(
    row: int,
    col: int,
    accum: np.ndarray,
    search_radius_cells: int = 5,
) -> Tuple[int, int]:
    """
    Snap candidate pour point to the local highest-flow-accumulation cell
    within a neighborhood window.
    """
    rows, cols = accum.shape
    r_min = max(0, row - search_radius_cells)
    r_max = min(rows, row + search_radius_cells + 1)
    c_min = max(0, col - search_radius_cells)
    c_max = min(cols, col + search_radius_cells + 1)

    sub_accum = accum[r_min:r_max, c_min:c_max]
    sub_max_idx = np.unravel_index(np.argmax(sub_accum), sub_accum.shape)

    snapped_row = r_min + sub_max_idx[0]
    snapped_col = c_min + sub_max_idx[1]
    return int(snapped_row), int(snapped_col)


def vectorize_mask_to_polygon(
    mask: np.ndarray,
    transform: rasterio.Affine,
) -> Union[Polygon, MultiPolygon]:
    """
    Vectorize a binary raster mask into a clean Shapely Polygon or MultiPolygon.
    """
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


def compute_scs_cn_runoff(
    catchment_area_m2: float,
    design_rainfall_mm: float = 100.0,
    curve_number: float = 75.0,
) -> Dict[str, Any]:
    """
    Estimate total watershed storm runoff volume using the USDA SCS-CN (Curve Number) method.

    Formulas:
        S = (25400 / CN) - 254 (Potential maximum soil moisture retention in mm)
        Ia = 0.2 * S (Initial abstraction before ponding in mm)
        Q = (P - Ia)^2 / (P - Ia + S) (Runoff depth in mm for P > Ia)
        V_runoff = (Q / 1000) * Area_m2 (Total storm runoff yield in m³)
    """
    cn = float(np.clip(curve_number, 30.0, 98.0))
    p = float(max(0.0, design_rainfall_mm))

    s_mm = float((25400.0 / cn) - 254.0)
    ia_mm = float(0.2 * s_mm)

    if p > ia_mm:
        q_mm = float(((p - ia_mm) ** 2) / (p - ia_mm + s_mm))
    else:
        q_mm = 0.0

    runoff_vol_m3 = float((q_mm / 1000.0) * catchment_area_m2)
    runoff_coeff = float(q_mm / p) if p > 0 else 0.0

    return {
        "design_rainfall_mm": round(p, 1),
        "curve_number": round(cn, 1),
        "potential_retention_mm": round(s_mm, 1),
        "initial_abstraction_mm": round(ia_mm, 1),
        "runoff_depth_mm": round(q_mm, 1),
        "estimated_runoff_volume_m3": round(runoff_vol_m3, 1),
        "runoff_coefficient": round(runoff_coeff, 3),
    }


def evaluate_catchment_to_pond_feasibility(
    catchment_area_m2: float,
    pond_area_m2: float,
    runoff_volume_m3: float,
    pond_storage_m3: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Evaluate hydrological sizing and catchment-to-pond area ratio.
    """
    eff_pond_area = max(1.0, pond_area_m2)
    ratio = float(catchment_area_m2 / eff_pond_area)

    if 10.0 <= ratio <= 50.0:
        status = "optimal"
        explanation = (
            f"Optimal catchment-to-pond area ratio ({ratio:.1f}x). "
            "Generates reliable monsoon runoff to fill the pond without high risk of bank breaches."
        )
    elif ratio < 10.0:
        status = "low_yield_risk"
        explanation = (
            f"Catchment-to-pond area ratio ({ratio:.1f}x) is below the recommended 10x minimum. "
            "Rainfall runoff may be insufficient during dry seasons; supplementary contour diversion drains recommended."
        )
    else:
        status = "high_flow_excess"
        explanation = (
            f"Catchment-to-pond area ratio ({ratio:.1f}x) is large (>50x). "
            "Generates substantial storm runoff; a masonry spillway or emergency bypass chute is essential to prevent embankment overtopping."
        )

    target_vol = pond_storage_m3 if (pond_storage_m3 and pond_storage_m3 > 0) else (eff_pond_area * 2.0)
    filling_factor = float(round(runoff_volume_m3 / target_vol, 2))

    return {
        "catchment_to_pond_ratio": round(ratio, 1),
        "hydrological_feasibility": status,
        "feasibility_explanation": explanation,
        "water_filling_factor": filling_factor,
    }


def compute_rusle_ls_factor(
    flow_accum: np.ndarray,
    slope_deg: np.ndarray,
    dx: float,
    catchment_mask: Optional[np.ndarray] = None,
) -> Tuple[float, str, str]:
    """
    Compute RUSLE topographic LS erosion factor and classify catchment siltation risk.
    """
    upslope_m = np.maximum(1.0, flow_accum * dx)
    slope_rad = np.radians(np.clip(slope_deg, 0.1, 60.0))
    sin_slope = np.maximum(0.001, np.sin(slope_rad))

    ls_grid = np.power(upslope_m / 22.13, 0.4) * np.power(sin_slope / 0.0896, 1.3)
    ls_grid = np.clip(ls_grid, 0.0, 50.0)

    if catchment_mask is not None and np.any(catchment_mask):
        mean_ls = float(np.mean(ls_grid[catchment_mask]))
    else:
        mean_ls = float(np.mean(ls_grid))

    if mean_ls < 2.5:
        risk = "low"
        explanation = "Low upstream soil erosion & siltation risk; gentle catchment slopes promote clean runoff."
    elif mean_ls <= 6.0:
        risk = "moderate"
        explanation = "Moderate siltation risk; a vegetative grass inlet buffer or basic silt trap is recommended."
    else:
        risk = "high"
        explanation = "High upstream soil erosion risk due to steep slopes; upstream contour bunds and desilting basins recommended."

    return float(round(mean_ls, 2)), risk, explanation


class CatchmentDelineationService:
    """
    Service for delineating contributing catchments/watersheds for candidate pond sites.
    """

    def __init__(self):
        pass

    def delineate(
        self,
        dem_data: DEMData,
        pour_point: Union[Tuple[float, float], PondSiteCandidate],
        is_wgs84_coords: bool = False,
        snap_radius_meters: float = 25.0,
        use_pysheds_if_available: bool = True,
        design_rainfall_mm: float = 100.0,
        curve_number: float = 75.0,
        pond_area_m2: Optional[float] = None,
        pond_storage_m3: Optional[float] = None,
    ) -> CatchmentResult:
        """
        Delineate catchment boundary draining to the specified pour point.

        Args:
            dem_data (DEMData): Input DEM object.
            pour_point (Union[Tuple[float, float], PondSiteCandidate]): Target point.
                Either (x, y), (lat, lon if is_wgs84_coords=True), or PondSiteCandidate.
            is_wgs84_coords (bool): Set True if pour_point is passed as (lat, lon).
            snap_radius_meters (float): Search radius in meters to snap pour point to stream channel.
            use_pysheds_if_available (bool): Try pysheds first if installed.
            design_rainfall_mm (float): 24-hr design storm rainfall in mm (default 100.0mm).
            curve_number (float): SCS Runoff Curve Number (default 75.0).
            pond_area_m2 (Optional[float]): Pond footprint area for ratio checks.
            pond_storage_m3 (Optional[float]): Pond storage volume for filling factor.

        Returns:
            CatchmentResult: Delineated catchment polygon, area, slope, elevation, and hydrology metrics.
        """
        # 1. Resolve pour point coordinates (UTM and WGS84)
        transformer_to_wgs84 = Transformer.from_crs(dem_data.crs, "EPSG:4326", always_xy=True)
        transformer_to_utm = Transformer.from_crs("EPSG:4326", dem_data.crs, always_xy=True)

        if isinstance(pour_point, PondSiteCandidate):
            utm_x, utm_y = pour_point.utm_x, pour_point.utm_y
            lat, lon = pour_point.latitude, pour_point.longitude
            if pond_area_m2 is None:
                pond_area_m2 = pour_point.area_m2
            if pond_storage_m3 is None:
                pond_storage_m3 = pour_point.storage_capacity_m3
        elif is_wgs84_coords:
            lat, lon = pour_point[0], pour_point[1]
            utm_x, utm_y = transformer_to_utm.transform(lon, lat)
        else:
            utm_x, utm_y = pour_point[0], pour_point[1]
            lon, lat = transformer_to_wgs84.transform(utm_x, utm_y)

        # 2. Convert UTM coordinates to raster row, col
        raw_row, raw_col = utm_to_rowcol(
            dem_data.transform, utm_x, utm_y, height=dem_data.height, width=dem_data.width
        )

        # Cell resolution & area
        dx = abs(dem_data.transform.a) if hasattr(dem_data.transform, "a") else dem_data.resolution
        dy = abs(dem_data.transform.e) if hasattr(dem_data.transform, "e") else dem_data.resolution
        cell_area_m2 = dx * dy

        search_radius_cells = max(1, int(np.round(snap_radius_meters / dem_data.resolution)))

        method_used = "basin_approximation"
        catchment_mask = None
        flow_accum = None
        flow_dir = None

        # 3. Execution via Pysheds (if enabled and installed)
        if use_pysheds_if_available and HAS_PYSHEDS:
            try:
                logger.info("Running catchment delineation using Pysheds engine...")
                from pysheds.grid import Grid
                grid = Grid.from_raster(dem_data.array, dem_data.transform, crs=dem_data.crs)
                pit_filled = grid.fill_pits(dem_data.array)
                flooded = grid.fill_depressions(pit_filled)
                inflated = grid.resolve_flats(flooded)
                
                pysheds_fdir = grid.flowdir(inflated)
                pysheds_acc = grid.accumulation(pysheds_fdir)

                # Snap pour point in pysheds
                threshold_val = max(1.0, float(np.percentile(pysheds_acc, 90)))
                stream_mask = pysheds_acc > threshold_val
                x_snap, y_snap = grid.snap_to_mask(stream_mask, (utm_x, utm_y))

                # Delineate
                catch_raw = grid.catchment(x=x_snap, y=y_snap, fdir=pysheds_fdir, xytype="coordinate")
                catchment_mask = np.asarray(catch_raw, dtype=bool)

                flow_accum = np.asarray(pysheds_acc)
                flow_dir = np.asarray(pysheds_fdir)

                snapped_row, snapped_col = utm_to_rowcol(
                    dem_data.transform, x_snap, y_snap, height=dem_data.height, width=dem_data.width
                )
                snapped_utm_x, snapped_utm_y = x_snap, y_snap

                method_used = "flow_accumulation"
                logger.info("Pysheds delineation succeeded. Cells captured: %d", np.count_nonzero(catchment_mask))
            except Exception as e:
                logger.warning("Pysheds delineation encountered error (%s). Falling back to Native D8 BFS engine.", e)
                catchment_mask = None

        # 4. Fallback Execution via Native D8 BFS Engine
        if catchment_mask is None or not np.any(catchment_mask):
            method_used = "basin_approximation"
            logger.info("Executing native D8 flow direction and accumulation routing...")

            flow_dir = compute_native_d8_flow_direction(dem_data.array, dx, dy)
            flow_accum = compute_native_d8_flow_accumulation(flow_dir)

            # Snap pour point to local high-accumulation cell
            snapped_row, snapped_col = snap_pour_point_to_stream(
                raw_row, raw_col, flow_accum, search_radius_cells=search_radius_cells
            )

            # Snapped UTM coordinates (cell center)
            snapped_utm_x, snapped_utm_y = rowcol_to_utm(
                dem_data.transform, snapped_row, snapped_col, offset="center"
            )

            # Delineate watershed mask via upstream BFS
            catchment_mask = delineate_catchment_d8_bfs(
                flow_dir, snapped_row, snapped_col, dem_arr=dem_data.array
            )

        # 5. Snapped WGS84 Coordinates
        snapped_lon, snapped_lat = transformer_to_wgs84.transform(snapped_utm_x, snapped_utm_y)

        # 6. Vectorize Catchment Mask to Polygons
        polygon_utm = vectorize_mask_to_polygon(catchment_mask, dem_data.transform)
        polygon_wgs84 = reproject_geometry(polygon_utm, dem_data.crs, "EPSG:4326")

        # 7. Compute Catchment Morphometric Metrics
        cell_count = int(np.count_nonzero(catchment_mask))
        area_m2 = float(cell_count * cell_area_m2)
        area_ha = float(area_m2 / 10000.0)

        # Compute slope within catchment
        terrain_service = TerrainAnalysisService()
        slope_deg, slope_pct = terrain_service.compute_slope(dem_data)

        in_catch_elev = dem_data.array[catchment_mask]
        in_catch_slope_deg = slope_deg[catchment_mask]
        in_catch_slope_pct = slope_pct[catchment_mask]

        if cell_count > 0:
            min_elev = float(np.min(in_catch_elev))
            max_elev = float(np.max(in_catch_elev))
            mean_elev = float(np.mean(in_catch_elev))
            elevation_span = max_elev - min_elev
            mean_slope_deg = float(np.mean(in_catch_slope_deg))
            mean_slope_pct = float(np.mean(in_catch_slope_pct))
        else:
            min_elev = max_elev = mean_elev = elevation_span = 0.0
            mean_slope_deg = mean_slope_pct = 0.0

        # 8. Advanced Hydrology & Runoff Modeling (SCS-CN, Feasibility, RUSLE LS)
        scs_runoff_data = compute_scs_cn_runoff(
            catchment_area_m2=area_m2,
            design_rainfall_mm=design_rainfall_mm,
            curve_number=curve_number,
        )

        eff_pond_area = pond_area_m2 if (pond_area_m2 and pond_area_m2 > 0) else max(200.0, area_m2 / 20.0)
        feasibility_data = evaluate_catchment_to_pond_feasibility(
            catchment_area_m2=area_m2,
            pond_area_m2=eff_pond_area,
            runoff_volume_m3=scs_runoff_data["estimated_runoff_volume_m3"],
            pond_storage_m3=pond_storage_m3,
        )

        if flow_accum is not None:
            mean_ls, silt_risk, silt_exp = compute_rusle_ls_factor(
                flow_accum=flow_accum,
                slope_deg=slope_deg,
                dx=dx,
                catchment_mask=catchment_mask,
            )
        else:
            mean_ls, silt_risk, silt_exp = 1.5, "low", "Gentle terrain gradient."

        erosion_data = {
            "mean_ls_factor": mean_ls,
            "siltation_risk": silt_risk,
            "siltation_explanation": silt_exp,
        }

        logger.info(
            "Catchment delineated successfully (%s): Area=%.1fm² (%.2f ha), Relief=[%.1fm, %.1fm], Slope=%.1f°, SCS Runoff=%.1fm³, Feasibility=%s, Siltation=%s",
            method_used,
            area_m2,
            area_ha,
            min_elev,
            max_elev,
            mean_slope_deg,
            scs_runoff_data["estimated_runoff_volume_m3"],
            feasibility_data["hydrological_feasibility"],
            silt_risk,
        )

        return CatchmentResult(
            pour_point_utm=(utm_x, utm_y),
            pour_point_wgs84=(lat, lon),
            snapped_pour_point_utm=(snapped_utm_x, snapped_utm_y),
            snapped_pour_point_wgs84=(snapped_lat, snapped_lon),
            area_m2=area_m2,
            area_ha=area_ha,
            cell_count=cell_count,
            mean_elevation=mean_elev,
            min_elevation=min_elev,
            max_elevation=max_elev,
            elevation_span=elevation_span,
            mean_slope_deg=mean_slope_deg,
            mean_slope_pct=mean_slope_pct,
            catchment_mask=catchment_mask,
            flow_accumulation=flow_accum,
            flow_direction=flow_dir,
            polygon_utm=polygon_utm,
            polygon_wgs84=polygon_wgs84,
            method_used=method_used,
            dem_data=dem_data,
            scs_runoff=scs_runoff_data,
            feasibility=feasibility_data,
            erosion_metrics=erosion_data,
        )

    def save_geojson(
        self,
        result: CatchmentResult,
        output_path: Union[str, Path],
    ) -> Path:
        """Save delineated catchment boundary as a standard GeoJSON file."""
        path = Path(output_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        geojson_data = result.to_geojson_dict()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(geojson_data, f, indent=2)

        logger.info("Saved Catchment GeoJSON to %s", path)
        return path

    def save_catchment_visualization(
        self,
        result: CatchmentResult,
        output_path: Union[str, Path],
        candidate_site: Optional[PondSiteCandidate] = None,
        title: Optional[str] = None,
    ) -> Path:
        """
        Generate and save a 2-panel visual overlay plot:
        Panel 1: DEM Hillshade + Elevation + Catchment Boundary Overlay + Snapped Pour Point Marker
        Panel 2: Stream Drainage Network (Flow Accumulation) + Catchment Boundary
        """
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import LightSource, LogNorm

        path = Path(output_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        dem_data = result.dem_data
        minx, miny, maxx, maxy = dem_data.bounds
        extent = [minx, maxx, miny, maxy]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 8), constrained_layout=True)

        # 1. Left Panel: Shaded Relief + Catchment Overlay
        ls = LightSource(azdeg=315, altdeg=45)
        rgb_blend = ls.shade(
            dem_data.array,
            cmap=plt.cm.terrain,
            blend_mode="overlay",
            vert_exag=1.5,
            dx=dem_data.resolution,
            dy=dem_data.resolution,
        )
        ax1.imshow(rgb_blend, extent=extent, origin="upper")

        # Overlay Catchment Mask with alpha shading
        catchment_overlay = np.where(result.catchment_mask, 1.0, np.nan)
        ax1.imshow(catchment_overlay, extent=extent, origin="upper", cmap="Blues_r", alpha=0.35)

        # Catchment Boundary Contour Line
        ax1.contour(
            result.catchment_mask.astype(int),
            levels=[0.5],
            colors="#0055FF",
            linewidths=2.0,
            extent=extent,
            origin="upper",
        )

        # Original Pour Point & Snapped Pour Point Markers
        ax1.scatter(
            result.pour_point_utm[0],
            result.pour_point_utm[1],
            color="red",
            marker="x",
            s=120,
            linewidths=2.5,
            label="Original Target Point",
            zorder=10,
        )
        ax1.scatter(
            result.snapped_pour_point_utm[0],
            result.snapped_pour_point_utm[1],
            color="#FFD700",
            edgecolors="black",
            marker="*",
            s=220,
            label="Snapped Stream Pour Point",
            zorder=11,
        )

        ax1.set_title(
            f"1. Delineated Catchment Boundary ({result.method_used})\n"
            f"Area: {result.area_ha:.2f} ha ({result.area_m2:,.0f} m²)",
            fontsize=13,
            fontweight="bold",
        )
        ax1.set_xlabel("UTM Easting (m)")
        ax1.set_ylabel("UTM Northing (m)")
        ax1.legend(loc="upper right", framealpha=0.9)
        ax1.grid(True, linestyle="--", alpha=0.3)

        # 2. Right Panel: Drainage Network (Flow Accumulation Log Scale)
        if result.flow_accumulation is not None:
            accum_safe = np.maximum(1.0, result.flow_accumulation)
            im2 = ax2.imshow(
                accum_safe,
                extent=extent,
                origin="upper",
                cmap="Blues",
                norm=LogNorm(vmin=1.0, vmax=float(np.max(accum_safe))),
            )
            cbar2 = fig.colorbar(im2, ax=ax2, fraction=0.046, pad=0.04)
            cbar2.set_label("Upstream Flow Accumulation (Cells)", fontsize=11, fontweight="bold")

            # Catchment Boundary on flow accumulation
            ax2.contour(
                result.catchment_mask.astype(int),
                levels=[0.5],
                colors="red",
                linewidths=1.8,
                extent=extent,
                origin="upper",
            )
            ax2.scatter(
                result.snapped_pour_point_utm[0],
                result.snapped_pour_point_utm[1],
                color="red",
                marker="o",
                s=80,
                edgecolors="white",
                label="Catchment Outlet",
                zorder=10,
            )

        ax2.set_title(
            f"2. Upstream Drainage Flow Network\n"
            f"Elevation Range: {result.min_elevation:.1f}m - {result.max_elevation:.1f}m (Relief: {result.elevation_span:.1f}m)",
            fontsize=13,
            fontweight="bold",
        )
        ax2.set_xlabel("UTM Easting (m)")
        ax2.set_ylabel("UTM Northing (m)")
        ax2.legend(loc="upper right", framealpha=0.9)
        ax2.grid(True, linestyle="--", alpha=0.3)

        fig_title = title or (
            f"Catchment Delineation Summary — Area: {result.area_ha:.2f} ha | "
            f"Mean Basin Slope: {result.mean_slope_deg:.1f}° ({dem_data.crs})"
        )
        fig.suptitle(fig_title, fontsize=15, fontweight="bold")

        plt.savefig(path, dpi=200, bbox_inches="tight")
        plt.close(fig)

        logger.info("Saved Catchment Visualization PNG to %s", path)
        return path


# Convenience function
def delineate_catchment(
    dem_data: DEMData,
    pour_point: Union[Tuple[float, float], PondSiteCandidate],
    is_wgs84_coords: bool = False,
    snap_radius_meters: float = 25.0,
) -> CatchmentResult:
    """Convenience helper to delineate upstream catchment."""
    service = CatchmentDelineationService()
    return service.delineate(
        dem_data=dem_data,
        pour_point=pour_point,
        is_wgs84_coords=is_wgs84_coords,
        snap_radius_meters=snap_radius_meters,
    )
