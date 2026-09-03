"""
End-to-End Terrain and Pond Catchment Analysis Pipeline.

Orchestration Sequence:
  1. kml_parser.py           -> Extract contour lines & elevations (EPSG:4326)
  2. dem_builder.py          -> Reproject to local UTM & interpolate regular DEM
  3. terrain_analysis.py     -> Calculate slope, local depressions & suitability scores
  4. pond_site.py            -> Segment contiguous sweet-spots & rank candidate sites
  5. catchment_delineation.py -> Trace upstream drainage catchment for recommended site

Provides:
  - analyze_contour_file(file_source, params) -> CatchmentResponse
  - DEFAULT_PIPELINE_PARAMS dictionary documenting all tunable thresholds and weights
"""

import gc
import logging
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Union

from shapely.geometry import Point

from app.models.schemas import (
    CatchmentResponse,
    InputSummary,
    PondSiteSummary,
    CatchmentSummary,
    ElevationRange,
)
from app.services.kml_parser import KMLParserService
from app.services.dem_builder import DEMBuilderService
from app.services.terrain_analysis import TerrainAnalysisService
from app.services.pond_site import PondSiteService
from app.services.catchment_delineation import CatchmentDelineationService

logger = logging.getLogger(__name__)

# Complete dictionary of tunable parameters with production-ready defaults
DEFAULT_PIPELINE_PARAMS: Dict[str, Any] = {
    # --- DEM Builder Parameters ---
    "dem_resolution_m": None,           # Optional float (e.g. 5.0). If None, data-driven adaptive resolution is used.
    "sample_spacing_m": None,           # Optional float. Interval along contour lines to sample points (defaults to res/2).
    "interpolation_method": "linear",   # Interpolation algorithm ('linear' or 'cubic' with nearest fallback for convex hull).

    # --- Terrain Analysis Parameters ---
    "ideal_slope_deg": 3.0,             # Slopes <= this angle (in degrees) receive 100% slope score.
    "max_slope_deg": 8.0,               # Slopes > this angle receive 0% slope score.
    "neighborhood_radius_m": None,      # Radius in meters for local depression window filter (None = auto-derived).
    "weight_slope": 0.35,               # Relative weight for slope factor in composite suitability score.
    "weight_depression": 0.35,          # Relative weight for depression factor in composite suitability score.
    "weight_twi": 0.30,                 # Relative weight for Topographic Wetness Index (TWI).
    "suitability_threshold": 60.0,      # Minimum score (0-100) to classify a cell as suitable for pond excavation.

    # --- Pond Siting Parameters ---
    "min_pond_area_m2": 200.0,          # Minimum contiguous footprint in m² required for a viable farm pond.
    "max_pond_area_m2": None,           # Optional maximum footprint in m².
    "max_candidate_sites": 5,           # Maximum number of ranked candidate sites to return.
    "max_elongation_ratio": 3.5,        # Maximum allowable major-to-minor axis ratio (rejects linear road/channel corridors).
    "min_pond_width_m": None,           # Minimum allowable excavation width in meters (derived from cell size if None).
    "pond_design_depth_m": 2.0,         # Standard pond design water depth in meters for volumetric capacity calculations.

    # --- Catchment Delineation & Hydrology Parameters ---
    "snap_radius_m": 25.0,              # Radius in meters to snap pour point to stream channel / high-accumulation cell.
    "use_pysheds": True,                # Attempt pysheds hydrological flow accumulation first (with native D8 fallback).
    "design_rainfall_mm": 100.0,        # 24-hr design storm precipitation in mm for SCS-CN runoff volume estimation.
    "curve_number": 75.0,               # SCS Runoff Curve Number (CN) for agricultural / cultivated soils.
}


