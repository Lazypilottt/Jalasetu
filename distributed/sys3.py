"""sys3 stage worker. Ties go to sys3 for terrain analysis and pond ranking."""

import os

from flask import Flask

from app.telemetry import init_telemetry

from .worker import create_worker_app


def create_app() -> Flask:
    return create_worker_app("sys3", affinity=("analyze",))


app = create_app()
init_telemetry(app=app, service_name=os.getenv("OTEL_SERVICE_NAME", "jalasetu-sys3-terrain"))


if __name__ == "__main__":
    port = int(os.getenv("JALASETU_PORT", "3000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
