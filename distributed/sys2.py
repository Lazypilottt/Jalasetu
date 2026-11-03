"""sys2 stage worker. Ties go to sys2 for parsing/DEM and catchment delineation."""

import os

from flask import Flask

from app.telemetry import init_telemetry

from .worker import create_worker_app


def create_app() -> Flask:
    return create_worker_app("sys2", affinity=("prepare", "catchment"))


app = create_app()
init_telemetry(app=app, service_name=os.getenv("OTEL_SERVICE_NAME", "jalasetu-sys2-dem"))


if __name__ == "__main__":
    port = int(os.getenv("JALASETU_PORT", "3000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
