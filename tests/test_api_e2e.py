"""
End-to-End API Integration Tests using FastAPI TestClient.

Tests:
  - Uploads contour file to POST /analyzeContour
  - Asserts HTTP 200 OK status
  - Asserts response matches CatchmentResponse Pydantic schema
  - Asserts catchment drainage area is a positive number
  - Asserts recommended_site coordinates fall strictly within the input contour bounding box
  - Validates GeoJSON FeatureCollection structure and non-empty polygon boundaries
  - Directly tests with sample 'contours_1m.kml' located in project/workspace directory

Usage via pytest:
    pytest tests/test_api_e2e.py

Usage as CLI:
    python tests/test_api_e2e.py [path/to/contours_1m.kml]
"""

import io
import json
import sys
from pathlib import Path
from typing import Dict, Any

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import CatchmentResponse
from app.services.kml_parser import KMLParserService

client = TestClient(app)

# Search candidates for sample contours_1m.kml
SAMPLE_FILE_CANDIDATES = [
    Path(project_root).parent / "contours_1m.kml",
    Path(project_root) / "contours_1m.kml",
    Path("/Users/lazypilot/Desktop/Lazypilot/IIT Bhilai/Acad/SEM7/CSD/Assignment1/JalaSetu/contours_1m.kml"),
]

