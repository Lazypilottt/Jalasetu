"""
Pydantic Request and Response Models for Pond Catchment Analysis API.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response schema."""
    status: str = Field(..., examples=["ok"], description="Server operational status ('ok')")
    message: str = Field(..., examples=["Pond Catchment API is running"], description="Status message")


class GeoJSONGeometry(BaseModel):
    """Standard GeoJSON geometry object."""
    type: str = Field(..., examples=["Polygon"], description="Geometry type (e.g. 'Polygon', 'MultiPolygon')")
    coordinates: List[Any] = Field(..., description="GeoJSON coordinates array in EPSG:4326 [Longitude, Latitude]")


class GeoJSONFeature(BaseModel):
    """Standard GeoJSON Feature object."""
    type: str = Field(default="Feature", description="GeoJSON type ('Feature')")
    geometry: GeoJSONGeometry = Field(..., description="Feature geometry")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Feature attributes and metadata")


class GeoJSONFeatureCollection(BaseModel):
    """Standard GeoJSON FeatureCollection."""
    type: str = Field(default="FeatureCollection", description="GeoJSON type ('FeatureCollection')")
    features: List[GeoJSONFeature] = Field(default_factory=list, description="Array of GeoJSON Features")


class InputSummary(BaseModel):
    """Summary of parsed contour input dataset and interpolated DEM."""
    num_contours: int = Field(..., examples=[34], description="Total number of contour features extracted from KML/KMZ")
    elevation_min: float = Field(..., examples=[420.0], description="Minimum elevation found in contour lines (meters)")
    elevation_max: float = Field(..., examples=[480.0], description="Maximum elevation found in contour lines (meters)")
    dem_resolution_m: float = Field(..., examples=[5.0], description="Interpolated DEM raster cell resolution (meters/pixel)")
    utm_crs: Optional[str] = Field(None, examples=["EPSG:32643"], description="Auto-detected local UTM Projected CRS")


class PondSiteSummary(BaseModel):
    """Attributes, centroid coordinates, and region boundary for an identified candidate pond location."""
    site_id: str = Field(..., examples=["site_1"], description="Unique identifier for the candidate site")
    rank: int = Field(..., examples=[1], description="Suitability rank (1 = highest recommended site)")
    latitude: float = Field(..., examples=[28.553412], description="Centroid Latitude in WGS84 decimal degrees")
    longitude: float = Field(..., examples=[77.112845], description="Centroid Longitude in WGS84 decimal degrees")
    elevation_m: float = Field(..., examples=[431.25], description="Average ground elevation at pond site (meters)")
    suitability_score: float = Field(..., examples=[91.4], ge=0.0, le=100.0, description="Composite terrain suitability score (0-100)")
    area_m2: float = Field(..., examples=[1450.0], description="Contiguous excavation footprint area (square meters)")
    slope_deg: Optional[float] = Field(None, examples=[1.85], description="Average terrain slope at site (degrees)")
    storage_capacity_m3: Optional[float] = Field(None, examples=[2175.0], description="Estimated water storage capacity at design depth (m³)")
    cut_volume_m3: Optional[float] = Field(None, examples=[1800.0], description="Estimated earthwork excavation cut volume (m³)")
    storage_efficiency_ratio: Optional[float] = Field(None, examples=[1.21], description="Storage-to-excavation earthwork efficiency ratio")
    mean_twi: Optional[float] = Field(None, examples=[8.45], description="Mean Topographic Wetness Index (TWI) across pond footprint")
    composite_mcdm_score: Optional[float] = Field(None, examples=[88.7], description="Composite Multi-Criteria Decision Making (MCDM) score (0-100)")
    stage_storage_curve: Optional[List[Dict[str, Any]]] = Field(None, description="Stage-Storage-Area depth increments")
    boundary_geojson: Optional[Dict[str, Any]] = Field(
        None,
        description="Suitability region boundary polygon in standard WGS84 GeoJSON FeatureCollection format",
    )


class ElevationRange(BaseModel):
    """Elevation relief metrics across the catchment basin."""
    min_m: float = Field(..., examples=[431.2], description="Lowest elevation point in catchment (meters)")
    max_m: float = Field(..., examples=[478.5], description="Highest ridge elevation in catchment (meters)")
    relief_m: float = Field(..., examples=[47.3], description="Total basin elevation relief span (max - min) (meters)")


class CatchmentSummary(BaseModel):
    """Delineated upstream catchment / watershed metrics and boundary geometry."""
    boundary_geojson: Optional[Dict[str, Any]] = Field(
        None, description="Catchment boundary polygon in standard WGS84 GeoJSON FeatureCollection format"
    )
    area_m2: float = Field(..., examples=[184500.0], description="Catchment contributing drainage area (square meters)")
    area_hectares: float = Field(..., examples=[18.45], description="Catchment contributing drainage area (hectares)")
    average_slope_deg: float = Field(..., examples=[4.82], description="Mean ground slope across the catchment (degrees)")
    elevation_range_m: ElevationRange = Field(..., description="Elevation range within the catchment")
    delineation_method: str = Field(
        ...,
        examples=["flow_accumulation"],
        description="Hydrological routing engine used ('flow_accumulation' via pysheds or 'basin_approximation' via native D8 BFS)",
    )
    catchment_to_pond_ratio: Optional[float] = Field(None, examples=[12.7], description="Upstream catchment area divided by pond footprint area")
    hydrological_feasibility: Optional[str] = Field(None, examples=["optimal"], description="Sizing feasibility ('optimal', 'low_yield_risk', 'high_flow_excess')")
    feasibility_explanation: Optional[str] = Field(None, description="Plain-language engineering explanation of catchment sizing")
    estimated_runoff_volume_m3: Optional[float] = Field(None, examples=[7380.0], description="Estimated storm runoff volume yield via SCS-CN method (m³)")
    design_rainfall_mm: Optional[float] = Field(None, examples=[100.0], description="Design 24-hr storm precipitation in mm")
    curve_number: Optional[float] = Field(None, examples=[75.0], description="SCS Runoff Curve Number used")
    mean_ls_factor: Optional[float] = Field(None, examples=[2.14], description="Catchment average RUSLE topographic LS erosion factor")
    siltation_risk: Optional[str] = Field(None, examples=["low"], description="Catchment erosion and pond siltation risk rating ('low', 'moderate', 'high')")
    siltation_explanation: Optional[str] = Field(None, description="Erosion risk explanation and soil conservation advice")
    water_filling_factor: Optional[float] = Field(None, examples=[3.39], description="Ratio of storm runoff volume to pond storage capacity")