def analyze_contour_file(
    file_source: Union[str, Path, BinaryIO, bytes],
    params: Optional[Dict[str, Any]] = None,
) -> CatchmentResponse:
    """
    Run complete end-to-end contour analysis and pond catchment delineation pipeline.

    Args:
        file_source: Input file path, bytes, or file-like stream (.kml or .kmz).
        params (Optional[Dict[str, Any]]): Parameter dictionary overriding DEFAULT_PIPELINE_PARAMS.

    Returns:
        CatchmentResponse: Full structured response including input summary, recommended site,
                           ranked alternative sites, catchment boundary GeoJSON & metrics, and processing notes.
    """
    # 1. Merge provided parameters with defaults
    config = dict(DEFAULT_PIPELINE_PARAMS)
    if params:
        config.update(params)

    processing_notes: List[str] = []

    # =========================================================================
    # Step 1: KML / KMZ Parsing
    # =========================================================================
    try:
        kml_parser = KMLParserService()
        contours_gdf = kml_parser.parse(file_source)
    except Exception as e:
        logger.error("KML Parser failed: %s", e)
        return CatchmentResponse(
            status="error",
            message=f"Failed to parse KML/KMZ contour file: {e}",
            processing_notes=[f"Parser error: {e}"],
        )

    if contours_gdf.empty:
        return CatchmentResponse(
            status="error",
            message="No valid contour features with elevation data could be extracted from the file.",
            processing_notes=["No contour features found."],
        )

    num_contours = len(contours_gdf)
    min_contour_elev = float(contours_gdf["elevation"].min())
    max_contour_elev = float(contours_gdf["elevation"].max())
    processing_notes.append(
        f"Parsed {num_contours} contour lines with elevations ranging from {min_contour_elev:.1f}m to {max_contour_elev:.1f}m."
    )

    # =========================================================================
    # Step 2: DEM Construction & Local UTM Reprojection
    # =========================================================================
    try:
        dem_builder = DEMBuilderService()
        dem_data = dem_builder.build_dem(
            contours_gdf=contours_gdf,
            resolution=config.get("dem_resolution_m"),
            sample_spacing=config.get("sample_spacing_m"),
            method=config.get("interpolation_method", "linear"),
        )
    except Exception as e:
        logger.error("DEM Builder failed: %s", e)
        return CatchmentResponse(
            status="error",
            message=f"Failed to construct DEM from contours: {e}",
            input_summary=InputSummary(
                num_contours=num_contours,
                elevation_min=min_contour_elev,
                elevation_max=max_contour_elev,
                dem_resolution_m=0.0,
            ),
            processing_notes=processing_notes + [f"DEM error: {e}"],
        )

    input_summary = InputSummary(
        num_contours=num_contours,
        elevation_min=min_contour_elev,
        elevation_max=max_contour_elev,
        dem_resolution_m=dem_data.resolution,
        utm_crs=dem_data.crs,
    )
    processing_notes.append(
        f"Generated DEM grid: {dem_data.height}x{dem_data.width} cells at {dem_data.resolution:.1f}m resolution in {dem_data.crs}."
    )

    # Free contour GeoDataFrame — no longer needed after DEM construction
    del contours_gdf
    gc.collect()

    # =========================================================================
    # Step 3: Terrain & Suitability Analysis
    # =========================================================================
    try:
        terrain_service = TerrainAnalysisService()
        analysis_result = terrain_service.analyze_terrain(
            dem_data=dem_data,
            ideal_slope_deg=config.get("ideal_slope_deg", 3.0),
            max_slope_deg=config.get("max_slope_deg", 8.0),
            neighborhood_radius_m=config.get("neighborhood_radius_m"),
            weight_slope=config.get("weight_slope", 0.35),
            weight_depression=config.get("weight_depression", 0.35),
            weight_twi=config.get("weight_twi", 0.30),
            suitability_threshold=config.get("suitability_threshold", 60.0),
        )
        processing_notes.append(
            f"Computed terrain derivatives: mean slope={analysis_result.mean_slope_deg:.1f}°, mean TWI={analysis_result.mean_twi:.2f}, "
            f"mean suitability={analysis_result.mean_suitability:.1f}/100, suitable area={analysis_result.suitable_area_percentage:.1f}%."
        )
    except Exception as e:
        logger.error("Terrain Analysis failed: %s", e)
        return CatchmentResponse(
            status="error",
            message=f"Terrain analysis failed: {e}",
            input_summary=input_summary,
            processing_notes=processing_notes + [f"Terrain analysis error: {e}"],
        )

    # =========================================================================
    # Step 4: Candidate Pond Site Identification & Ranking
    # =========================================================================
    try:
        pond_service = PondSiteService()
        siting_result = pond_service.identify_candidate_sites(
            analysis_result=analysis_result,
            min_suitability_threshold=config.get("suitability_threshold", 60.0),
            min_area_m2=config.get("min_pond_area_m2", 200.0),
            max_area_m2=config.get("max_pond_area_m2"),
            max_slope_deg=config.get("max_slope_deg", 8.0),
            max_elongation_ratio=config.get("max_elongation_ratio", 3.5),
            min_width_m=config.get("min_pond_width_m") or config.get("min_width_m"),
            pond_design_depth_m=config.get("pond_design_depth_m", 2.0),
            top_n=config.get("max_candidate_sites", 5),
        )
        if siting_result.notes:
            processing_notes.extend(siting_result.notes)
    except Exception as e:
        logger.error("Pond Siting failed: %s", e)
        return CatchmentResponse(
            status="error",
            message=f"Pond siting failed: {e}",
            input_summary=input_summary,
            processing_notes=processing_notes + [f"Pond siting error: {e}"],
        )

    # Free large terrain arrays that are no longer needed — only flow_accum
    # and flow_dir are required for catchment delineation.
    analysis_result.slope_percent = None  # type: ignore[assignment]
    analysis_result.depression_index = None  # type: ignore[assignment]
    analysis_result.tpi = None  # type: ignore[assignment]
    analysis_result.twi_score = None  # type: ignore[assignment]
    analysis_result.suitable_mask = None  # type: ignore[assignment]
    gc.collect()

    # If no candidate passed strict thresholds, attempt a relaxed fallback
    candidates = siting_result.candidates
    if not candidates:
        logger.warning("No candidate pond sites met default criteria; attempting relaxed fallback...")
        processing_notes.append(
            "No candidate regions met initial criteria (threshold: "
            f"{config.get('suitability_threshold')} score, {config.get('min_pond_area_m2')}m² area). Attempting relaxed fallback."
        )
        try:
            siting_result = pond_service.identify_candidate_sites(
                analysis_result=analysis_result,
                min_suitability_threshold=max(40.0, config.get("suitability_threshold", 60.0) - 20.0),
                min_area_m2=max(50.0, config.get("min_pond_area_m2", 200.0) / 4.0),
                max_elongation_ratio=config.get("max_elongation_ratio", 3.5),
                min_width_m=config.get("min_pond_width_m") or config.get("min_width_m"),
                pond_design_depth_m=config.get("pond_design_depth_m", 2.0),
                top_n=config.get("max_candidate_sites", 5),
            )
            if siting_result.notes:
                processing_notes.extend(siting_result.notes)
            candidates = siting_result.candidates
            if candidates:
                processing_notes.append(f"Relaxed fallback identified {len(candidates)} candidate site(s).")
        except Exception as e:
            logger.warning("Fallback pond siting error: %s", e)

    if not candidates:
        processing_notes.append("No viable candidate pond locations could be identified.")
        return CatchmentResponse(
            status="no_suitable_site",
            message="Terrain analysis completed successfully, but no regions met the suitability criteria for pond excavation.",
            input_summary=input_summary,
            recommended_site=None,
            alternative_sites=[],
            catchment=None,
            processing_notes=processing_notes,
        )

    # Format recommended site and alternatives
    top_cand = candidates[0]
    recommended_site = PondSiteSummary(
        site_id=top_cand.site_id,
        rank=top_cand.rank,
        latitude=round(top_cand.latitude, 6),
        longitude=round(top_cand.longitude, 6),
        elevation_m=round(top_cand.mean_elevation, 2),
        suitability_score=round(top_cand.mean_suitability, 1),
        area_m2=round(top_cand.area_m2, 1),
        slope_deg=round(top_cand.mean_slope_deg, 2),
        storage_capacity_m3=round(top_cand.storage_capacity_m3, 1),
        cut_volume_m3=round(top_cand.cut_volume_m3, 1),
        storage_efficiency_ratio=round(top_cand.storage_efficiency_ratio, 2),
        mean_twi=round(top_cand.mean_twi, 2),
        composite_mcdm_score=round(top_cand.composite_mcdm_score, 1),
        stage_storage_curve=top_cand.stage_storage_curve,
        boundary_geojson=top_cand.to_boundary_geojson_dict(),
    )

    alternative_sites: List[PondSiteSummary] = []
    for cand in candidates[1:]:
        alternative_sites.append(
            PondSiteSummary(
                site_id=cand.site_id,
                rank=cand.rank,
                latitude=round(cand.latitude, 6),
                longitude=round(cand.longitude, 6),
                elevation_m=round(cand.mean_elevation, 2),
                suitability_score=round(cand.mean_suitability, 1),
                area_m2=round(cand.area_m2, 1),
                slope_deg=round(cand.mean_slope_deg, 2),
                storage_capacity_m3=round(cand.storage_capacity_m3, 1),
                cut_volume_m3=round(cand.cut_volume_m3, 1),
                storage_efficiency_ratio=round(cand.storage_efficiency_ratio, 2),
                mean_twi=round(cand.mean_twi, 2),
                composite_mcdm_score=round(cand.composite_mcdm_score, 1),
                stage_storage_curve=cand.stage_storage_curve,
                boundary_geojson=cand.to_boundary_geojson_dict(),
            )
        )

    processing_notes.append(
        f"Selected top recommended pond site ({top_cand.site_id}): score={top_cand.mean_suitability:.1f}, "
        f"storage capacity={top_cand.storage_capacity_m3:,.0f}m³, area={top_cand.area_m2:.0f}m² at ({top_cand.latitude:.5f}°N, {top_cand.longitude:.5f}°E)."
    )

    # Sanity-check coordinate containment: verify recommended site point falls within
    # (or within one cell's distance of) its own suitability region boundary polygon
    if top_cand.polygon_utm is not None and not top_cand.polygon_utm.is_empty:
        site_point_utm = Point(top_cand.utm_x, top_cand.utm_y)
        cell_size_m = float(dem_data.resolution)
        is_inside_utm = top_cand.polygon_utm.covers(site_point_utm) or top_cand.polygon_utm.contains(site_point_utm)
        dist_utm = 0.0 if is_inside_utm else float(top_cand.polygon_utm.distance(site_point_utm))

        if dist_utm > cell_size_m:
            warning_msg = (
                f"DATA QUALITY WARNING: Recommended pond site centroid ({top_cand.latitude:.6f}°N, {top_cand.longitude:.6f}°E) "
                f"does not fall within its candidate suitability region boundary polygon "
                f"(distance: {dist_utm:.2f}m exceeds 1-cell threshold of {cell_size_m:.1f}m). "
                f"Possible coordinate transform misalignment."
            )
            logger.warning(warning_msg)
            processing_notes.append(warning_msg)
        else:
            logger.debug(
                "Coordinate containment sanity-check passed: site centroid distance to suitability region polygon is %.2fm (<= %.1fm cell threshold).",
                dist_utm,
                cell_size_m,
            )

    # =========================================================================
    # Step 5: Catchment Watershed Delineation
    # =========================================================================
    catchment_summary: Optional[CatchmentSummary] = None
    try:
        catchment_service = CatchmentDelineationService()
        catchment_res = catchment_service.delineate(
            dem_data=dem_data,
            pour_point=top_cand,
            snap_radius_meters=config.get("snap_radius_m", 25.0),
            use_pysheds_if_available=config.get("use_pysheds", True),
            design_rainfall_mm=config.get("design_rainfall_mm", 100.0),
            curve_number=config.get("curve_number", 75.0),
            pond_area_m2=top_cand.area_m2,
            pond_storage_m3=top_cand.storage_capacity_m3,
            precomputed_flow_accum=analysis_result.flow_accum,
            precomputed_flow_dir=analysis_result.flow_dir,
        )

        delineation_method_name = (
            "flow_accumulation" if catchment_res.method_used == "pysheds" else "basin_approximation"
        )

        catchment_summary = CatchmentSummary(
            boundary_geojson=catchment_res.to_geojson_dict(),
            area_m2=round(catchment_res.area_m2, 1),
            area_hectares=round(catchment_res.area_ha, 3),
            average_slope_deg=round(catchment_res.mean_slope_deg, 2),
            elevation_range_m=ElevationRange(
                min_m=round(catchment_res.min_elevation, 2),
                max_m=round(catchment_res.max_elevation, 2),
                relief_m=round(catchment_res.elevation_span, 2),
            ),
            delineation_method=delineation_method_name,
            catchment_to_pond_ratio=catchment_res.feasibility.get("catchment_to_pond_ratio") if catchment_res.feasibility else None,
            hydrological_feasibility=catchment_res.feasibility.get("hydrological_feasibility") if catchment_res.feasibility else None,
            feasibility_explanation=catchment_res.feasibility.get("feasibility_explanation") if catchment_res.feasibility else None,
            estimated_runoff_volume_m3=catchment_res.scs_runoff.get("estimated_runoff_volume_m3") if catchment_res.scs_runoff else None,
            design_rainfall_mm=catchment_res.scs_runoff.get("design_rainfall_mm") if catchment_res.scs_runoff else None,
            curve_number=catchment_res.scs_runoff.get("curve_number") if catchment_res.scs_runoff else None,
            mean_ls_factor=catchment_res.erosion_metrics.get("mean_ls_factor") if catchment_res.erosion_metrics else None,
            siltation_risk=catchment_res.erosion_metrics.get("siltation_risk") if catchment_res.erosion_metrics else None,
            siltation_explanation=catchment_res.erosion_metrics.get("siltation_explanation") if catchment_res.erosion_metrics else None,
            water_filling_factor=catchment_res.feasibility.get("water_filling_factor") if catchment_res.feasibility else None,
        )

        processing_notes.append(
            f"Delineated upstream catchment using {delineation_method_name}: area={catchment_res.area_ha:.2f} ha "
            f"({catchment_res.area_m2:,.0f}m²), elevation span={catchment_res.elevation_span:.1f}m, mean slope={catchment_res.mean_slope_deg:.1f}°, "
            f"estimated storm runoff={catchment_summary.estimated_runoff_volume_m3:,.0f}m³, feasibility={catchment_summary.hydrological_feasibility}."
        )

    except Exception as e:
        logger.error("Catchment delineation failed: %s", e)
        processing_notes.append(f"Catchment delineation failed: {e}")

    return CatchmentResponse(
        status="success" if catchment_summary is not None else "partial_success",
        message="Contour analysis and pond catchment delineation completed successfully.",
        input_summary=input_summary,
        recommended_site=recommended_site,
        alternative_sites=alternative_sites,
        catchment=catchment_summary,
        processing_notes=processing_notes,
    )
