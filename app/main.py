"""
FastAPI application entrypoint for Pond Catchment Analysis API.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import catchment
from app.models.schemas import HealthResponse

# OpenAPI Tag Metadata
tags_metadata = [
    {
        "name": "Catchment Analysis",
        "description": "Endpoints for contour map analysis, DEM generation, pond site ranking, and catchment delineation.",
    },
    {
        "name": "System",
        "description": "Operational health and diagnostic endpoints.",
    },
]

app = FastAPI(
    title="Pond Catchment Analysis API",
    description=(
        "A specialized geospatial backend for automated terrain analysis from contour maps (KML/KMZ).\n\n"
        "### Key Capabilities:\n"
        "- 🗺️ **Contour Parsing**: Multi-strategy extraction of 2D/3D elevation contours from `.kml` and `.kmz` files.\n"
        "- 🏔️ **DEM Construction**: Interpolates regular raster elevation surfaces in local UTM projections.\n"
        "- 📐 **Terrain Derivatives**: Computes finite-difference slopes, local depressions, and Topographic Position Index (TPI).\n"
        "- 💧 **Pond Siting**: Identifies, ranks, and calculates footprints for optimal farm pond excavation sites.\n"
        "- 🌊 **Catchment Delineation**: Traces upstream contributing watershed boundaries with hydrological flow routing."
    ),
    version="1.0.0",
    openapi_tags=tags_metadata,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for web frontend clients and local tooling
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Catchment Router at root (/analyzeContour) and under /catchment prefix
app.include_router(catchment.router, tags=["Catchment Analysis"])
app.include_router(catchment.router, prefix="/catchment", tags=["Catchment Analysis"], include_in_schema=False)


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Health check endpoint",
    description="Check if the backend server is running and healthy.",
)
async def health_check() -> HealthResponse:
    """
    Returns server operational status.
    """
    return HealthResponse(status="ok", message="Pond Catchment API is running")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
