"""sys2 Flask service: contour parsing and DEM construction."""

import base64
import logging
import os
from typing import Any, Dict

from flask import Flask, jsonify, request

from .stage_payloads import ParsedContoursPayload
from .stages import build_dem_stage, parse_contours_stage

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
    app = Flask("jalasetu-sys2")
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "sys2", "message": "sys2 is running"})

    @app.post("/v1/parse")
    def parse():
        try:
            payload = parse_contours_stage(_file_bytes())
            return jsonify(payload.to_dict())
        except Exception as exc:
            logger.exception("sys2 parse failed")
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
            logger.exception("sys2 DEM build failed")
            return _error(str(exc), 422)

    @app.post("/v1/prepare")
    def prepare():
        """Parse and build in one call, useful for the gateway's normal path."""
        try:
            raw = _file_bytes()
            body = request.get_json(silent=True) or {}
            contours = parse_contours_stage(raw)
            dem = build_dem_stage(contours, body.get("params", {}))
            return jsonify({"contours": contours.to_dict(), "dem": dem.to_dict()})
        except Exception as exc:
            logger.exception("sys2 prepare failed")
            return _error(str(exc), 422)

    @app.errorhandler(413)
    def too_large(_error):
        return _error("uploaded file exceeds the 50 MB limit", 413)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("JALASETU_PORT", "3000")))
