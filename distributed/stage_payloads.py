"""Serializable contracts exchanged between distributed processing stages."""

from __future__ import annotations

import base64
import binascii
import io
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import geopandas as gpd
import numpy as np
from affine import Affine
from shapely.geometry import mapping, shape

if TYPE_CHECKING:
    from app.services.catchment_delineation import CatchmentResult
    from app.services.dem_builder import DEMData
    from app.services.pond_site import PondSiteCandidate, PondSitingResult
    from app.services.terrain_analysis import TerrainAnalysisResult


def _encode_array(value: Optional[np.ndarray]) -> Optional[str]:
    if value is None:
        return None
    stream = io.BytesIO()
    np.save(stream, np.asarray(value), allow_pickle=False)
    return base64.b64encode(stream.getvalue()).decode("ascii")


def _decode_array(value: Optional[str]) -> Optional[np.ndarray]:
    if value is None:
        return None
    try:
        data = base64.b64decode(value.encode("ascii"), validate=True)
        return np.load(io.BytesIO(data), allow_pickle=False)
    except (ValueError, OSError, TypeError, EOFError, binascii.Error) as exc:
        raise ValueError("Invalid encoded raster array in stage payload") from exc


@dataclass
class ParsedContoursPayload:
    """Contour features represented as GeoJSON-compatible dictionaries."""

    features: List[Dict[str, Any]]
    crs: str = "EPSG:4326"

    @classmethod
    def from_geodataframe(cls, contours: gpd.GeoDataFrame) -> "ParsedContoursPayload":
        return cls(
            features=[
                {"elevation": float(row.elevation), "geometry": mapping(row.geometry)}
                for row in contours.itertuples()
            ],
            crs=str(contours.crs or "EPSG:4326"),
        )

    def to_geodataframe(self) -> gpd.GeoDataFrame:
        rows = [
            {"elevation": float(item["elevation"]), "geometry": shape(item["geometry"])}
            for item in self.features
        ]
        return gpd.GeoDataFrame(rows, columns=["elevation", "geometry"], crs=self.crs)

    def to_dict(self) -> Dict[str, Any]:
        return {"version": 1, "features": self.features, "crs": self.crs}

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "ParsedContoursPayload":
        if not isinstance(value.get("features"), list):
            raise ValueError("Parsed contour payload must contain a features list")
        return cls(features=value["features"], crs=str(value.get("crs", "EPSG:4326")))


@dataclass
class DEMPayload:
    """A DEM raster and georeferencing metadata safe to send over HTTP."""

    array: str
    shape: Tuple[int, int]
    dtype: str
    transform: Tuple[float, float, float, float, float, float]
    crs: str
    nodata: float
    resolution: float
    bounds: Tuple[float, float, float, float]

    @classmethod
    def from_dem_data(cls, dem: DEMData) -> "DEMPayload":
        return cls(
            array=_encode_array(dem.array) or "",
            shape=tuple(int(x) for x in dem.array.shape),
            dtype=str(dem.array.dtype),
            transform=tuple(float(x) for x in dem.transform[:6]),
            crs=dem.crs,
            nodata=float(dem.nodata),
            resolution=float(dem.resolution),
            bounds=tuple(float(x) for x in dem.bounds),
        )

    def to_dem_data(self) -> DEMData:
        from app.services.dem_builder import DEMData

        array = _decode_array(self.array)
        if array is None or tuple(array.shape) != tuple(self.shape):
            raise ValueError("DEM payload array shape does not match metadata")
        return DEMData(
            array=array.astype(self.dtype, copy=False),
            transform=Affine(*self.transform),
            crs=self.crs,
            nodata=self.nodata,
            resolution=self.resolution,
            bounds=self.bounds,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "array": self.array,
            "shape": list(self.shape),
            "dtype": self.dtype,
            "transform": list(self.transform),
            "crs": self.crs,
            "nodata": self.nodata,
            "resolution": self.resolution,
            "bounds": list(self.bounds),
        }

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "DEMPayload":
        return cls(
            array=str(value["array"]),
            shape=tuple(int(x) for x in value["shape"]),
            dtype=str(value["dtype"]),
            transform=tuple(float(x) for x in value["transform"]),
            crs=str(value["crs"]),
            nodata=float(value["nodata"]),
            resolution=float(value["resolution"]),
            bounds=tuple(float(x) for x in value["bounds"]),
        )