class CatchmentResponse(BaseModel):
    """Master response payload for contour terrain & pond catchment analysis."""
    status: str = Field(
        ...,
        examples=["success"],
        description="Execution status ('success', 'no_suitable_site', 'partial_success', 'error')",
    )
    message: Optional[str] = Field(
        None,
        examples=["Contour analysis and pond catchment delineation completed successfully."],
        description="Summary explanation of analysis results",
    )
    input_summary: Optional[InputSummary] = Field(
        None, description="Summary of parsed contour inputs and DEM metadata"
    )
    recommended_site: Optional[PondSiteSummary] = Field(
        None, description="Top-ranked recommended pond site (#1)"
    )
    alternative_sites: List[PondSiteSummary] = Field(
        default_factory=list, description="Ranked alternative candidate pond sites"
    )
    catchment: Optional[CatchmentSummary] = Field(
        None, description="Delineated upstream catchment contributing to recommended pond site"
    )
    processing_notes: List[str] = Field(
        default_factory=list,
        examples=[
            [
                "Parsed 34 contour lines with elevations ranging from 420.0m to 480.0m.",
                "Generated DEM grid: 340x280 cells at 5.0m resolution in EPSG:32643.",
                "Selected top recommended pond site (site_1): score=91.4, area=1450m².",
                "Delineated upstream catchment using flow_accumulation: area=18.45 ha.",
            ]
        ],
        description="Execution logs, parameter choices, skipped features, and warnings",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "success",
                "message": "Contour analysis and pond catchment delineation completed successfully.",
                "input_summary": {
                    "num_contours": 34,
                    "elevation_min": 420.0,
                    "elevation_max": 480.0,
                    "dem_resolution_m": 5.0,
                    "utm_crs": "EPSG:32643",
                },
                "recommended_site": {
                    "site_id": "site_1",
                    "rank": 1,
                    "latitude": 28.553412,
                    "longitude": 77.112845,
                    "elevation_m": 431.25,
                    "suitability_score": 91.4,
                    "area_m2": 1450.0,
                    "slope_deg": 1.85,
                    "boundary_geojson": {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "geometry": {
                                    "type": "Polygon",
                                    "coordinates": [[[77.111, 28.552], [77.114, 28.552], [77.114, 28.555], [77.111, 28.555], [77.111, 28.552]]],
                                },
                                "properties": {"site_id": "site_1", "rank": 1, "area_m2": 1450.0},
                            }
                        ],
                    },
                },
                "alternative_sites": [
                    {
                        "site_id": "site_2",
                        "rank": 2,
                        "latitude": 28.558901,
                        "longitude": 77.118930,
                        "elevation_m": 438.50,
                        "suitability_score": 86.2,
                        "area_m2": 875.0,
                        "slope_deg": 2.40,
                        "boundary_geojson": {
                            "type": "FeatureCollection",
                            "features": [
                                {
                                    "type": "Feature",
                                    "geometry": {
                                        "type": "Polygon",
                                        "coordinates": [[[77.117, 28.557], [77.120, 28.557], [77.120, 28.560], [77.117, 28.560], [77.117, 28.557]]],
                                    },
                                    "properties": {"site_id": "site_2", "rank": 2, "area_m2": 875.0},
                                }
                            ],
                        },
                    }
                ],
                "catchment": {
                    "boundary_geojson": {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "geometry": {
                                    "type": "Polygon",
                                    "coordinates": [[[77.105, 28.548], [77.120, 28.548], [77.120, 28.560], [77.105, 28.560], [77.105, 28.548]]],
                                },
                                "properties": {"area_ha": 18.45},
                            }
                        ],
                    },
                    "area_m2": 184500.0,
                    "area_hectares": 18.45,
                    "average_slope_deg": 4.82,
                    "elevation_range_m": {
                        "min_m": 431.2,
                        "max_m": 478.5,
                        "relief_m": 47.3,
                    },
                    "delineation_method": "flow_accumulation",
                },
                "processing_notes": [
                    "Parsed 34 contour lines with elevations ranging from 420.0m to 480.0m.",
                    "Generated DEM grid: 340x280 cells at 5.0m resolution in EPSG:32643.",
                    "Selected top recommended pond site (site_1): score=91.4, area=1450m².",
                    "Delineated upstream catchment using flow_accumulation: area=18.45 ha.",
                ],
            }
        }
    }


# Backwards compatibility alias
ContourAnalysisResponse = CatchmentResponse
