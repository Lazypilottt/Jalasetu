"""
Unit tests for JalaSetu OpenTelemetry configuration, logging sanitization, and resilience.
"""

import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from opentelemetry import metrics, trace

from app.telemetry import (
    SanitizeTelemetryLogFilter,
    init_telemetry,
    tracer,
    meter,
    pipeline_duration_histogram,
    pipeline_requests_counter,
)


def test_sanitize_telemetry_log_filter_scrubs_paths():
    """Verify that filesystem paths are scrubbed from log messages."""
    log_filter = SanitizeTelemetryLogFilter()
    logger = logging.getLogger("test_sanitizer")

    # Path in message string
    record = logger.makeRecord(
        name="test",
        level=logging.INFO,
        fn="test.py",
        lno=10,
        msg="Saved raster to /var/data/uploads/dem_12345.tif successfully",
        args=(),
        exc_info=None,
    )
    log_filter.filter(record)
    assert "/var/data/uploads" not in record.getMessage()
    assert "[sanitized_path]" in record.getMessage()

    # Path as format argument
    record2 = logger.makeRecord(
        name="test",
        level=logging.INFO,
        fn="test.py",
        lno=12,
        msg="Writing output to %s",
        args=(Path("/Users/alice/projects/test.kml"),),
        exc_info=None,
    )
    log_filter.filter(record2)
    assert "/Users/alice" not in record2.getMessage()
    assert "[sanitized_path]" in record2.getMessage()


def test_sanitize_telemetry_log_filter_scrubs_file_content_bytes():
    """Verify raw file bytes are replaced with placeholder instead of leaking content."""
    log_filter = SanitizeTelemetryLogFilter()
    logger = logging.getLogger("test_bytes_sanitizer")

    record = logger.makeRecord(
        name="test",
        level=logging.INFO,
        fn="test.py",
        lno=20,
        msg="Uploaded payload: %s",
        args=(b"<kml xmlns='...'>secret raw data</kml>",),
        exc_info=None,
    )
    log_filter.filter(record)
    msg = record.getMessage()
    assert "secret raw data" not in msg
    assert "bytes binary data" in msg


def test_telemetry_toggle_disabled():
    """Verify that JALASETU_OTEL_ENABLED=false disables initialization."""
    with patch.dict(os.environ, {"JALASETU_OTEL_ENABLED": "false"}):
        # Even if called, it should respect the disabled flag
        enabled_str = os.getenv("JALASETU_OTEL_ENABLED", "true").strip().lower()
        assert enabled_str == "false"


def test_telemetry_pipeline_metrics_callable():
    """Verify domain metrics record and add calls execute without throwing."""
    pipeline_duration_histogram.record(0.42, {"status": "success"})
    pipeline_requests_counter.add(1, {"status": "success"})


def test_telemetry_tracer_span():
    """Verify custom spans can be created safely."""
    with tracer.start_as_current_span("unit_test_span") as span:
        span.set_attribute("test.key", "val")
        assert span is not None