@dataclass
class TerrainPayload:
    """Terrain rasters and scalar diagnostics produced by sys3."""

    dem: DEMPayload
    slope_degrees: str
    slope_percent: str
    depression_index: str
    tpi: str
    suitability_score: str
    suitable_mask: str
    twi: Optional[str]
    twi_score: Optional[str]
    flow_accum: Optional[str]
    flow_dir: Optional[str]
    mean_slope_deg: float
    mean_suitability: float
    mean_twi: float
    suitable_area_percentage: float

    @classmethod
    def from_result(cls, result: TerrainAnalysisResult) -> "TerrainPayload":
        return cls(
            dem=DEMPayload.from_dem_data(result.dem_data),
            slope_degrees=_encode_array(result.slope_degrees) or "",
            slope_percent=_encode_array(result.slope_percent) or "",
            depression_index=_encode_array(result.depression_index) or "",
            tpi=_encode_array(result.tpi) or "",
            suitability_score=_encode_array(result.suitability_score) or "",
            suitable_mask=_encode_array(result.suitable_mask) or "",
            twi=_encode_array(result.twi),
            twi_score=_encode_array(result.twi_score),
            flow_accum=_encode_array(result.flow_accum),
            flow_dir=_encode_array(result.flow_dir),
            mean_slope_deg=result.mean_slope_deg,
            mean_suitability=result.mean_suitability,
            mean_twi=result.mean_twi,
            suitable_area_percentage=result.suitable_area_percentage,
        )

    def to_result(self) -> TerrainAnalysisResult:
        from app.services.terrain_analysis import TerrainAnalysisResult

        return TerrainAnalysisResult(
            slope_degrees=_decode_array(self.slope_degrees),
            slope_percent=_decode_array(self.slope_percent),
            depression_index=_decode_array(self.depression_index),
            tpi=_decode_array(self.tpi),
            suitability_score=_decode_array(self.suitability_score),
            suitable_mask=_decode_array(self.suitable_mask).astype(bool),
            dem_data=self.dem.to_dem_data(),
            twi=_decode_array(self.twi),
            twi_score=_decode_array(self.twi_score),
            flow_accum=_decode_array(self.flow_accum),
            flow_dir=_decode_array(self.flow_dir),
        )

    def to_dict(self) -> Dict[str, Any]:
        result = dict(self.__dict__)
        result["version"] = 1
        result["dem"] = self.dem.to_dict()
        return result

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "TerrainPayload":
        fields = dict(value)
        fields.pop("version", None)
        fields["dem"] = DEMPayload.from_dict(fields["dem"])
        return cls(**fields)


def _candidate_dict(candidate: PondSiteCandidate) -> Dict[str, Any]:
    value = {key: getattr(candidate, key) for key in candidate.__dataclass_fields__ if key not in ("polygon_utm", "polygon_wgs84")}
    value["polygon_utm"] = mapping(candidate.polygon_utm) if candidate.polygon_utm is not None else None
    value["polygon_wgs84"] = mapping(candidate.polygon_wgs84) if candidate.polygon_wgs84 is not None else None
    return value


def _candidate_from_dict(value: Dict[str, Any]) -> PondSiteCandidate:
    from app.services.pond_site import PondSiteCandidate

    fields = dict(value)
    fields["polygon_utm"] = shape(fields["polygon_utm"]) if fields.get("polygon_utm") else None
    fields["polygon_wgs84"] = shape(fields["polygon_wgs84"]) if fields.get("polygon_wgs84") else None
    return PondSiteCandidate(**fields)


