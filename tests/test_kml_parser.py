"""
Test and CLI verification script for KML / KMZ parser service.

Usage as CLI:
    python tests/test_kml_parser.py path/to/contours.kml
    python tests/test_kml_parser.py path/to/contours.kmz

Usage via pytest:
    pytest tests/test_kml_parser.py
"""

import io
import sys
import zipfile
import argparse
from pathlib import Path

# Add project root to sys.path if executed directly
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.services.kml_parser import KMLParserService, parse_contour_kml, reproject_contours_to_utm


def inspect_kml_file(file_path: str):
    """
    Parse a KML/KMZ file and print a summary of extracted contour data.
    """
    path = Path(file_path)
    if not path.exists():
        print(f"Error: File not found at '{file_path}'")
        sys.exit(1)

    print("=" * 60)
    print(f"Parsing Contour Map: {path.name}")
    print("=" * 60)

    parser = KMLParserService()
    try:
        gdf = parser.parse(path)
    except Exception as e:
        print(f"Failed to parse file: {e}")
        sys.exit(1)

    if gdf.empty:
        print("Result: No valid contour features with elevation were found.")
        return

    num_features = len(gdf)
    min_elev = float(gdf["elevation"].min())
    max_elev = float(gdf["elevation"].max())
    unique_elevs = sorted(gdf["elevation"].unique().tolist())

    min_lon, min_lat, max_lon, max_lat = gdf.total_bounds

    print(f"Total Contour Features Found : {num_features}")
    print(f"Elevation Range (meters)     : {min_elev:.2f} m to {max_elev:.2f} m (span: {max_elev - min_elev:.2f} m)")
    print(f"Unique Elevation Levels ({len(unique_elevs)}) : {unique_elevs[:10]}{' ...' if len(unique_elevs) > 10 else ''}")
    print(f"Geographic Bounding Box (WGS84 EPSG:4326):")
    print(f"  Longitude : [{min_lon:.6f}, {max_lon:.6f}]")
    print(f"  Latitude  : [{min_lat:.6f}, {max_lat:.6f}]")

    # Reproject to UTM
    gdf_utm, utm_epsg = parser.to_utm(gdf)
    min_x, min_y, max_x, max_y = gdf_utm.total_bounds
    width_m = max_x - min_x
    height_m = max_y - min_y

    print(f"\nLocal Projected Coordinate System:")
    print(f"  Auto-detected UTM EPSG : EPSG:{utm_epsg}")
    print(f"  Projected Extent (m)   : Width = {width_m:.2f} m, Height = {height_m:.2f} m")
    print(f"  UTM Bounding Box (m)   : Easting [{min_x:.2f}, {max_x:.2f}], Northing [{min_y:.2f}, {max_y:.2f}]")

    print("\nSample Features Preview:")
    print(gdf.head(5)[["elevation", "geometry"]])
    print("=" * 60)
    print("Parsing completed successfully!")
    print("=" * 60)


# =====================================================================
# Unit Tests for Pytest
# =====================================================================

SAMPLE_KML_NAME_STRATEGY = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Contour 450</name>
      <LineString>
        <coordinates>
          77.100,28.100 77.101,28.101 77.102,28.100
        </coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>Contour 460</name>
      <LineString>
        <coordinates>
          77.100,28.105 77.101,28.106 77.102,28.105
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>
"""

SAMPLE_KML_EXTENDED_DATA = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Line_01</name>
      <ExtendedData>
        <Data name="ELEVATION">
          <value>520.5</value>
        </Data>
      </ExtendedData>
      <LineString>
        <coordinates>
          78.200,12.300 78.201,12.301
        </coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>Line_02</name>
      <ExtendedData>
        <SchemaData schemaUrl="#MySchema">
          <SimpleData name="CONTOUR">530.0</SimpleData>
        </SchemaData>
      </ExtendedData>
      <LineString>
        <coordinates>
          78.200,12.305 78.201,12.306
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>
"""

SAMPLE_KML_3D_COORDINATES = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <LineString>
        <coordinates>
          80.00,20.00,310.0 80.01,20.01,310.0 80.02,20.00,310.0
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>
"""

SAMPLE_KML_WITH_INVALID = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Boundary Property Line</name>
      <!-- No elevation data whatsoever -->
      <LineString>
        <coordinates>
          75.0,15.0 75.1,15.1
        </coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>Contour 100m</name>
      <LineString>
        <coordinates>
          75.0,15.0 75.1,15.1
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>
"""


def test_parse_kml_name_strategy():
    parser = KMLParserService()
    gdf = parser.parse(SAMPLE_KML_NAME_STRATEGY.encode("utf-8"))
    assert len(gdf) == 2
    assert sorted(gdf["elevation"].tolist()) == [450.0, 460.0]
    assert gdf.crs.to_epsg() == 4326


def test_parse_kml_extended_data_strategy():
    parser = KMLParserService()
    gdf = parser.parse(SAMPLE_KML_EXTENDED_DATA.encode("utf-8"))
    assert len(gdf) == 2
    assert sorted(gdf["elevation"].tolist()) == [520.5, 530.0]


def test_parse_kml_3d_coordinates():
    parser = KMLParserService()
    gdf = parser.parse(SAMPLE_KML_3D_COORDINATES.encode("utf-8"))
    assert len(gdf) == 1
    assert gdf.iloc[0]["elevation"] == 310.0


def test_parse_kml_graceful_skipping():
    parser = KMLParserService()
    gdf = parser.parse(SAMPLE_KML_WITH_INVALID.encode("utf-8"))
    # One valid contour feature (100m) should be parsed, the non-elevation boundary skipped
    assert len(gdf) == 1
    assert gdf.iloc[0]["elevation"] == 100.0


def test_parse_kmz_archive():
    # Build in-memory KMZ zip archive
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", SAMPLE_KML_NAME_STRATEGY)

    zip_bytes = zip_buffer.getvalue()
    parser = KMLParserService()
    gdf = parser.parse(zip_bytes)
    assert len(gdf) == 2
    assert sorted(gdf["elevation"].tolist()) == [450.0, 460.0]


def test_reproject_to_utm():
    parser = KMLParserService()
    gdf = parser.parse(SAMPLE_KML_NAME_STRATEGY.encode("utf-8"))
    gdf_utm, utm_epsg = parser.to_utm(gdf)
    assert utm_epsg == 32643  # Longitude ~77.1E is in UTM Zone 43N
    assert gdf_utm.crs.to_epsg() == 32643


if __name__ == "__main__":
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        inspect_kml_file(sys.argv[1])
    else:
        print("Usage: python tests/test_kml_parser.py <path_to_kml_or_kmz_file>")
        print("Running internal smoke test with sample dataset...")
        test_parse_kml_name_strategy()
        test_parse_kml_extended_data_strategy()
        test_parse_kml_3d_coordinates()
        test_parse_kml_graceful_skipping()
        test_parse_kmz_archive()
        test_reproject_to_utm()
        print("All internal smoke tests passed successfully!")
