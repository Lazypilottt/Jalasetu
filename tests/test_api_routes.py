"""
API Route Tests for FastAPI Application.

Tests:
  - GET /health
  - GET /analyzeContour/schema
  - POST /analyzeContour validation (invalid extension, empty file, invalid parameter bounds)
  - POST /analyzeContour synthetic KML execution
"""

import io
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

SAMPLE_CONTOUR_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Contour 500m</name>
      <LineString>
        <coordinates>
          77.100,28.100 77.105,28.100 77.105,28.105 77.100,28.105 77.100,28.100
        </coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>Contour 520m</name>
      <LineString>
        <coordinates>
          77.101,28.101 77.104,28.101 77.104,28.104 77.101,28.104 77.101,28.101
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>
"""


def test_health_check_endpoint():
    """Verify GET /health returns 200 OK."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "running" in data["message"]


def test_analyze_contour_schema_endpoint():
    """Verify GET /analyzeContour/schema returns schema and defaults."""
    response = client.get("/analyzeContour/schema")
    assert response.status_code == 200
    data = response.json()
    assert "schema" in data
    assert "example" in data
    assert "default_parameters" in data
    assert data["default_parameters"]["ideal_slope_deg"] == 3.0


def test_analyze_contour_invalid_extension():
    """Verify uploading non-KML/KMZ returns 400 Bad Request."""
    files = {"file": ("test.txt", io.BytesIO(b"hello world"), "text/plain")}
    response = client.post("/analyzeContour", files=files)
    assert response.status_code == 400
    assert "Unsupported file format" in response.json()["detail"]


def test_analyze_contour_empty_file():
    """Verify uploading an empty KML file returns 400 Bad Request."""
    files = {"file": ("empty.kml", io.BytesIO(b""), "application/vnd.google-earth.kml+xml")}
    response = client.post("/analyzeContour", files=files)
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_analyze_contour_invalid_slope_bounds():
    """Verify parameter validation when max_slope <= ideal_slope."""
    files = {"file": ("valid.kml", io.BytesIO(SAMPLE_CONTOUR_KML.encode("utf-8")), "application/vnd.google-earth.kml+xml")}
    data = {
        "ideal_slope_deg": 10.0,
        "max_slope_deg": 5.0,  # Invalid: max_slope < ideal_slope
    }
    response = client.post("/analyzeContour", files=files, data=data)
    assert response.status_code == 400
    assert "must be strictly greater than" in response.json()["detail"]


def test_analyze_contour_valid_kml():
    """Verify successful end-to-end execution of POST /analyzeContour with valid synthetic KML."""
    files = {"file": ("contours.kml", io.BytesIO(SAMPLE_CONTOUR_KML.encode("utf-8")), "application/vnd.google-earth.kml+xml")}
    data = {"dem_resolution_m": 10.0}
    response = client.post("/analyzeContour", files=files, data=data)
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in ("success", "no_suitable_site", "partial_success")
    assert payload["input_summary"]["num_contours"] == 2
    assert payload["input_summary"]["elevation_min"] == 500.0
    assert payload["input_summary"]["elevation_max"] == 520.0