@dataclass
class PondRankingPayload:
    """Ranked candidate sites plus diagnostics from sys3."""

    candidates: List[Dict[str, Any]] = field(default_factory=list)
    total_candidates_found: int = 0
    rejected_elongated_count: int = 0
    rejected_narrow_count: int = 0
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_result(cls, result: PondSitingResult) -> "PondRankingPayload":
        return cls(
            candidates=[_candidate_dict(candidate) for candidate in result.candidates],
            total_candidates_found=result.total_candidates_found,
            rejected_elongated_count=result.rejected_elongated_count,
            rejected_narrow_count=result.rejected_narrow_count,
            notes=list(result.notes),
        )

    def to_result(self, dem: Optional[DEMData] = None) -> PondSitingResult:
        from app.services.pond_site import PondSitingResult

        return PondSitingResult(
            candidates=[_candidate_from_dict(item) for item in self.candidates],
            dem_data=dem,
            total_candidates_found=self.total_candidates_found,
            rejected_elongated_count=self.rejected_elongated_count,
            rejected_narrow_count=self.rejected_narrow_count,
            notes=list(self.notes),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"version": 1, **self.__dict__}

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "PondRankingPayload":
        fields = dict(value)
        fields.pop("version", None)
        return cls(**fields)


@dataclass
class CatchmentPayload:
    """Serializable catchment metrics and boundary produced by sys4."""

    boundary_geojson: Dict[str, Any]
    pour_point_utm: Tuple[float, float]
    pour_point_wgs84: Tuple[float, float]
    snapped_pour_point_utm: Tuple[float, float]
    snapped_pour_point_wgs84: Tuple[float, float]
    area_m2: float
    area_ha: float
    cell_count: int
    mean_elevation: float
    min_elevation: float
    max_elevation: float
    elevation_span: float
    mean_slope_deg: float
    mean_slope_pct: float
    method_used: str
    scs_runoff: Optional[Dict[str, Any]] = None
    feasibility: Optional[Dict[str, Any]] = None
    erosion_metrics: Optional[Dict[str, Any]] = None

    @classmethod
    def from_result(cls, result: CatchmentResult) -> "CatchmentPayload":
        from app.services.catchment_delineation import CatchmentResult

        return cls(
            boundary_geojson=result.to_geojson_dict(),
            pour_point_utm=tuple(result.pour_point_utm),
            pour_point_wgs84=tuple(result.pour_point_wgs84),
            snapped_pour_point_utm=tuple(result.snapped_pour_point_utm),
            snapped_pour_point_wgs84=tuple(result.snapped_pour_point_wgs84),
            area_m2=float(result.area_m2),
            area_ha=float(result.area_ha),
            cell_count=int(result.cell_count),
            mean_elevation=float(result.mean_elevation),
            min_elevation=float(result.min_elevation),
            max_elevation=float(result.max_elevation),
            elevation_span=float(result.elevation_span),
            mean_slope_deg=float(result.mean_slope_deg),
            mean_slope_pct=float(result.mean_slope_pct),
            method_used=result.method_used,
            scs_runoff=result.scs_runoff,
            feasibility=result.feasibility,
            erosion_metrics=result.erosion_metrics,
        )

    def to_geojson_dict(self) -> Dict[str, Any]:
        return self.boundary_geojson

    def to_dict(self) -> Dict[str, Any]:
        return {"version": 1, **self.__dict__}

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "CatchmentPayload":
        fields = dict(value)
        fields.pop("version", None)
        for key in ("pour_point_utm", "pour_point_wgs84", "snapped_pour_point_utm", "snapped_pour_point_wgs84"):
            fields[key] = tuple(float(x) for x in fields[key])
        return cls(**fields)
