"""Location recommendation API."""

from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from app.services.location_search import recommend_locations

router = APIRouter()


def _search(latitude: float, longitude: float, category: str, radius: float, link_text: Optional[str]) -> list[str]:
    if not category.strip():
        raise HTTPException(status_code=422, detail="cat must not be empty")
    if radius < 0:
        raise HTTPException(status_code=422, detail="rad must be non-negative")
    try:
        return recommend_locations(latitude, longitude, category, radius, link_text)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/IP/search/",
    response_model=list[str],
    summary="Recommend the ten closest locations",
)
async def search_locations(
    lat: float = Form(...),
    long: float = Form(...),
    cat: str = Form(...),
    rad: float = Form(..., ge=0),
    link: Optional[UploadFile] = File(None),
) -> list[str]:
    link_text = None
    if link is not None:
        link_text = (await link.read()).decode("utf-8")
    return _search(lat, long, cat, rad, link_text)


@router.get(
    "/IP/search/",
    response_model=list[str],
    include_in_schema=True,
    summary="Recommend the ten closest locations",
)
def search_locations_query(
    lat: float = Query(...),
    long: float = Query(...),
    cat: str = Query(...),
    rad: float = Query(..., ge=0),
) -> list[str]:
    return _search(lat, long, cat, rad, None)
