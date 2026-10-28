"""
OpenTelemetry metrics definitions for JalaSetu.
Meter: "jalasetu"
"""

from opentelemetry import metrics

meter = metrics.get_meter("jalasetu")

# Counter jalasetu.analyses.total (attr status=success|error)
analyses_total = meter.create_counter(
    name="jalasetu.analyses.total",
    description="Total count of contour analyses completed by status",
    unit="1",
)

# Counter jalasetu.pysheds.fallback.total
pysheds_fallback_total = meter.create_counter(
    name="jalasetu.pysheds.fallback.total",
    description="Total count of Pysheds fallbacks to native D8 routing",
    unit="1",
)

# Histogram jalasetu.analysis.duration (s)
analysis_duration = meter.create_histogram(
    name="jalasetu.analysis.duration",
    description="Total duration of contour analysis in seconds",
    unit="s",
)

# Histogram jalasetu.stage.duration (s, attr stage)
stage_duration = meter.create_histogram(
    name="jalasetu.stage.duration",
    description="Duration of individual pipeline stages in seconds",
    unit="s",
)

# Histogram jalasetu.runoff.volume (m3)
runoff_volume = meter.create_histogram(
    name="jalasetu.runoff.volume",
    description="Estimated runoff volume in cubic meters",
    unit="m3",
)
