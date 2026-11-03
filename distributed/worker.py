"""Shared Flask stage worker used by sys2 and sys3.

Every worker can run every stage. The gateway's scheduler decides where a stage
goes from the capacity each worker reports on ``/health``; ``affinity`` only
breaks ties between equally idle nodes. Heavy endpoints refuse work with
HTTP 503 when the node has no free slot or too little memory headroom, so the
gateway can try the next node instead of pushing this one into the OOM killer.
"""

from __future__ import annotations

import base64
import logging
from functools import wraps
from typing import Any, Callable, Dict, Iterable

from flask import Flask, jsonify, request

from .capacity import CapacityGuard, StorageMonitor
from .stage_payloads import DEMPayload, ParsedContoursPayload, PondRankingPayload, TerrainPayload
from .stages import (
    analyze_terrain_stage,
    build_dem_stage,
    delineate_catchment_stage,
    global_dem_stage,
    parse_contours_stage,
    rank_pond_sites_stage,
)

logger = logging.getLogger(__name__)

STAGES = ("prepare", "analyze", "catchment")
RETRY_AFTER_SECONDS = "2"


def _error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def _file_bytes() -> bytes:
    upload = request.files.get("file") or request.files.get("contour_map")
    if upload is not None:
        return upload.read()
    body = request.get_json(silent=True) or {}
    encoded = body.get("file_base64")
    if not encoded:
        raise ValueError("request must contain a multipart file or file_base64")
    return base64.b64decode(encoded, validate=True)


def create_worker_app(service: str, affinity: Iterable[str], guard: CapacityGuard | None = None) -> Flask:
    app = Flask(f"jalasetu-{service}")
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
    guard = guard or CapacityGuard()
    storage = StorageMonitor()
    affinity = [stage for stage in affinity if stage in STAGES]
    app.extensions["jalasetu_guard"] = guard

    def heavy(label: str) -> Callable:
        """Run the view inside a capacity slot, or answer 503 busy."""

        def decorator(view: Callable) -> Callable:
            @wraps(view)
            def wrapped(*args, **kwargs):
                with guard.slot() as admitted:
                    if not admitted:
                        response = jsonify({"error": "busy", "service": service, "capacity": guard.report()})
                        response.status_code = 503
                        response.headers["Retry-After"] = RETRY_AFTER_SECONDS
                        return response
                    try:
                        return view(*args, **kwargs)
                    except Exception as exc:
                        logger.exception("%s %s failed", service, label)
                        return _error(str(exc), 422)

            return wrapped

        return decorator

    @app.get("/health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "service": service,
                "role": "stage-worker",
                "stages": list(STAGES),
                "affinity": affinity,
                "capacity": guard.report(),
                "storage": storage.report(),
            }
        )

    @app.post("/v1/parse")
    @heavy("parse")
    def parse():
        return jsonify(parse_contours_stage(_file_bytes()).to_dict())

    @app.post("/v1/dem")
    @heavy("dem")
    def dem():
        body: Dict[str, Any] = request.get_json(force=True)
        contours = body.get("contours", body)
        payload = build_dem_stage(ParsedContoursPayload.from_dict(contours), body.get("params", {}))
        return jsonify(payload.to_dict())

    @app.post("/v1/prepare")
    @heavy("prepare")
    def prepare():
        """Parse contours and build the DEM, or build a global DEM around a point."""
        body = request.get_json(silent=True) or {}
        if body.get("global_dem"):
            point = body["global_dem"]
            contours, dem_result = global_dem_stage(float(point["lat"]), float(point["lon"]), body.get("params", {}))
            return jsonify({"contours": contours.to_dict(), "dem": dem_result.to_dict()})
        raw = _file_bytes()
        contours = parse_contours_stage(raw)
        del raw
        dem_result = build_dem_stage(contours, body.get("params", {}))
        return jsonify({"contours": contours.to_dict(), "dem": dem_result.to_dict()})

    @app.post("/v1/terrain")
    @heavy("terrain")
    def terrain():
        body: Dict[str, Any] = request.get_json(force=True)
        payload = analyze_terrain_stage(DEMPayload.from_dict(body["dem"]), body.get("params", {}))
        return jsonify(payload.to_dict())

    @app.post("/v1/rank")
    @heavy("rank")
    def rank():
        body = request.get_json(force=True)
        payload = rank_pond_sites_stage(TerrainPayload.from_dict(body["terrain"]), body.get("params", {}))
        return jsonify(payload.to_dict())

    @app.post("/v1/analyze")
    @heavy("analyze")
    def analyze():
        """Terrain derivatives and pond-site ranking in one stage call."""
        body = request.get_json(force=True)
        params = body.get("params", {})
        terrain_payload = analyze_terrain_stage(DEMPayload.from_dict(body["dem"]), params)
        ranking = rank_pond_sites_stage(terrain_payload, params)
        return jsonify({"terrain": terrain_payload.to_dict(), "ranking": ranking.to_dict()})

    @app.post("/v1/catchment")
    @heavy("catchment")
    def catchment():
        """Upstream catchment delineation and SCS-CN runoff for the top site."""
        body = request.get_json(force=True)
        result = delineate_catchment_stage(
            TerrainPayload.from_dict(body["terrain"]),
            PondRankingPayload.from_dict(body["ranking"]),
            body.get("params", {}),
        )
        return jsonify({"catchment": result.to_dict() if result is not None else None})

    @app.errorhandler(413)
    def too_large(_error):
        return _error("stage payload exceeds limit", 413)

    return app
