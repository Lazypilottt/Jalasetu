"""
Rainfall API Router.

Provides endpoints to query multi-year precipitation, seasonal monsoon distributions,
and design storm parameters for farm-pond and watershed runoff modeling.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.models.schemas import RainfallResponse
from app.services.rainfall_service import RainfallService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Rainfall & Climate Analytics"])


class RainfallQueryPayload(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees")
    start_year: Optional[int] = Field(None, ge=1950, le=2050, description="Optional start year")
    end_year: Optional[int] = Field(None, ge=1950, le=2050, description="Optional end year")


@router.get(
    "",
    response_model=RainfallResponse,
    summary="Query location precipitation and design storm metrics",
    description=(
        "Retrieves multi-year historical precipitation data from Open-Meteo ERA5 Reanalysis "
        "and computes key hydrological parameters: mean annual precipitation, monsoon seasonal "
        "volume, 24-hr design storm for SCS-CN runoff, and monthly distribution."
    ),
)
async def get_rainfall(
    latitude: Optional[float] = Query(None, ge=-90.0, le=90.0, description="Latitude"),
    longitude: Optional[float] = Query(None, ge=-180.0, le=180.0, description="Longitude"),
    lat: Optional[float] = Query(None, ge=-90.0, le=90.0, description="Latitude alias"),
    lon: Optional[float] = Query(None, ge=-180.0, le=180.0, description="Longitude alias"),
    start_year: Optional[int] = Query(None, ge=1950, le=2050),
    end_year: Optional[int] = Query(None, ge=1950, le=2050),
) -> RainfallResponse:
    effective_lat = latitude if latitude is not None else lat
    effective_lon = longitude if longitude is not None else lon

    if effective_lat is None or effective_lon is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both 'latitude' and 'longitude' (or 'lat' and 'lon') query parameters are required.",
        )

    try:
        service = RainfallService()
        data = service.get_rainfall_data(
            latitude=effective_lat,
            longitude=effective_lon,
            start_year=start_year,
            end_year=end_year,
        )
        return RainfallResponse(**data)
    except Exception as exc:
        logger.exception("Rainfall query error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process rainfall query: {exc}",
        )


@router.post(
    "",
    response_model=RainfallResponse,
    summary="Query location precipitation (POST body)",
    description="POST alternative to query precipitation with a JSON body.",
)
async def post_rainfall(payload: RainfallQueryPayload) -> RainfallResponse:
    try:
        service = RainfallService()
        data = service.get_rainfall_data(
            latitude=payload.latitude,
            longitude=payload.longitude,
            start_year=payload.start_year,
            end_year=payload.end_year,
        )
        return RainfallResponse(**data)
    except Exception as exc:
        logger.exception("Rainfall query error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process rainfall query: {exc}",
        )
