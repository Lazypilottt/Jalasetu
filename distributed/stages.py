"""Small, transport-independent functions for each processing stage."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from opentelemetry import trace
from opentelemetry.trace import StatusCode

from app.telemetry import tracer
from app.metrics import stage_duration, pysheds_fallback_total
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

logger = logging.getLogger(__name__)


def parse_contours_stage(file_bytes: bytes) -> ParsedContoursPayload:
    """Parse KML/KMZ bytes without leaking a GeoDataFrame across a boundary."""
    t0 = time.perf_counter()
    logger.info("Starting parse_contours stage")
    with tracer.start_as_current_span("parse_contours") as span:
        try:
            gdf = KMLParserService().parse(file_bytes)
            if gdf is None or gdf.empty:
                raise ValueError("No valid contour features with elevation data could be extracted.")
            res = ParsedContoursPayload.from_geodataframe(gdf)
            num_contours = len(res.features)
            span.set_attribute("num_contours", num_contours)
            dur_s = time.perf_counter() - t0
            stage_duration.record(dur_s, {"stage": "parse_contours"})
            logger.info("Completed parse_contours stage in %.2f ms, num_contours=%d", dur_s * 1000, num_contours)
            return res
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR, str(exc))
            logger.error("parse_contours stage failed: %s", exc, exc_info=True)
            raise


def build_dem_stage(
    contours: ParsedContoursPayload,
    params: Optional[Dict[str, Any]] = None,
) -> DEMPayload:
    params = params or {}
    t0 = time.perf_counter()
    logger.info("Starting build_dem stage")
    with tracer.start_as_current_span("build_dem") as span:
        try:
            dem = DEMBuilderService().build_dem(
                contours.to_geodataframe(),
                resolution=params.get("dem_resolution_m"),
                sample_spacing=params.get("sample_spacing_m"),
                method=params.get("interpolation_method", "linear"),
            )
            res = DEMPayload.from_dem_data(dem)
            dur_s = time.perf_counter() - t0
            stage_duration.record(dur_s, {"stage": "build_dem"})
            logger.info("Completed build_dem stage in %.2f ms, resolution=%.1fm", dur_s * 1000, dem.resolution)
            return res
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR, str(exc))
            logger.error("build_dem stage failed: %s", exc, exc_info=True)
            raise


def analyze_terrain_stage(
    dem: DEMPayload,
    params: Optional[Dict[str, Any]] = None,
) -> TerrainPayload:
    params = params or {}
    t0 = time.perf_counter()
    logger.info("Starting terrain_analysis stage")
    with tracer.start_as_current_span("terrain_analysis") as span:
        try:
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
            res = TerrainPayload.from_result(result)
            dur_s = time.perf_counter() - t0
            stage_duration.record(dur_s, {"stage": "terrain_analysis"})
            logger.info("Completed terrain_analysis stage in %.2f ms, mean_slope=%.1f deg", dur_s * 1000, result.mean_slope_deg)
            return res
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR, str(exc))
            logger.error("terrain_analysis stage failed: %s", exc, exc_info=True)
            raise


def rank_pond_sites_stage(
    terrain: TerrainPayload,
    params: Optional[Dict[str, Any]] = None,
) -> PondRankingPayload:
    params = params or {}
    t0 = time.perf_counter()
    logger.info("Starting rank_pond_sites stage")
    with tracer.start_as_current_span("rank_pond_sites") as span:
        try:
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
            candidates = result.candidates
            if not candidates:
                logger.warning("no suitable site")
            res = PondRankingPayload.from_result(result)
            dur_s = time.perf_counter() - t0
            stage_duration.record(dur_s, {"stage": "rank_pond_sites"})
            logger.info("Completed rank_pond_sites stage in %.2f ms, candidate_count=%d", dur_s * 1000, len(candidates))
            return res
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR, str(exc))
            logger.error("rank_pond_sites stage failed: %s", exc, exc_info=True)
            raise


def delineate_catchment_stage(
    terrain: TerrainPayload,
    ranking: PondRankingPayload,
    params: Optional[Dict[str, Any]] = None,
) -> Optional[CatchmentPayload]:
    """Run sys4's hydrology stage and return a serializable result."""
    from app.services.catchment_delineation import CatchmentDelineationService

    params = params or {}
    t0 = time.perf_counter()
    logger.info("Starting delineate_catchment stage")
    with tracer.start_as_current_span("delineate_catchment") as span:
        try:
            dem = terrain.dem.to_dem_data()
            candidates = ranking.to_result(dem).candidates
            if not candidates:
                dur_s = time.perf_counter() - t0
                stage_duration.record(dur_s, {"stage": "delineate_catchment"})
                logger.warning("no suitable site to delineate catchment for")
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
            if params.get("use_pysheds", True) and result.method_used not in ("pysheds", "flow_accumulation"):
                span.add_event("pysheds_fallback")
                pysheds_fallback_total.add(1)
                logger.warning("Pysheds fallback: native D8 routing used")

            dur_s = time.perf_counter() - t0
            stage_duration.record(dur_s, {"stage": "delineate_catchment"})
            logger.info("Completed delineate_catchment stage in %.2f ms, area_m2=%.1f", dur_s * 1000, result.area_m2)
            return CatchmentPayload.from_result(result)
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR, str(exc))
            logger.error("delineate_catchment stage failed: %s", exc, exc_info=True)
            raise


# Friendly aliases used by workers and deployment examples.
parse_kml_stage = parse_contours_stage