# Synthetic drainage basin contour map for fallback unit tests
SAMPLE_BASIN_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Sample Drainage Basin</name>
    <!-- Outer Ridge: 480m -->
    <Placemark>
      <name>Contour 480m</name>
      <LineString>
        <coordinates>
          77.100,28.540 77.120,28.540 77.120,28.560 77.100,28.560 77.100,28.540
        </coordinates>
      </LineString>
    </Placemark>
    <!-- Mid Valley Contour: 460m -->
    <Placemark>
      <name>Contour 460m</name>
      <LineString>
        <coordinates>
          77.103,28.543 77.117,28.543 77.117,28.557 77.103,28.557 77.103,28.543
        </coordinates>
      </LineString>
    </Placemark>
    <!-- Inner Swale: 440m -->
    <Placemark>
      <name>Contour 440m</name>
      <LineString>
        <coordinates>
          77.106,28.546 77.114,28.546 77.114,28.554 77.106,28.554 77.106,28.546
        </coordinates>
      </LineString>
    </Placemark>
    <!-- Bottom Bowl / Pond Site: 420m -->
    <Placemark>
      <name>Contour 420m</name>
      <LineString>
        <coordinates>
          77.109,28.549 77.111,28.549 77.111,28.551 77.109,28.551 77.109,28.549
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>
"""


def test_e2e_analyze_contour_endpoint_synthetic():
    """
    End-to-end test verifying schema validity, coordinate bounding box constraints,
    positive catchment drainage area, and GeoJSON geometry on synthetic data.
    """
    kml_bytes = SAMPLE_BASIN_KML.encode("utf-8")

    # 1. Parse bounding box of the input test dataset
    parser = KMLParserService()
    gdf = parser.parse(kml_bytes)
    min_lon, min_lat, max_lon, max_lat = gdf.total_bounds

    # 2. Upload to /analyzeContour endpoint via TestClient
    files = {"file": ("sample_basin.kml", io.BytesIO(kml_bytes), "application/vnd.google-earth.kml+xml")}
    data = {
        "dem_resolution_m": 5.0,
        "ideal_slope_deg": 3.0,
        "max_slope_deg": 8.0,
        "min_pond_area_m2": 100.0,
        "suitability_threshold": 60.0,
    }

    response = client.post("/analyzeContour", files=files, data=data)

    # 3. Assert HTTP 200 Status
    assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}: {response.text}"
    json_payload = response.json()

    # 4. Assert response matches CatchmentResponse Pydantic schema
    catchment_resp = CatchmentResponse(**json_payload)
    assert catchment_resp.status in ("success", "partial_success", "no_suitable_site")

    # 5. Assert input summary accuracy
    assert catchment_resp.input_summary is not None
    assert catchment_resp.input_summary.num_contours == 4
    assert catchment_resp.input_summary.elevation_min == 420.0
    assert catchment_resp.input_summary.elevation_max == 480.0

    # 6. Assert recommended site coordinates fall strictly within input bounding box
    assert catchment_resp.recommended_site is not None, "Recommended site should not be None for suitable basin"
    rec_site = catchment_resp.recommended_site

    assert min_lat <= rec_site.latitude <= max_lat, (
        f"Recommended site latitude ({rec_site.latitude}) must fall within contour bounds [{min_lat}, {max_lat}]"
    )
    assert min_lon <= rec_site.longitude <= max_lon, (
        f"Recommended site longitude ({rec_site.longitude}) must fall within contour bounds [{min_lon}, {max_lon}]"
    )
    assert rec_site.area_m2 > 0
    assert 0 <= rec_site.suitability_score <= 100

    # 7. Assert catchment drainage area is positive and valid
    assert catchment_resp.catchment is not None, "Catchment summary should be present for recommended site"
    catchment_info = catchment_resp.catchment

    assert catchment_info.area_m2 > 0, "Catchment drainage area (m²) must be positive"
    assert catchment_info.area_hectares > 0, "Catchment drainage area (ha) must be positive"
    assert catchment_info.average_slope_deg >= 0, "Catchment average slope must be non-negative"
    assert catchment_info.elevation_range_m.relief_m >= 0

    # 8. Assert GeoJSON boundary structure
    geojson = catchment_info.boundary_geojson
    assert geojson is not None
    assert geojson.get("type") == "FeatureCollection"
    assert len(geojson.get("features", [])) > 0
    first_geom = geojson["features"][0].get("geometry", {})
    assert first_geom.get("type") in ("Polygon", "MultiPolygon")
    assert len(first_geom.get("coordinates", [])) > 0


def test_e2e_with_contours_1m_sample_file():
    """
    End-to-end test specifically uploading and verifying contours_1m.kml from workspace.
    """
    sample_path = None
    for candidate in SAMPLE_FILE_CANDIDATES:
        if candidate.exists():
            sample_path = candidate
            break

    if sample_path is None:
        pytest.skip("contours_1m.kml sample file not found in expected paths.")

    with open(sample_path, "rb") as f:
        file_bytes = f.read()

    # 1. Parse ground truth bounds from file
    parser = KMLParserService()
    gdf = parser.parse(file_bytes)
    assert not gdf.empty, "contours_1m.kml must contain valid contour features"
    min_lon, min_lat, max_lon, max_lat = gdf.total_bounds

    # 2. Upload file to POST /analyzeContour
    files = {"file": (sample_path.name, io.BytesIO(file_bytes), "application/vnd.google-earth.kml+xml")}
    response = client.post("/analyzeContour", files=files)

    # 3. Assertions
    assert response.status_code == 200, f"Analysis failed with HTTP {response.status_code}: {response.text}"
    data = response.json()
    catchment_resp = CatchmentResponse(**data)

    # Status must be successful
    assert catchment_resp.status in ("success", "partial_success", "no_suitable_site")
    assert catchment_resp.input_summary is not None
    assert catchment_resp.input_summary.num_contours > 0

    # If recommended site is found, verify its coordinates are within real bounding box
    if catchment_resp.recommended_site:
        rec = catchment_resp.recommended_site
        assert min_lat <= rec.latitude <= max_lat, (
            f"Recommended site latitude ({rec.latitude}) not within file bounds [{min_lat}, {max_lat}]"
        )
        assert min_lon <= rec.longitude <= max_lon, (
            f"Recommended site longitude ({rec.longitude}) not within file bounds [{min_lon}, {max_lon}]"
        )
        assert rec.area_m2 > 0
        assert 0 <= rec.suitability_score <= 100

    # If catchment is delineated, verify positive drainage area
    if catchment_resp.catchment:
        cat = catchment_resp.catchment
        assert cat.area_m2 > 0, "Catchment area (m²) must be positive"
        assert cat.area_hectares > 0, "Catchment area (ha) must be positive"
        assert cat.average_slope_deg >= 0
        assert cat.boundary_geojson is not None
        assert cat.boundary_geojson["type"] == "FeatureCollection"


def verify_custom_file_e2e(file_path: Path):
    """
    CLI runner helper to test any custom KML/KMZ file through the TestClient and verify assertions.
    """
    print(f"\n" + "=" * 70)
    print(f"Running End-to-End API Verification against: {file_path.name}")
    print("=" * 70)
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    parser = KMLParserService()
    gdf = parser.parse(file_bytes)
    min_lon, min_lat, max_lon, max_lat = gdf.total_bounds
    print(f"1. Input Contour Extent:")
    print(f"   • Longitude : [{min_lon:.6f}, {max_lon:.6f}]")
    print(f"   • Latitude  : [{min_lat:.6f}, {max_lat:.6f}]")
    print(f"   • Features  : {len(gdf)} contour lines (Elevations: {gdf['elevation'].min():.1f}m - {gdf['elevation'].max():.1f}m)")

    print("\n2. Uploading file to POST /analyzeContour via TestClient...")
    files = {"file": (file_path.name, io.BytesIO(file_bytes), "application/octet-stream")}
    response = client.post("/analyzeContour", files=files)

    assert response.status_code == 200, f"Endpoint failed: {response.text}"
    data = response.json()
    catchment_resp = CatchmentResponse(**data)
    print("   ✅ HTTP 200 OK — Pydantic CatchmentResponse schema validated successfully.")

    if catchment_resp.recommended_site:
        rec = catchment_resp.recommended_site
        print(f"\n3. Recommended Pond Site (Rank #{rec.rank}):")
        print(f"   • Centroid Coordinates : {rec.latitude:.6f}°N, {rec.longitude:.6f}°E")
        print(f"   • Suitability Score    : {rec.suitability_score:.1f} / 100")
        print(f"   • Excavation Footprint : {rec.area_m2:,.1f} m² ({rec.area_m2/10000:.3f} ha)")
        print(f"   • Elevation & Slope    : {rec.elevation_m:.2f} m | {rec.slope_deg:.2f}°")

        assert min_lat <= rec.latitude <= max_lat, f"Latitude {rec.latitude} out of bounds [{min_lat}, {max_lat}]!"
        assert min_lon <= rec.longitude <= max_lon, f"Longitude {rec.longitude} out of bounds [{min_lon}, {max_lon}]!"
        print("   ✅ Centroid coordinates are strictly inside contour bounding box.")

    if catchment_resp.catchment:
        cat = catchment_resp.catchment
        print(f"\n4. Delineated Upstream Catchment Basin:")
        print(f"   • Catchment Area    : {cat.area_hectares:.3f} ha ({cat.area_m2:,.1f} m²)")
        print(f"   • Mean Basin Slope  : {cat.average_slope_deg:.2f}°")
        print(f"   • Elevation Relief  : {cat.elevation_range_m.min_m:.1f}m - {cat.elevation_range_m.max_m:.1f}m (Span: {cat.elevation_range_m.relief_m:.1f}m)")
        print(f"   • Routing Method    : {cat.delineation_method}")

        assert cat.area_m2 > 0, "Catchment area must be positive!"
        print("   ✅ Catchment drainage area verified as positive number.")

    print("\n" + "=" * 70)
    print("🎉 ALL END-TO-END TEST ASSERTIONS PASSED SUCCESSFULLY!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        verify_custom_file_e2e(Path(sys.argv[1]).resolve())
    else:
        sample_path = None
        for candidate in SAMPLE_FILE_CANDIDATES:
            if candidate.exists():
                sample_path = candidate
                break
        if sample_path:
            verify_custom_file_e2e(sample_path)
        else:
            print("Running synthetic End-to-End API test...")
            test_e2e_analyze_contour_endpoint_synthetic()
            print("✅ End-to-End API test passed successfully!")
