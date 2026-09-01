"""
Catchment and Contour Analysis API Routes.

Provides:
  - POST /analyzeContour: Upload KML/KMZ contour maps to perform terrain analysis,
                          rank candidate pond sites, and delineate upstream catchments.
  - GET  /analyzeContour/schema: Returns documentation, schema metadata, and example payloads.
"""

import logging
import os
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse

from app.models.schemas import CatchmentResponse, HealthResponse
from app.services.pipeline import analyze_contour_file, DEFAULT_PIPELINE_PARAMS

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/analyzeContour",
    response_model=CatchmentResponse,
    summary="Analyze contour map and delineate farm pond catchment",
    description=(
        "Upload a KML or KMZ contour map file to execute the complete terrain analysis workflow:\n\n"
        "1. **KML/KMZ Parsing**: Extract contour lines and Z-elevation values.\n"
        "2. **DEM Generation**: Reproject to local UTM and interpolate a continuous elevation grid.\n"
        "3. **Terrain Analysis**: Compute slope gradient, topographic depressions, and suitability scores.\n"
        "4. **Pond Siting**: Segment contiguous regions and rank optimal farm pond locations.\n"
        "5. **Catchment Delineation**: Delineate upstream contributing watershed draining to the recommended pond site.\n\n"
        "Returns the complete analysis in standard WGS84 coordinates (EPSG:4326) with GeoJSON boundary polygons."
    ),
    responses={
        200: {
            "description": "Contour analysis completed successfully, or valid analysis with no suitable sites found.",
            "model": CatchmentResponse,
        },
        400: {
            "description": "Invalid file format, empty file, corrupted archive, or invalid parameter bounds.",
            "content": {"application/json": {"example": {"detail": "Uploaded file is corrupted or not a valid KML/KMZ."}}},
        },
        422: {
            "description": "Unprocessable contour data (e.g. no elevation attributes found in features).",
            "content": {"application/json": {"example": {"detail": "No valid contour features with elevation data could be extracted."}}},
        },
        500: {
            "description": "Internal server error during terrain computation.",
            "content": {"application/json": {"example": {"detail": "An internal error occurred while processing the terrain data."}}},
        },
    },
)
@router.post(
    "/findCatchment",
    response_model=CatchmentResponse,
    summary="Find pond sites and delineate catchment (alias for /analyzeContour)",
    description="Alias endpoint for `/analyzeContour`.",
    responses={
        200: {
            "description": "Contour analysis completed successfully, or valid analysis with no suitable sites found.",
            "model": CatchmentResponse,
        },
        400: {
            "description": "Invalid file format, empty file, corrupted archive, or invalid parameter bounds.",
            "content": {"application/json": {"example": {"detail": "Uploaded file is corrupted or not a valid KML/KMZ."}}},
        },
        422: {
            "description": "Unprocessable contour data (e.g. no elevation attributes found in features).",
            "content": {"application/json": {"example": {"detail": "No valid contour features with elevation data could be extracted."}}},
        },
        500: {
            "description": "Internal server error during terrain computation.",
            "content": {"application/json": {"example": {"detail": "An internal error occurred while processing the terrain data."}}},
        },
    },
)
async def analyze_contour(
    file: UploadFile = File(..., description="KML (.kml) or KMZ (.kmz) file containing elevation contour lines"),
    # --- Tunable Pipeline Overrides ---
    dem_resolution_m: Optional[float] = Form(
        None, ge=0.5, le=100.0, description="DEM raster grid resolution in meters (e.g. 5.0m). Auto-derived if omitted."
    ),
    sample_spacing_m: Optional[float] = Form(
        None, ge=0.5, le=100.0, description="Contour sampling interval in meters. Defaults to resolution / 2."
    ),
    ideal_slope_deg: Optional[float] = Form(
        3.0, ge=0.0, le=45.0, description="Ideal maximum ground slope in degrees for pond excavation (defaults to 3.0°)."
    ),
    max_slope_deg: Optional[float] = Form(
        8.0, ge=1.0, le=60.0, description="Upper allowable ground slope limit in degrees (defaults to 8.0°)."
    ),
    neighborhood_radius_m: Optional[float] = Form(
        None, ge=5.0, le=500.0, description="Neighborhood filter radius in meters for local depression detection."
    ),
    weight_slope: Optional[float] = Form(
        0.35, ge=0.0, le=1.0, description="Relative weight for slope criterion in composite suitability score (0-1)."
    ),
    weight_depression: Optional[float] = Form(
        0.35, ge=0.0, le=1.0, description="Relative weight for local depression criterion in composite suitability score (0-1)."
    ),
    weight_twi: Optional[float] = Form(
        0.30, ge=0.0, le=1.0, description="Relative weight for Topographic Wetness Index (TWI) in composite score (0-1)."
    ),
    suitability_threshold: Optional[float] = Form(
        60.0, ge=0.0, le=100.0, description="Minimum suitability score threshold (0-100) for candidate pond sites."
    ),
    min_pond_area_m2: Optional[float] = Form(
        200.0, ge=10.0, le=1000000.0, description="Minimum contiguous footprint in square meters for a viable pond."
    ),
    max_pond_area_m2: Optional[float] = Form(
        None, ge=50.0, le=10000000.0, description="Optional maximum allowable pond footprint in square meters."
    ),
    max_candidate_sites: Optional[int] = Form(
        5, ge=1, le=20, description="Maximum number of ranked candidate pond sites to return."
    ),
    max_elongation_ratio: Optional[float] = Form(
        3.5, ge=1.0, le=50.0, description="Maximum allowable major-to-minor axis elongation ratio (rejects linear road/channel corridors, defaults to 3.5)."
    ),
    min_pond_width_m: Optional[float] = Form(
        None, ge=1.0, le=500.0, description="Minimum allowable pond width in meters (derived from DEM cell size if omitted)."
    ),
    pond_design_depth_m: Optional[float] = Form(
        2.0, ge=0.5, le=10.0, description="Design water depth in meters for pond volumetric storage capacity."
    ),
    snap_radius_m: Optional[float] = Form(
        25.0, ge=0.0, le=200.0, description="Search radius in meters to snap pour point to stream channel."
    ),
    use_pysheds: Optional[bool] = Form(
        True, description="Attempt pysheds hydrological flow accumulation first (falls back to native D8)."
    ),
    design_rainfall_mm: Optional[float] = Form(
        100.0, ge=5.0, le=1000.0, description="24-hr design storm precipitation in mm for SCS-CN runoff volume estimation."
    ),
    curve_number: Optional[float] = Form(
        75.0, ge=30.0, le=98.0, description="SCS Runoff Curve Number for hydrological modeling."
    ),
) -> CatchmentResponse:
    """
    Execute contour analysis pipeline on uploaded KML/KMZ file.
    """
    # 1. Validate file extension
    filename = file.filename or "upload"
    ext = Path(filename).suffix.lower()
    if ext not in (".kml", ".kmz"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Only .kml and .kmz contour files are supported.",
        )

    # 2. Validate parameter constraints
    if max_slope_deg is not None and ideal_slope_deg is not None and max_slope_deg <= ideal_slope_deg:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"max_slope_deg ({max_slope_deg}°) must be strictly greater than ideal_slope_deg ({ideal_slope_deg}°).",
        )

    # 3. Save uploaded file to temporary location and validate integrity
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    temp_path = Path(temp_file.name)

    try:
        shutil.copyfileobj(file.file, temp_file)
        temp_file.flush()
        temp_file.close()

        file_size = temp_path.stat().st_size
        if file_size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty (0 bytes).",
            )

        # Integrity check for KMZ (must be valid zip archive containing .kml)
        if ext == ".kmz":
            if not zipfile.is_zipfile(temp_path):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Uploaded KMZ file is corrupted or not a valid ZIP archive.",
                )
            with zipfile.ZipFile(temp_path, "r") as zf:
                kml_entries = [n for n in zf.namelist() if n.lower().endswith(".kml")]
                if not kml_entries:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="The uploaded KMZ archive does not contain any .kml files.",
                    )

        # Integrity check for KML (must be parseable XML)
        elif ext == ".kml":
            try:
                with open(temp_path, "rb") as f:
                    ET.fromstring(f.read())
            except ET.ParseError as xml_err:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Uploaded KML contains invalid XML syntax: {xml_err}",
                )

        # 4. Construct parameters dictionary
        params: Dict[str, Any] = {
            "dem_resolution_m": dem_resolution_m,
            "sample_spacing_m": sample_spacing_m,
            "ideal_slope_deg": ideal_slope_deg,
            "max_slope_deg": max_slope_deg,
            "neighborhood_radius_m": neighborhood_radius_m,
            "weight_slope": weight_slope,
            "weight_depression": weight_depression,
            "weight_twi": weight_twi,
            "suitability_threshold": suitability_threshold,
            "min_pond_area_m2": min_pond_area_m2,
            "max_pond_area_m2": max_pond_area_m2,
            "max_candidate_sites": max_candidate_sites,
            "max_elongation_ratio": max_elongation_ratio,
            "min_pond_width_m": min_pond_width_m,
            "pond_design_depth_m": pond_design_depth_m,
            "snap_radius_m": snap_radius_m,
            "use_pysheds": use_pysheds,
            "design_rainfall_mm": design_rainfall_mm,
            "curve_number": curve_number,
        }

        # 5. Execute pipeline
        try:
            response = analyze_contour_file(file_source=temp_path, params=params)
        except Exception as e:
            logger.exception("Unhandled server exception during analyze_contour_file: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An internal error occurred while processing the terrain data. Please check server logs.",
            )

        # Handle specific pipeline failure statuses
        if response.status == "error":
            logger.warning("Pipeline reported unprocessable input: %s", response.message)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=response.message or "Could not extract or process contour features from the input file.",
            )

        return response

    finally:
        # Clean up temporary file
        if temp_path.exists():
            try:
                os.unlink(temp_path)
            except OSError as cleanup_err:
                logger.debug("Failed to delete temp file %s: %s", temp_path, cleanup_err)


@router.get(
    "/analyzeContour/schema",
    summary="Get response schema and example payload",
    description="Returns the OpenAPI schema definition and sample payload for CatchmentResponse.",
    tags=["Catchment Analysis"],
)
async def get_response_schema():
    """
    Returns the JSON schema and sample response documentation for the /analyzeContour endpoint.
    """
    schema = CatchmentResponse.model_json_schema()
    example = CatchmentResponse.model_config.get("json_schema_extra", {}).get("example", {})
    return {
        "title": "CatchmentResponse Schema Documentation",
        "description": "Standardized schema for terrain analysis and catchment delineation output",
        "schema": schema,
        "example": example,
        "default_parameters": DEFAULT_PIPELINE_PARAMS,
    }
