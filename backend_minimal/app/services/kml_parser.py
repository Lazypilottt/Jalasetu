"""
KML / KMZ Parsing Service.

Responsibility:
- Parse uploaded KML / KMZ contour map files and extract contour features.
- Support both file paths and file-like objects (e.g. UploadFile stream, BytesIO, raw bytes).
- Multi-strategy elevation extraction:
    1. <ExtendedData> (<Data> / <SimpleData> tags)
    2. <name> tag parsing with regex patterns
    3. <description> tag parsing
    4. 3D geometry coordinates (Z-coordinate)
- Graceful degradation: skip features where elevation cannot be determined with a warning log.
- Return GeoDataFrame with columns ['elevation', 'geometry'] in EPSG:4326.
- Provide helper methods to reproject the GeoDataFrame to the auto-calculated local UTM zone.
"""

import io
import logging
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import BinaryIO, Dict, List, Optional, Tuple, Union

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import (
    LineString,
    MultiLineString,
    Polygon,
    MultiPolygon,
    Point,
    MultiPoint,
    GeometryCollection,
)
from shapely.geometry.base import BaseGeometry

from app.utils.geometry import (
    get_utm_epsg_from_lon_lat,
    calculate_utm_crs_from_gdf,
    reproject_to_utm,
)

logger = logging.getLogger(__name__)

# Common XML tag names for elevation attributes (case-insensitive)
ELEVATION_ATTR_KEYS = {
    "elevation",
    "elev",
    "contour",
    "height",
    "altitude",
    "alt",
    "z",
    "level",
    "lvl",
    "contour_val",
    "contour_m",
    "contour_ft",
    "c_val",
    "ele",
    "val",
    "value",
    "height_m",
    "elev_m",
}


