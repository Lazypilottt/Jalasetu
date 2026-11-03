"""
Existing-infrastructure API Router.

Lets the frontend preview the mapped rivers, tanks, buildings, schools and
roads around a point before running an analysis; the same lookup feeds the
siting exclusions.
"""

from fastapi import APIRouter, Query
from starlette.concurrency import run_in_threadpool

from app.services.infrastructure import fetch_infrastructure

router = APIRouter(tags=["Existing Infrastructure"])


@router.get(
    "",
    summary="Mapped infrastructure around a point",
    description=(
        "Returns OpenStreetMap features that a farm pond must avoid (water bodies, waterways, "
        "buildings, schools/hospitals/places of worship, roads, railways, residential areas, wells), "
        "classified into categories with default safety buffers. A failed lookup returns "
        "status='unavailable' instead of an error."
    ),
)
async def get_infrastructure(
    lat: float = Query(..., ge=-90.0, le=90.0, description="Latitude"),
    lon: float = Query(..., ge=-180.0, le=180.0, description="Longitude"),
    radius_m: float = Query(400.0, ge=50.0, le=3000.0, description="Search radius in metres"),
):
    return await run_in_threadpool(fetch_infrastructure, lat, lon, radius_m)
