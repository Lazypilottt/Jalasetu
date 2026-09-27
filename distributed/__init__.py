"""Distributed JalaSetu services.

The package contains the three independently deployable services used by the
distributed deployment:

* ``sys2`` parses contours and builds a DEM.
* ``sys3`` computes terrain metrics and ranks pond sites.
* ``sys4`` is the public gateway and performs catchment delineation.

Stage payloads are deliberately JSON serialisable so a service can be moved
from an in-process call to an HTTP call without changing the processing code.
"""

from .stage_payloads import (
    CatchmentPayload,
    DEMPayload,
    ParsedContoursPayload,
    PondRankingPayload,
    TerrainPayload,
)

__all__ = [
    "CatchmentPayload",
    "DEMPayload",
    "ParsedContoursPayload",
    "PondRankingPayload",
    "TerrainPayload",
]
