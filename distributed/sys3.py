"""sys3 Flask service: terrain analysis and pond site ranking."""

import logging
import os
from typing import Any, Dict

from flask import Flask, jsonify, request

from .stage_payloads import DEMPayload, TerrainPayload
from .stages import analyze_terrain_stage, rank_pond_sites_stage

logger = logging.getLogger(__name__)


def _error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def create_app() -> Flask:
    app = Flask("jalasetu-sys3")
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "sys3", "message": "sys3 is running"})

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

    @app.errorhandler(413)
    def too_large(_error):
        return _error("stage payload exceeds the 100 MB limit", 413)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("JALASETU_PORT", "3000")))
