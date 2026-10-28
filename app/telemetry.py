"""
OpenTelemetry Configuration and Observability Setup for JalaSetu.

Provides:
- Distributed traces, metrics, and logs exported via OTLP (gRPC) to grafana/otel-lgtm.
- Configurable through environment variables:
    * OTEL_SERVICE_NAME: logical service identifier (default: 'jalasetu')
    * OTEL_EXPORTER_OTLP_ENDPOINT: collector address (default: 'localhost:4317')
    * JALASETU_OTEL_ENABLED: master toggle (default: 'true')
- Privacy-safe logging filter: strictly prevents logging uploaded file contents or filesystem paths.
- Resilient non-blocking behavior: application continues functioning normally even if collector is down.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from opentelemetry import _logs, metrics, trace
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)

_initialized = False

# Module-level Tracer and Meter singletons (gracefully fallback to NoOp if uninitialized)
tracer = trace.get_tracer("jalasetu")
meter = metrics.get_meter("jalasetu")

# Pre-defined domain metrics for pipeline operations
pipeline_duration_histogram = meter.create_histogram(
    name="jalasetu.pipeline.duration_seconds",
    unit="s",
    description="Duration of terrain analysis pipeline execution in seconds",
)

pipeline_requests_counter = meter.create_counter(
    name="jalasetu.pipeline.requests_total",
    description="Total count of pipeline analysis requests by status",
)

stage_duration_histogram = meter.create_histogram(
    name="jalasetu.stage.duration_seconds",
    unit="s",
    description="Duration of individual pipeline stages in seconds",
)

candidate_sites_histogram = meter.create_histogram(
    name="jalasetu.pond_candidates.count",
    description="Number of candidate pond sites found per run",
)

catchment_area_histogram = meter.create_histogram(
    name="jalasetu.catchment.area_m2",
    unit="m2",
    description="Delineated upstream catchment area in square meters",
)


class TraceContextFilter(logging.Filter):
    """
    Ensures every LogRecord carries trace_id and span_id formatted as standard hex strings.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        if ctx and ctx.is_valid:
            record.trace_id = format(ctx.trace_id, "032x")
            record.span_id = format(ctx.span_id, "016x")
        else:
            record.trace_id = "0" * 32
            record.span_id = "0" * 16
        return True


class SanitizeTelemetryLogFilter(logging.Filter):
    """
    Ensures OpenTelemetry logs never export filesystem paths or raw uploaded file contents.
    """
    PATH_PATTERN = re.compile(r'(?:/(?:[a-zA-Z0-9_\.\-]+/)+[a-zA-Z0-9_\.\-]+|[a-zA-Z]:\\[^\s]+)')

    def _sanitize(self, val: Any) -> Any:
        if isinstance(val, (bytes, bytearray)):
            return f"<{len(val)} bytes binary data>"
        if isinstance(val, (str, Path)):
            return self.PATH_PATTERN.sub("[sanitized_path]", str(val))
        return val

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = self.PATH_PATTERN.sub("[sanitized_path]", record.msg)
            elif isinstance(record.msg, (bytes, bytearray)):
                record.msg = f"<{len(record.msg)} bytes binary data>"

            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: self._sanitize(v) for k, v in record.args.items()}
                elif isinstance(record.args, (list, tuple)):
                    record.args = tuple(self._sanitize(v) for v in record.args)
        except Exception:
            pass
        return True


def _instrument_framework(app: Optional[Any] = None) -> None:
    try:
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        if not RequestsInstrumentor().is_instrumented_by_opentelemetry:
            RequestsInstrumentor().instrument()
    except Exception as exc:
        logger.warning("Failed to instrument requests with OpenTelemetry: %s", exc)

    if app is None:
        return
    try:
        # FastAPI / Starlette
        if hasattr(app, "openapi"):
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app)
        # Flask / WSGI
        elif hasattr(app, "wsgi_app"):
            from opentelemetry.instrumentation.flask import FlaskInstrumentor
            FlaskInstrumentor().instrument_app(app)
    except Exception as exc:
        logger.warning("Failed to instrument application framework with OpenTelemetry: %s", exc)


def init_telemetry(app: Optional[Any] = None, service_name: Optional[str] = None) -> bool:
    """
    Initialize OpenTelemetry traces, metrics, and logs with OTLP gRPC export.

    Configuration via environment variables:
      - JALASETU_OTEL_ENABLED: "true" (default) or "false"
      - OTEL_SERVICE_NAME: service name string (default: "jalasetu")
      - OTEL_EXPORTER_OTLP_ENDPOINT: gRPC endpoint (default: "localhost:4317")
    """
    global _initialized

    enabled_str = os.getenv("JALASETU_OTEL_ENABLED", "true").strip().lower()
    if enabled_str in ("false", "0", "no", "off", "disable", "disabled"):
        logger.info("OpenTelemetry is disabled via JALASETU_OTEL_ENABLED.")
        return False

    if _initialized:
        _instrument_framework(app)
        return True

    effective_service_name = os.getenv("OTEL_SERVICE_NAME", service_name or "jalasetu")
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317")

    insecure_env = os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "").strip().lower()
    if insecure_env in ("false", "0", "no"):
        insecure = False
    elif insecure_env in ("true", "1", "yes"):
        insecure = True
    else:
        insecure = not endpoint.startswith("https://")

    try:
        resource = Resource.create({SERVICE_NAME: effective_service_name})

        # 1. Traces
        tracer_provider = TracerProvider(resource=resource)
        span_exporter = OTLPSpanExporter(endpoint=endpoint, insecure=insecure)
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
        trace.set_tracer_provider(tracer_provider)

        # 2. Metrics
        metric_exporter = OTLPMetricExporter(endpoint=endpoint, insecure=insecure)
        metric_reader = PeriodicExportingMetricReader(
            metric_exporter,
            export_interval_millis=15000,
        )
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(meter_provider)

        # 3. Logs
        log_exporter = OTLPLogExporter(endpoint=endpoint, insecure=insecure)
        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
        _logs.set_logger_provider(logger_provider)

        logging_handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
        logging_handler.addFilter(SanitizeTelemetryLogFilter())
        logging_handler.addFilter(TraceContextFilter())
        root_logger = logging.getLogger()
        root_logger.addHandler(logging_handler)
        root_logger.addFilter(TraceContextFilter())

        # Ensure existing stream handlers format trace_id and span_id
        trace_formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [trace_id=%(trace_id)s span_id=%(span_id)s] %(name)s: %(message)s"
        )
        for h in root_logger.handlers:
            h.addFilter(TraceContextFilter())
            h.addFilter(SanitizeTelemetryLogFilter())
            if not isinstance(h, LoggingHandler):
                h.setFormatter(trace_formatter)

        _initialized = True
        logger.info(
            "OpenTelemetry initialized: service='%s', endpoint='%s' (insecure=%s)",
            effective_service_name,
            endpoint,
            insecure,
        )
    except Exception as exc:
        logger.warning(
            "Failed to initialize OpenTelemetry providers (service will run without OTLP export): %s",
            exc,
        )
        return False

    _instrument_framework(app)
    return True