def _strip_namespace(tag: str) -> str:
    """Remove XML namespace from element tag."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _parse_float_from_string(text: Optional[str]) -> Optional[float]:
    """
    Extract a floating point elevation value from text.
    Handles units like 'm', 'meters', 'ft', 'feet'.
    """
    if not text:
        return None

    cleaned = text.strip()
    if not cleaned:
        return None

    # Check for unit specification
    unit_factor = 1.0
    if re.search(r'\b(?:ft|feet|foot)\b', cleaned, re.IGNORECASE):
        unit_factor = 0.3048  # Convert feet to meters

    # Try matching explicit number with optional signs and decimals
    # 1. Match number followed by meter/ft units or standalone
    match = re.search(r'([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)', cleaned)
    if match:
        try:
            val = float(match.group(1))
            return val * unit_factor
        except (ValueError, TypeError):
            pass

    return None


def _parse_coordinates_text(coord_text: str) -> List[Tuple[float, ...]]:
    """
    Parse KML coordinate tuples: 'lon,lat,alt lon,lat,alt ...'
    Supports various delimiters (spaces, tabs, newlines).
    """
    points: List[Tuple[float, ...]] = []
    if not coord_text:
        return points

    # Split by any whitespace
    tokens = coord_text.strip().split()
    for token in tokens:
        parts = [p.strip() for p in token.split(",") if p.strip()]
        if len(parts) >= 2:
            try:
                lon = float(parts[0])
                lat = float(parts[1])
                if len(parts) >= 3:
                    alt = float(parts[2])
                    points.append((lon, lat, alt))
                else:
                    points.append((lon, lat))
            except ValueError:
                continue
    return points


def _extract_geometry_from_element(elem: ET.Element) -> Optional[BaseGeometry]:
    """
    Recursively extract Shapely geometry from a KML XML element.
    Handles LineString, Polygon, LinearRing, MultiGeometry, and Point.
    """
    tag = _strip_namespace(elem.tag)

    if tag == "LineString":
        for child in elem:
            if _strip_namespace(child.tag) == "coordinates" and child.text:
                coords = _parse_coordinates_text(child.text)
                if len(coords) >= 2:
                    # Use 2D (lon, lat) for shapely horizontal geometry
                    return LineString([(p[0], p[1]) for p in coords])
        return None

    elif tag == "LinearRing":
        for child in elem:
            if _strip_namespace(child.tag) == "coordinates" and child.text:
                coords = _parse_coordinates_text(child.text)
                if len(coords) >= 3:
                    return LineString([(p[0], p[1]) for p in coords])
        return None

    elif tag == "Polygon":
        outer_coords = []
        inner_coords_list = []
        for child in elem:
            child_tag = _strip_namespace(child.tag)
            if child_tag == "outerBoundaryIs":
                for lr in child:
                    if _strip_namespace(lr.tag) == "LinearRing":
                        for c in lr:
                            if _strip_namespace(c.tag) == "coordinates" and c.text:
                                outer_coords = [
                                    (p[0], p[1]) for p in _parse_coordinates_text(c.text)
                                ]
            elif child_tag == "innerBoundaryIs":
                for lr in child:
                    if _strip_namespace(lr.tag) == "LinearRing":
                        for c in lr:
                            if _strip_namespace(c.tag) == "coordinates" and c.text:
                                inner_coords = [
                                    (p[0], p[1]) for p in _parse_coordinates_text(c.text)
                                ]
                                if len(inner_coords) >= 3:
                                    inner_coords_list.append(inner_coords)

        if len(outer_coords) >= 3:
            return Polygon(shell=outer_coords, holes=inner_coords_list)
        return None

    elif tag == "Point":
        for child in elem:
            if _strip_namespace(child.tag) == "coordinates" and child.text:
                coords = _parse_coordinates_text(child.text)
                if coords:
                    return Point(coords[0][0], coords[0][1])
        return None

    elif tag == "MultiGeometry":
        geoms = []
        for child in elem:
            g = _extract_geometry_from_element(child)
            if g is not None and not g.is_empty:
                geoms.append(g)

        if not geoms:
            return None

        # Consolidate geometries
        all_lines = all(isinstance(g, (LineString, MultiLineString)) for g in geoms)
        all_polys = all(isinstance(g, (Polygon, MultiPolygon)) for g in geoms)
        all_pts = all(isinstance(g, (Point, MultiPoint)) for g in geoms)

        if all_lines:
            line_list = []
            for g in geoms:
                if isinstance(g, MultiLineString):
                    line_list.extend(g.geoms)
                else:
                    line_list.append(g)
            return MultiLineString(line_list) if len(line_list) > 1 else line_list[0]
        elif all_polys:
            poly_list = []
            for g in geoms:
                if isinstance(g, MultiPolygon):
                    poly_list.extend(g.geoms)
                else:
                    poly_list.append(g)
            return MultiPolygon(poly_list) if len(poly_list) > 1 else poly_list[0]
        elif all_pts:
            pt_list = [p for g in geoms for p in (g.geoms if isinstance(g, MultiPoint) else [g])]
            return MultiPoint(pt_list)
        else:
            return GeometryCollection(geoms)

    return None


def _extract_all_3d_coordinates(elem: ET.Element) -> List[Tuple[float, ...]]:
    """Recursively collect all coordinate tuples from an XML element."""
    coords: List[Tuple[float, ...]] = []
    for el in elem.iter():
        if _strip_namespace(el.tag) == "coordinates" and el.text:
            coords.extend(_parse_coordinates_text(el.text))
    return coords


def _extract_elevation_from_placemark(
    placemark_elem: ET.Element,
    raw_coords: List[Tuple[float, ...]],
    placemark_name: Optional[str] = None,
    placemark_desc: Optional[str] = None,
) -> Optional[float]:
    """
    Multi-strategy elevation extraction:
    Strategy 1: <ExtendedData> (<Data> / <SimpleData> tags)
    Strategy 2: <name> tag parsing with regex
    Strategy 3: <description> tag parsing
    Strategy 4: Z coordinate from 3D geometry coordinates
    """

    # --- Strategy 1: ExtendedData inspection ---
    for el in placemark_elem.iter():
        tag = _strip_namespace(el.tag)
        if tag in ("Data", "SimpleData"):
            attr_name = el.attrib.get("name", "").strip().lower()
            val_text = None
            if tag == "SimpleData":
                val_text = el.text
            elif tag == "Data":
                for child in el:
                    if _strip_namespace(child.tag) == "value":
                        val_text = child.text
                        break

            # If attribute name matches common elevation keys
            if attr_name in ELEVATION_ATTR_KEYS or any(k in attr_name for k in ("elev", "cont", "height", "altitude")):
                elev = _parse_float_from_string(val_text)
                if elev is not None:
                    return elev

    # --- Strategy 2: <name> tag inspection ---
    if placemark_name:
        name_str = placemark_name.strip()

        # 2a. Explicit keyword match (e.g., 'Contour 450', 'Elevation: 450.5m', 'Elev_100')
        keyword_match = re.search(
            r'(?:contour|elevation|elev|height|altitude|level|z|alt)\s*[:=_#\-]?\s*([+-]?\d+(?:\.\d+)?)',
            name_str,
            re.IGNORECASE,
        )
        if keyword_match:
            try:
                return float(keyword_match.group(1))
            except ValueError:
                pass

        # 2b. Match number with units (e.g. '450m', '450 m', '1200 ft')
        unit_match = re.search(
            r'([+-]?\d+(?:\.\d+)?)\s*(?:m|meter|meters|ft|feet)\b',
            name_str,
            re.IGNORECASE,
        )
        if unit_match:
            elev = _parse_float_from_string(unit_match.group(0))
            if elev is not None:
                return elev

        # 2c. Name is purely a number (e.g., '450' or '450.0')
        pure_num_match = re.match(r'^[+-]?\d+(?:\.\d+)?$', name_str)
        if pure_num_match:
            try:
                return float(pure_num_match.group(0))
            except ValueError:
                pass

        # 2d. If name contains exactly one isolated numeric token
        tokens = re.findall(r'[-+]?\d+(?:\.\d+)?', name_str)
        if len(tokens) == 1:
            try:
                return float(tokens[0])
            except ValueError:
                pass

    # --- Strategy 3: <description> tag inspection ---
    if placemark_desc:
        desc_match = re.search(
            r'(?:contour|elevation|elev|height|altitude|level)\s*[:=><td/\s]*([+-]?\d+(?:\.\d+)?)',
            placemark_desc,
            re.IGNORECASE,
        )
        if desc_match:
            try:
                return float(desc_match.group(1))
            except ValueError:
                pass

    # --- Strategy 4: 3D geometry coordinates (Z-value) ---
    if raw_coords:
        z_vals = [p[2] for p in raw_coords if len(p) >= 3]
        if z_vals:
            # Check if z values are meaningful (non-zero or consistent)
            has_nonzero = any(abs(z) > 1e-4 for z in z_vals)
            if has_nonzero or len(set(z_vals)) == 1:
                # Use mean Z coordinate across vertices
                return float(np.mean(z_vals))

    return None


class KMLParserService:
    """
    Service for parsing KML and KMZ contour map files into GeoDataFrames.
    """

    def __init__(self):
        pass

    def _read_kml_bytes(self, file_source: Union[str, Path, BinaryIO, bytes]) -> bytes:
        """
        Extract raw KML byte content from file path, bytes, or KMZ archive.
        """
        # Case 1: Bytes or bytearray
        if isinstance(file_source, (bytes, bytearray)):
            raw_bytes = bytes(file_source)
        # Case 2: File path (str or Path)
        elif isinstance(file_source, (str, Path)):
            path = Path(file_source)
            if not path.exists():
                raise FileNotFoundError(f"File not found: {path}")
            with open(path, "rb") as f:
                raw_bytes = f.read()
        # Case 3: File-like object (e.g. UploadFile.file, BytesIO)
        elif hasattr(file_source, "read"):
            raw_bytes = file_source.read()
            if isinstance(raw_bytes, str):
                raw_bytes = raw_bytes.encode("utf-8")
        else:
            raise ValueError(f"Unsupported file source type: {type(file_source)}")

        # Check if the input is a KMZ archive (ZIP format)
        if zipfile.is_zipfile(io.BytesIO(raw_bytes)):
            logger.info("Detected KMZ (zip archive). Extracting KML...")
            with zipfile.ZipFile(io.BytesIO(raw_bytes), "r") as zf:
                # Search for .kml files inside archive
                kml_names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
                if not kml_names:
                    raise ValueError("KMZ archive does not contain any .kml files.")

                # Prefer 'doc.kml' if present, otherwise take the first .kml
                target_kml = "doc.kml" if "doc.kml" in kml_names else kml_names[0]
                logger.info("Reading %s from KMZ archive", target_kml)
                raw_bytes = zf.read(target_kml)

        return raw_bytes

    def parse(
        self,
        file_source: Union[str, Path, BinaryIO, bytes],
    ) -> gpd.GeoDataFrame:
        """
        Parse KML or KMZ contour file and extract contour lines with elevations.

        Args:
            file_source: Path to .kml/.kmz file, bytes, or file-like object.

        Returns:
            gpd.GeoDataFrame: GeoDataFrame with columns ['elevation', 'geometry'] in EPSG:4326.
        """
        kml_bytes = self._read_kml_bytes(file_source)

        try:
            root = ET.fromstring(kml_bytes)
        except ET.ParseError as e:
            logger.error("XML parse error while reading KML: %s", e)
            raise ValueError(f"Invalid KML XML content: {e}") from e

        records: List[Dict[str, Any]] = []

        # Find all Placemark elements regardless of nesting or namespace
        for elem in root.iter():
            if _strip_namespace(elem.tag) != "Placemark":
                continue

            placemark_elem = elem

            # Extract Placemark name and description
            placemark_name: Optional[str] = None
            placemark_desc: Optional[str] = None

            for child in placemark_elem:
                child_tag = _strip_namespace(child.tag)
                if child_tag == "name" and child.text:
                    placemark_name = child.text.strip()
                elif child_tag == "description" and child.text:
                    placemark_desc = child.text.strip()

            # Collect raw coordinates for 3D Z inspection
            raw_coords = _extract_all_3d_coordinates(placemark_elem)

            # Extract geometry
            geometry = None
            for child in placemark_elem:
                c_tag = _strip_namespace(child.tag)
                if c_tag in ("LineString", "Polygon", "LinearRing", "MultiGeometry", "Point"):
                    geometry = _extract_geometry_from_element(child)
                    if geometry is not None and not geometry.is_empty:
                        break

            if geometry is None or geometry.is_empty:
                logger.debug("Placemark '%s' contains no valid geometry. Skipping.", placemark_name)
                continue

            # Extract elevation using multi-strategy approach
            elevation = _extract_elevation_from_placemark(
                placemark_elem,
                raw_coords,
                placemark_name=placemark_name,
                placemark_desc=placemark_desc,
            )

            if elevation is None:
                logger.warning(
                    "Could not extract elevation for feature '%s'. Skipping feature.",
                    placemark_name or "<unnamed>",
                )
                continue

            # If geometry is a MultiLineString or MultiPolygon, unroll individual parts or keep multi
            records.append({
                "elevation": float(elevation),
                "geometry": geometry,
            })

        if not records:
            logger.warning("No valid contour features with elevation were extracted from KML.")
            return gpd.GeoDataFrame(columns=["elevation", "geometry"], crs="EPSG:4326")

        gdf = gpd.GeoDataFrame(records, columns=["elevation", "geometry"], crs="EPSG:4326")
        gdf["elevation"] = pd.to_numeric(gdf["elevation"], errors="coerce")
        gdf = gdf.dropna(subset=["elevation"]).reset_index(drop=True)

        logger.info("Successfully parsed %d contour features from KML.", len(gdf))
        return gdf

    def to_utm(self, gdf: gpd.GeoDataFrame) -> Tuple[gpd.GeoDataFrame, int]:
        """
        Helper method to reproject GeoDataFrame from EPSG:4326 to auto-calculated local UTM zone.

        Args:
            gdf (gpd.GeoDataFrame): Input GeoDataFrame.

        Returns:
            Tuple[gpd.GeoDataFrame, int]: (Reprojected GeoDataFrame, UTM EPSG code).
        """
        return reproject_to_utm(gdf)


# Convenience module-level functions
def parse_contour_kml(file_source: Union[str, Path, BinaryIO, bytes]) -> gpd.GeoDataFrame:
    """Parse KML/KMZ contour file into GeoDataFrame in EPSG:4326."""
    parser = KMLParserService()
    return parser.parse(file_source)


def reproject_contours_to_utm(gdf: gpd.GeoDataFrame) -> Tuple[gpd.GeoDataFrame, int]:
    """Reproject contour GeoDataFrame to local UTM projection."""
    return reproject_to_utm(gdf)
