"""sys3 Flask worker service: terrain analysis, pond ranking, and backup contour parsing."""

import base64
import logging
import os
from typing import Any, Dict

from flask import Flask, jsonify, request

from .stage_payloads import DEMPayload, ParsedContoursPayload, TerrainPayload
from .stages import (
    analyze_terrain_stage,
    build_dem_stage,
    parse_contours_stage,
    rank_pond_sites_stage,
)

logger = logging.getLogger(__name__)


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


def create_app() -> Flask:
    app = Flask("jalasetu-sys3")
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "sys3", "role": "primary-ranking,backup-parsing"})

    # --- Primary Stage 2: Terrain Analysis & Pond Ranking ---
    @app.post("/v1/terrain")
    def terrain():
        try:
            body: Dict[str, Any] = request.get_json(force=True)
            payload = analyze_terrain_stage(
                DEMPayload.from_dict(body["dem"]),
                body.get("params", {}),
            )
            return jsonify(payload.to_dict())
        except Exception as exc:
            logger.exception("sys3 terrain analysis failed")
            return _error(str(exc), 422)

    @app.post("/v1/rank")
    def rank():
        try:
            body = request.get_json(force=True)
            terrain_payload = TerrainPayload.from_dict(body["terrain"])
            payload = rank_pond_sites_stage(terrain_payload, body.get("params", {}))
            return jsonify(payload.to_dict())
        except Exception as exc:
            logger.exception("sys3 pond ranking failed")
            return _error(str(exc), 422)

    @app.post("/v1/analyze")
    def analyze():
        """Atomic terrain analysis and pond site ranking stage."""
        try:
            body = request.get_json(force=True)
            terrain_payload = analyze_terrain_stage(
                DEMPayload.from_dict(body["dem"]),
                body.get("params", {}),
            )
            ranking = rank_pond_sites_stage(terrain_payload, body.get("params", {}))
            return jsonify({"terrain": terrain_payload.to_dict(), "ranking": ranking.to_dict()})
        except Exception as exc:
            logger.exception("sys3 analysis failed")
            return _error(str(exc), 422)

    # --- Backup / Redundancy Stage 1: Parsing & DEM Generation ---
    @app.post("/v1/parse")
    def parse():
        try:
            payload = parse_contours_stage(_file_bytes())
            return jsonify(payload.to_dict())
        except Exception as exc:
            logger.exception("sys3 parse fallback failed")
            return _error(str(exc), 422)

    @app.post("/v1/dem")
    def dem():
        try:
            body: Dict[str, Any] = request.get_json(force=True)
            contours = body.get("contours", body)
            payload = build_dem_stage(
                ParsedContoursPayload.from_dict(contours),
                body.get("params", {}),
            )
            return jsonify(payload.to_dict())
        except Exception as exc:
            logger.exception("sys3 DEM fallback failed")
            return _error(str(exc), 422)

    @app.post("/v1/prepare")
    def prepare():
        try:
            raw = _file_bytes()
            body = request.get_json(silent=True) or {}
            contours = parse_contours_stage(raw)
            dem_result = build_dem_stage(contours, body.get("params", {}))
            return jsonify({"contours": contours.to_dict(), "dem": dem_result.to_dict()})
        except Exception as exc:
            logger.exception("sys3 prepare fallback failed")
            return _error(str(exc), 422)

    @app.errorhandler(413)
    def too_large(_error):
        return _error("stage payload exceeds limit", 413)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("JALASETU_PORT", "3000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
