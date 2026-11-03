"""Distributed JalaSetu services.

The package contains the four independently deployable services used by the
distributed deployment:

* ``sys1`` is the edge node: static frontend and the climate/rainfall API.
* ``sys2`` and ``sys3`` are stage workers that can run any heavy stage.
* ``sys4`` is the public gateway: job queue, capacity-aware scheduler, and a
  local fallback for any stage.

Stage payloads are deliberately JSON serialisable so a stage can move between
an in-process call and an HTTP call without changing the processing code.
Payload classes are imported lazily: the sys1 edge service imports this package
without GeoPandas installed.
"""

_PAYLOADS = (
    "CatchmentPayload",
    "DEMPayload",
    "ParsedContoursPayload",
    "PondRankingPayload",
    "TerrainPayload",
)

__all__ = list(_PAYLOADS)


def __getattr__(name):
    if name in _PAYLOADS:
        from . import stage_payloads

        return getattr(stage_payloads, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
