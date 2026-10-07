"""sys4 Flask gateway and catchment delineation service.

The gateway uses HTTP when ``JALASETU_SYS2_URL``/``JALASETU_SYS3_URL`` are
configured and uses the same stage functions in-process otherwise. This makes
local development deterministic while allowing each stage to scale
independently in production.
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from flask import Flask, jsonify, request

from app.models.schemas import (
    CatchmentResponse,
    CatchmentSummary,
    ElevationRange,
    InputSummary,
    PondSiteSummary,
)
from app.services.location_search import recommend_locations

from .config import ServiceConfig
from .stage_payloads import (
    DEMPayload,
    ParsedContoursPayload,
    PondRankingPayload,
    TerrainPayload,
)
from .stages import (
    analyze_terrain_stage,
    build_dem_stage,
    delineate_catchment_stage,
    parse_contours_stage,
    rank_pond_sites_stage,
)

logger = logging.getLogger(__name__)

PARAM_TYPES = {
    "dem_resolution_m": float,
    "sample_spacing_m": float,
    "ideal_slope_deg": float,
    "max_slope_deg": float,
    "neighborhood_radius_m": float,
    "weight_slope": float,
    "weight_depression": float,
    "weight_twi": float,
    "suitability_threshold": float,
    "min_pond_area_m2": float,
    "max_pond_area_m2": float,
    "max_candidate_sites": int,
    "max_elongation_ratio": float,
    "min_pond_width_m": float,
    "pond_design_depth_m": float,
    "snap_radius_m": float,
    "design_rainfall_mm": float,
    "curve_number": float,
    "use_pysheds": lambda value: str(value).lower() in ("1", "true", "yes", "on"),
}


def _error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def _params_from_request() -> Dict[str, Any]:
    body = request.get_json(silent=True) or {}
    raw = body.get("params", {}) if request.is_json else request.form
    result: Dict[str, Any] = {}
    for key, converter in PARAM_TYPES.items():
        value = raw.get(key) if hasattr(raw, "get") else None
        if value not in (None, ""):
            result[key] = converter(value)
    return result


def _uploaded_bytes() -> bytes:
    upload = request.files.get("contour_map") or request.files.get("file")
    if upload is not None:
        return upload.read()
    body = request.get_json(silent=True) or {}
    encoded = body.get("file_base64")
    if not encoded:
        raise ValueError("request must contain a multipart file or file_base64")
    return base64.b64decode(encoded, validate=True)


class Gateway:
    """Orchestrates serializable stages and isolates transport concerns."""

    def __init__(self, config: Optional[ServiceConfig] = None):
        self.config = config or ServiceConfig.from_env()

    def _call_stage(self, endpoint: str, json_data: dict, prefer_url: str, fallback_url: str):
        candidates = [u for u in [prefer_url, fallback_url] if u]
        for url in candidates:
            try:
                logger.info(f"Calling worker stage {url}{endpoint}")
                resp = requests.post(
                    f"{url}{endpoint}",
                    json=json_data,
                    timeout=self.config.request_timeout_seconds,
                )
                if resp.status_code == 200:
                    return resp.json()
                logger.warning(f"Worker {url}{endpoint} responded with status {resp.status_code}: {resp.text[:200]}")
            except Exception as exc:
                logger.warning(f"Worker {url}{endpoint} failed or unreachable: {exc}")
                continue
        return None

    def _prepare(self, file_bytes: bytes, params: Dict[str, Any]):
        data = self._call_stage(
            "/v1/prepare",
            {"file_base64": base64.b64encode(file_bytes).decode("ascii"), "params": params},
            prefer_url=self.config.sys2_url,
            fallback_url=self.config.sys3_url,
        )
        if data is not None:
            return ParsedContoursPayload.from_dict(data["contours"]), DEMPayload.from_dict(data["dem"])
        logger.info("Falling back to local in-process contour parsing and DEM building on sys4")
        contours = parse_contours_stage(file_bytes)
        return contours, build_dem_stage(contours, params)

    def _analyze(self, dem: DEMPayload, params: Dict[str, Any]):
        data = self._call_stage(
            "/v1/analyze",
            {"dem": dem.to_dict(), "params": params},
            prefer_url=self.config.sys3_url,
            fallback_url=self.config.sys2_url,
        )
        if data is not None:
            return TerrainPayload.from_dict(data["terrain"]), PondRankingPayload.from_dict(data["ranking"])
        logger.info("Falling back to local in-process terrain analysis and ranking on sys4")
        terrain = analyze_terrain_stage(dem, params)
        return terrain, rank_pond_sites_stage(terrain, params)

    def analyze(self, file_bytes: bytes, params: Optional[Dict[str, Any]] = None) -> CatchmentResponse:
        params = params or {}
        contours, dem = self._prepare(file_bytes, params)
        if not contours.features:
            return CatchmentResponse(
                status="error",
                message="No valid contour features with elevation data could be extracted from the file.",
                processing_notes=["No contour features found."],
            )
        terrain, ranking = self._analyze(dem, params)
        catchment = delineate_catchment_stage(terrain, ranking, params)
        return _public_response(contours, dem, terrain, ranking, catchment)


def _public_response(
    contours: ParsedContoursPayload,
    dem: DEMPayload,
    terrain: TerrainPayload,
    ranking: PondRankingPayload,
    catchment: Any,
) -> CatchmentResponse:
    elevations = [float(item["elevation"]) for item in contours.features]
    native_ranking = ranking.to_result(dem.to_dem_data())
    candidates = native_ranking.candidates
    input_summary = InputSummary(
        num_contours=len(elevations),
        elevation_min=min(elevations),
        elevation_max=max(elevations),
        dem_resolution_m=dem.resolution,
        utm_crs=dem.crs,
    )
    sites = [
        PondSiteSummary(
            site_id=c.site_id,
            rank=c.rank,
            latitude=round(c.latitude, 6),
            longitude=round(c.longitude, 6),
            elevation_m=round(c.mean_elevation, 2),
            suitability_score=round(c.mean_suitability, 1),
            area_m2=round(c.area_m2, 1),
            slope_deg=round(c.mean_slope_deg, 2),
            storage_capacity_m3=round(c.storage_capacity_m3, 1),
            cut_volume_m3=round(c.cut_volume_m3, 1),
            storage_efficiency_ratio=round(c.storage_efficiency_ratio, 2),
            mean_twi=round(c.mean_twi, 2),
            composite_mcdm_score=round(c.composite_mcdm_score, 1),
            stage_storage_curve=c.stage_storage_curve,
            boundary_geojson=c.to_boundary_geojson_dict(),
        )
        for c in candidates
    ]
    notes = [
        f"Parsed {len(elevations)} contour lines with elevations ranging from {min(elevations):.1f}m to {max(elevations):.1f}m.",
        f"Generated DEM grid at {dem.resolution:.1f}m resolution in {dem.crs}.",
        f"Computed terrain derivatives: mean slope={terrain.mean_slope_deg:.1f}°, mean suitability={terrain.mean_suitability:.1f}/100.",
        *ranking.notes,
    ]
    if not sites:
        return CatchmentResponse(
            status="no_suitable_site",
            message="Terrain analysis completed successfully, but no suitable pond sites were identified.",
            input_summary=input_summary,
            processing_notes=notes + ["No viable candidate pond locations could be identified."],
        )

    catchment_summary = None
    if catchment is not None:
        runoff = catchment.scs_runoff or {}
        feasibility = catchment.feasibility or {}
        erosion = catchment.erosion_metrics or {}
        catchment_summary = CatchmentSummary(
            boundary_geojson=catchment.to_geojson_dict(),
            area_m2=round(catchment.area_m2, 1),
            area_hectares=round(catchment.area_ha, 3),
            average_slope_deg=round(catchment.mean_slope_deg, 2),
            elevation_range_m=ElevationRange(
                min_m=round(catchment.min_elevation, 2),
                max_m=round(catchment.max_elevation, 2),
                relief_m=round(catchment.elevation_span, 2),
            ),
            delineation_method="flow_accumulation" if catchment.method_used == "pysheds" else "basin_approximation",
            catchment_to_pond_ratio=feasibility.get("catchment_to_pond_ratio"),
            hydrological_feasibility=feasibility.get("hydrological_feasibility"),
            feasibility_explanation=feasibility.get("feasibility_explanation"),
            estimated_runoff_volume_m3=runoff.get("estimated_runoff_volume_m3"),
            design_rainfall_mm=runoff.get("design_rainfall_mm"),
            curve_number=runoff.get("curve_number"),
            mean_ls_factor=erosion.get("mean_ls_factor"),
            siltation_risk=erosion.get("siltation_risk"),
            siltation_explanation=erosion.get("siltation_explanation"),
            water_filling_factor=feasibility.get("water_filling_factor"),
        )
        notes.append(f"Delineated upstream catchment: area={catchment.area_ha:.2f} ha.")
    return CatchmentResponse(
        status="success" if catchment_summary is not None else "partial_success",
        message="Contour analysis and pond catchment delineation completed successfully.",
        input_summary=input_summary,
        recommended_site=sites[0],
        alternative_sites=sites[1:],
        catchment=catchment_summary,
        processing_notes=notes,
    )


def create_app(config: Optional[ServiceConfig] = None) -> Flask:
    app = Flask("jalasetu-sys4")
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
    gateway = Gateway(config)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "sys4", "message": "sys4 gateway is running"})

    @app.get("/analyzeContour/schema")
    def schema():
        from app.services.pipeline import DEFAULT_PIPELINE_PARAMS

        return jsonify(
            {
                "title": "CatchmentResponse Schema Documentation",
                "schema": CatchmentResponse.model_json_schema(),
                "example": CatchmentResponse.model_config.get("json_schema_extra", {}).get("example", {}),
                "default_parameters": DEFAULT_PIPELINE_PARAMS,
            }
        )

    @app.route("/IP/search/", methods=["GET", "POST"])
    def search_locations():
        values = request.args if request.method == "GET" else request.form
        try:
            latitude = float(values["lat"])
            longitude = float(values["long"])
            category = values["cat"]
            radius = float(values["rad"])
        except (KeyError, TypeError, ValueError):
            return _error("lat, long, cat, and rad are required", 422)

        if not category.strip():
            return _error("cat must not be empty", 422)
        if radius < 0:
            return _error("rad must be non-negative", 422)

        link_text = None
        if request.method == "POST" and "link" in request.files:
            link_text = request.files["link"].read().decode("utf-8")

        try:
            return jsonify(recommend_locations(latitude, longitude, category, radius, link_text))
        except (FileNotFoundError, OSError, ValueError) as exc:
            return _error(str(exc), 400)

    @app.post("/analyzeContour")
    @app.post("/findCatchment")
    @app.post("/v1/analyze")
    def analyze():
        try:
            result = gateway.analyze(_uploaded_bytes(), _params_from_request())
            status = 200 if result.status != "error" else 422
            return jsonify(result.model_dump()), status
        except requests.RequestException:
            logger.exception("downstream service request failed")
            return _error("a processing service is unavailable", 502)
        except Exception as exc:
            logger.exception("sys4 request failed")
            return _error(str(exc), 422)

    @app.errorhandler(413)
    def too_large(_error):
        return _error("uploaded file exceeds the 50 MB limit", 413)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("JALASETU_PORT", "3000")), threaded=True)
