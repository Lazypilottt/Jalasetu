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
import time
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Union

from shapely.geometry import Point, mapping
import numpy as np
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from app.telemetry import tracer
from app.metrics import (
    analyses_total,
    pysheds_fallback_total,
    analysis_duration,
    stage_duration,
    runoff_volume,
)

from app.models.schemas import (
    CatchmentResponse,
    InputSummary,
    PondSiteSummary,
    CatchmentSummary,
    ElevationRange,
    SelectedAreaSummary,
    RainfallSummary,
)
from app.services.kml_parser import KMLParserService
from app.services.dem_builder import DEMBuilderService
from app.services.terrain_analysis import TerrainAnalysisService
from app.services.pond_site import PondSiteService
from app.services.catchment_delineation import CatchmentDelineationService
from app.services.rainfall_service import RainfallService

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
    config = dict(DEFAULT_PIPELINE_PARAMS)
    if params:
        config.update(params)

    # Determine whether this is an uploaded file or bundled default
    is_bundled = isinstance(file_source, (str, Path)) and "contours_1m.kml" in str(file_source)
    has_upload = not is_bundled

    pipeline_start = time.perf_counter()
    with tracer.start_as_current_span("analyze_contour") as parent_span:
        parent_span.set_attribute("has_upload", bool(has_upload))
        if config.get("dem_resolution_m") is not None:
            parent_span.set_attribute("dem_resolution_m", float(config["dem_resolution_m"]))

        try:
            processing_notes: List[str] = []
            selected_area = None
            selected_lat = config.get("selected_latitude")
            selected_lon = config.get("selected_longitude")
            selected_radius = config.get("selected_radius_m")
            if selected_lat is not None and selected_lon is not None and selected_radius is not None:
                selected_area = SelectedAreaSummary(
                    latitude=float(selected_lat),
                    longitude=float(selected_lon),
                    radius_m=float(selected_radius),
                    area_m2=round(3.141592653589793 * float(selected_radius) ** 2, 1),
                )
                processing_notes.append(
                    f"Prioritizing candidate sites within the selected {float(selected_radius):.0f}m map radius."
                )

            # =========================================================================
            # Step 1: KML / KMZ Parsing
            # =========================================================================
            t0 = time.perf_counter()
            logger.info("Starting parse_contours stage")
            with tracer.start_as_current_span("parse_contours") as stage_span:
                try:
                    kml_parser = KMLParserService()
                    contours_gdf = kml_parser.parse(file_source)
                    if contours_gdf is None or contours_gdf.empty:
                        raise ValueError("No valid contour features with elevation data could be extracted.")
                    num_contours = len(contours_gdf)
                    min_contour_elev = float(contours_gdf["elevation"].min())
                    max_contour_elev = float(contours_gdf["elevation"].max())
                    stage_span.set_attribute("num_contours", num_contours)
                    dur = time.perf_counter() - t0
                    stage_duration.record(dur, {"stage": "parse_contours"})
                    logger.info("Completed parse_contours stage in %.2f ms, num_contours=%d", dur * 1000, num_contours)
                except Exception as e:
                    stage_span.record_exception(e)
                    stage_span.set_status(StatusCode.ERROR, str(e))
                    logger.error("parse_contours stage failed: %s", e, exc_info=True)
                    raise

            parent_span.set_attribute("num_contours", int(num_contours))

            input_min_lon, input_min_lat, input_max_lon, input_max_lat = (
                float(value) for value in contours_gdf.total_bounds
            )
            processing_notes.append(
                f"Parsed {num_contours} contour lines with elevations ranging from {min_contour_elev:.1f}m to {max_contour_elev:.1f}m."
            )

            # =========================================================================
            # Step 2: DEM Construction & Local UTM Reprojection
            # =========================================================================
            t0 = time.perf_counter()
            logger.info("Starting build_dem stage")
            with tracer.start_as_current_span("build_dem") as stage_span:
                try:
                    dem_builder = DEMBuilderService()
                    dem_data = dem_builder.build_dem(
                        contours_gdf=contours_gdf,
                        resolution=config.get("dem_resolution_m"),
                        sample_spacing=config.get("sample_spacing_m"),
                        method=config.get("interpolation_method", "linear"),
                    )
                    dur = time.perf_counter() - t0
                    stage_duration.record(dur, {"stage": "build_dem"})
                    logger.info("Completed build_dem stage in %.2f ms, resolution=%.1fm", dur * 1000, dem_data.resolution)
                except Exception as e:
                    stage_span.record_exception(e)
                    stage_span.set_status(StatusCode.ERROR, str(e))
                    logger.error("build_dem stage failed: %s", e, exc_info=True)
                    raise

            parent_span.set_attribute("dem_resolution_m", float(dem_data.resolution))

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

            # Build lightweight GeoJSON feature collection for 2D/3D raised-relief visualization
            contours_geojson = None
            try:
                sample_gdf = contours_gdf
                if len(sample_gdf) > 120:
                    step = max(1, len(sample_gdf) // 120)
                    sample_gdf = sample_gdf.iloc[::step].copy()
                else:
                    sample_gdf = sample_gdf.copy()

                sample_gdf["geometry"] = sample_gdf["geometry"].simplify(0.0001, preserve_topology=True)
                contours_geojson = {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"elevation": round(float(row.elevation), 1)},
                            "geometry": mapping(row.geometry),
                        }
                        for row in sample_gdf.itertuples()
                        if row.geometry is not None and not row.geometry.is_empty
                    ],
                }
            except Exception as exc:
                logger.warning("Could not construct contours GeoJSON: %s", exc)

            # Free contour GeoDataFrame
            del contours_gdf
            gc.collect()

            # Build downsampled 3D elevation mesh for fast interactive raised-relief client rendering
            dem_mesh = None
            try:
                arr = dem_data.array
                nrows, ncols = arr.shape
                target_size = 50
                r_step = max(1, nrows // target_size)
                c_step = max(1, ncols // target_size)
                sampled = arr[::r_step, ::c_step]
                cleaned = np.where(np.isnan(sampled) | (sampled == dem_data.nodata), float(dem_data.min_elevation), sampled)
                dem_mesh = {
                    "rows": int(cleaned.shape[0]),
                    "cols": int(cleaned.shape[1]),
                    "elevation_min": round(float(dem_data.min_elevation), 1),
                    "elevation_max": round(float(dem_data.max_elevation), 1),
                    "relief_m": round(float(dem_data.elevation_span), 1),
                    "bounds": [input_min_lon, input_min_lat, input_max_lon, input_max_lat],
                    "grid": [[round(float(v), 1) for v in row] for row in cleaned],
                }
            except Exception as exc:
                logger.warning("Could not construct dem_mesh: %s", exc)

            # Query location rainfall data for centroid
            rainfall_summary = None
            try:
                centroid_lat = (input_min_lat + input_max_lat) / 2.0
                centroid_lon = (input_min_lon + input_max_lon) / 2.0
                rain_svc = RainfallService()
                rain_data = rain_svc.get_rainfall_data(centroid_lat, centroid_lon)
                rainfall_summary = RainfallSummary(**rain_data)
                processing_notes.append(
                    f"Retrieved precipitation regime: mean annual={rainfall_summary.mean_annual_rainfall_mm:.0f} mm, "
                    f"monsoon={rainfall_summary.monsoon_rainfall_mm:.0f} mm ({rainfall_summary.monsoon_share_pct:.1f}%), "
                    f"24h design storm={rainfall_summary.design_24h_rainfall_mm:.1f} mm ({rainfall_summary.source})."
                )
                if config.get("auto_rainfall") or "design_rainfall_mm" not in config or config.get("design_rainfall_mm") == 100.0:
                    config["design_rainfall_mm"] = rainfall_summary.recommended_design_rainfall_mm
            except Exception as exc:
                logger.warning("Could not fetch rainfall data: %s", exc)

            # =========================================================================
            # Step 3: Terrain & Suitability Analysis
            # =========================================================================
            t0 = time.perf_counter()
            logger.info("Starting terrain_analysis stage")
            with tracer.start_as_current_span("terrain_analysis") as stage_span:
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
                    dur = time.perf_counter() - t0
                    stage_duration.record(dur, {"stage": "terrain_analysis"})
                    logger.info("Completed terrain_analysis stage in %.2f ms, mean_slope=%.1f deg", dur * 1000, analysis_result.mean_slope_deg)
                except Exception as e:
                    stage_span.record_exception(e)
                    stage_span.set_status(StatusCode.ERROR, str(e))
                    logger.error("terrain_analysis stage failed: %s", e, exc_info=True)
                    raise

            # =========================================================================
            # Step 4: Candidate Pond Site Identification & Ranking
            # =========================================================================
            t0 = time.perf_counter()
            logger.info("Starting rank_pond_sites stage")
            with tracer.start_as_current_span("rank_pond_sites") as stage_span:
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
                    stage_span.record_exception(e)
                    stage_span.set_status(StatusCode.ERROR, str(e))
                    logger.error("rank_pond_sites stage failed: %s", e, exc_info=True)
                    raise

                # Free large terrain arrays that are no longer needed
                analysis_result.slope_percent = None  # type: ignore[assignment]
                analysis_result.depression_index = None  # type: ignore[assignment]
                analysis_result.tpi = None  # type: ignore[assignment]
                analysis_result.twi_score = None  # type: ignore[assignment]
                analysis_result.suitable_mask = None  # type: ignore[assignment]
                gc.collect()

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

                dur = time.perf_counter() - t0
                stage_duration.record(dur, {"stage": "rank_pond_sites"})
                logger.info("Completed rank_pond_sites stage in %.2f ms, candidate_count=%d", dur * 1000, len(candidates))
                if not candidates:
                    logger.warning("no suitable site")

            parent_span.set_attribute("candidate_count", int(len(candidates)))

            if not candidates:
                processing_notes.append("No viable candidate pond locations could be identified.")
                dur_total = time.perf_counter() - pipeline_start
                analysis_duration.record(dur_total)
                analyses_total.add(1, {"status": "success"})
                return CatchmentResponse(
                    status="no_suitable_site",
                    message="Terrain analysis completed successfully, but no regions met the suitability criteria for pond excavation.",
                    input_summary=input_summary,
                    recommended_site=None,
                    alternative_sites=[],
                    catchment=None,
                    rainfall=rainfall_summary,
                    contours_geojson=contours_geojson,
                    dem_mesh=dem_mesh,
                    processing_notes=processing_notes,
                )

            # When the user selected an area, prefer candidates inside it
            if selected_area is not None:
                def distance_to_selection(candidate):
                    d_lat = (candidate.latitude - selected_area.latitude) * 111_320.0
                    d_lon = (candidate.longitude - selected_area.longitude) * 111_320.0
                    return (d_lat * d_lat + d_lon * d_lon) ** 0.5

                nearby = [candidate for candidate in candidates
                          if distance_to_selection(candidate) <= selected_area.radius_m]
                candidates = sorted(nearby or candidates, key=distance_to_selection)
                processing_notes.append(
                    f"Found {len(nearby)} candidate site(s) inside the selected area."
                    if nearby
                    else "No candidate fell inside the selected area; showing the nearest terrain-supported site."
                )
                for rank, candidate in enumerate(candidates, start=1):
                    candidate.rank = rank

            top_cand = candidates[0]
            recommended_site = PondSiteSummary(
                site_id=top_cand.site_id,
                rank=top_cand.rank,
                latitude=min(max(round(top_cand.latitude, 6), input_min_lat), input_max_lat),
                longitude=min(max(round(top_cand.longitude, 6), input_min_lon), input_max_lon),
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
                        latitude=min(max(round(cand.latitude, 6), input_min_lat), input_max_lat),
                        longitude=min(max(round(cand.longitude, 6), input_min_lon), input_max_lon),
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

            # Sanity-check coordinate containment
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

            # =========================================================================
            # Step 5: Catchment Watershed Delineation
            # =========================================================================
            t0 = time.perf_counter()
            logger.info("Starting delineate_catchment stage")
            catchment_summary: Optional[CatchmentSummary] = None
            catchment_res = None
            with tracer.start_as_current_span("delineate_catchment") as stage_span:
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
                    if config.get("use_pysheds", True) and catchment_res.method_used not in ("pysheds", "flow_accumulation"):
                        stage_span.add_event("pysheds_fallback")
                        pysheds_fallback_total.add(1)
                        logger.warning("Pysheds fallback: native D8 routing used")

                    dur = time.perf_counter() - t0
                    stage_duration.record(dur, {"stage": "delineate_catchment"})
                    logger.info("Completed delineate_catchment stage in %.2f ms, area_m2=%.1f", dur * 1000, catchment_res.area_m2)
                except Exception as e:
                    stage_span.record_exception(e)
                    stage_span.set_status(StatusCode.ERROR, str(e))
                    logger.error("delineate_catchment stage failed: %s", e, exc_info=True)
                    raise

            routing_method = catchment_res.method_used if catchment_res else "unknown"
            catchment_area_m2 = float(catchment_res.area_m2) if catchment_res else 0.0
            parent_span.set_attribute("routing_method", str(routing_method))
            parent_span.set_attribute("catchment_area_m2", catchment_area_m2)

            delineation_method_name = (
                "flow_accumulation" if catchment_res.method_used in ("pysheds", "flow_accumulation") else "basin_approximation"
            )

            # =========================================================================
            # Step 6: Runoff Volume Estimation
            # =========================================================================
            t0 = time.perf_counter()
            logger.info("Starting estimate_runoff stage")
            runoff_vol = 0.0
            with tracer.start_as_current_span("estimate_runoff") as stage_span:
                try:
                    if catchment_res and catchment_res.scs_runoff:
                        runoff_vol = float(catchment_res.scs_runoff.get("estimated_runoff_volume_m3") or 0.0)
                    runoff_volume.record(runoff_vol)
                    dur = time.perf_counter() - t0
                    stage_duration.record(dur, {"stage": "estimate_runoff"})
                    logger.info("Completed estimate_runoff stage in %.2f ms, runoff_volume_m3=%.1f", dur * 1000, runoff_vol)
                except Exception as e:
                    stage_span.record_exception(e)
                    stage_span.set_status(StatusCode.ERROR, str(e))
                    logger.error("estimate_runoff stage failed: %s", e, exc_info=True)
                    raise

            parent_span.set_attribute("runoff_volume_m3", float(runoff_vol))

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
                f"estimated storm runoff={runoff_vol:,.0f}m³, feasibility={catchment_summary.hydrological_feasibility}."
            )

            dur_total = time.perf_counter() - pipeline_start
            analysis_duration.record(dur_total)
            analyses_total.add(1, {"status": "success"})

            return CatchmentResponse(
                status="success" if catchment_summary is not None else "partial_success",
                message="Contour analysis and pond catchment delineation completed successfully.",
                input_summary=input_summary,
                recommended_site=recommended_site,
                alternative_sites=alternative_sites,
                selected_area=selected_area,
                catchment=catchment_summary,
                rainfall=rainfall_summary,
                contours_geojson=contours_geojson,
                dem_mesh=dem_mesh,
                processing_notes=processing_notes,
            )

        except Exception as exc:
            dur_total = time.perf_counter() - pipeline_start
            analysis_duration.record(dur_total)
            analyses_total.add(1, {"status": "error"})
            parent_span.record_exception(exc)
            parent_span.set_status(StatusCode.ERROR, str(exc))
            raise
