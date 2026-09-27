"""Small, transport-independent functions for each processing stage."""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.dem_builder import DEMBuilderService
from app.services.kml_parser import KMLParserService
from app.services.pond_site import PondSiteService
from app.services.terrain_analysis import TerrainAnalysisService

from .stage_payloads import (
    CatchmentPayload,
    DEMPayload,
    ParsedContoursPayload,
    PondRankingPayload,
    TerrainPayload,
)


def parse_contours_stage(file_bytes: bytes) -> ParsedContoursPayload:
    """Parse KML/KMZ bytes without leaking a GeoDataFrame across a boundary."""
    return ParsedContoursPayload.from_geodataframe(KMLParserService().parse(file_bytes))


def build_dem_stage(
    contours: ParsedContoursPayload,
    params: Optional[Dict[str, Any]] = None,
) -> DEMPayload:
    params = params or {}
    dem = DEMBuilderService().build_dem(
        contours.to_geodataframe(),
        resolution=params.get("dem_resolution_m"),
        sample_spacing=params.get("sample_spacing_m"),
        method=params.get("interpolation_method", "linear"),
    )
    return DEMPayload.from_dem_data(dem)


def analyze_terrain_stage(
    dem: DEMPayload,
    params: Optional[Dict[str, Any]] = None,
) -> TerrainPayload:
    params = params or {}
    result = TerrainAnalysisService().analyze_terrain(
        dem.to_dem_data(),
        ideal_slope_deg=params.get("ideal_slope_deg", 3.0),
        max_slope_deg=params.get("max_slope_deg", 8.0),
        neighborhood_radius_m=params.get("neighborhood_radius_m"),
        weight_slope=params.get("weight_slope", 0.35),
        weight_depression=params.get("weight_depression", 0.35),
        weight_twi=params.get("weight_twi", 0.30),
        suitability_threshold=params.get("suitability_threshold", 60.0),
    )
    return TerrainPayload.from_result(result)


def rank_pond_sites_stage(
    terrain: TerrainPayload,
    params: Optional[Dict[str, Any]] = None,
) -> PondRankingPayload:
    params = params or {}
    result = PondSiteService().identify_candidate_sites(
        analysis_result=terrain.to_result(),
        min_suitability_threshold=params.get("suitability_threshold", 60.0),
        min_area_m2=params.get("min_pond_area_m2", 200.0),
        max_area_m2=params.get("max_pond_area_m2"),
        max_slope_deg=params.get("max_slope_deg", 8.0),
        max_elongation_ratio=params.get("max_elongation_ratio", 3.5),
        min_width_m=params.get("min_pond_width_m") or params.get("min_width_m"),
        pond_design_depth_m=params.get("pond_design_depth_m", 2.0),
        top_n=params.get("max_candidate_sites", 5),
    )
    return PondRankingPayload.from_result(result)


def delineate_catchment_stage(
    terrain: TerrainPayload,
    ranking: PondRankingPayload,
    params: Optional[Dict[str, Any]] = None,
) -> Optional[CatchmentPayload]:
    """Run sys4's hydrology stage and return a serializable result."""
    from app.services.catchment_delineation import CatchmentDelineationService

    params = params or {}
    dem = terrain.dem.to_dem_data()
    candidates = ranking.to_result(dem).candidates
    if not candidates:
        return None
    candidate = candidates[0]
    result = CatchmentDelineationService().delineate(
        dem_data=dem,
        pour_point=candidate,
        snap_radius_meters=params.get("snap_radius_m", 25.0),
        use_pysheds_if_available=params.get("use_pysheds", True),
        design_rainfall_mm=params.get("design_rainfall_mm", 100.0),
        curve_number=params.get("curve_number", 75.0),
        pond_area_m2=candidate.area_m2,
        pond_storage_m3=candidate.storage_capacity_m3,
        precomputed_flow_accum=terrain.to_result().flow_accum,
        precomputed_flow_dir=terrain.to_result().flow_dir,
    )
    return CatchmentPayload.from_result(result)


# Friendly aliases used by workers and deployment examples.
parse_kml_stage = parse_contours_stage
