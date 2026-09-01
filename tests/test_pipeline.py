"""
Integration tests for the end-to-end analyze_contour_file pipeline.

Usage as CLI:
    python tests/test_pipeline.py path/to/contours.kml

Usage via pytest:
    pytest tests/test_pipeline.py
"""

import io
import json
import sys
import zipfile
from pathlib import Path

# Add project root to sys.path if executed directly
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pytest
from shapely.geometry import Point, shape

from app.models.schemas import CatchmentResponse
from app.services.pipeline import analyze_contour_file, DEFAULT_PIPELINE_PARAMS
from app.services.kml_parser import KMLParserService

SAMPLE_FILE_CANDIDATES = [
    Path(project_root) / "contours_1m.kml",
    Path(project_root).parent / "contours_1m.kml",
    Path("/Users/lazypilot/Desktop/Lazypilot/IIT Bhilai/Acad/SEM7/CSD/Assignment1/JalaSetu/contours_1m.kml"),
]

SAMPLE_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <!-- Concentric hill contour rings -->
    <Placemark>
      <name>Contour 400m</name>
      <LineString>
        <coordinates>
          77.100,28.100 77.105,28.100 77.105,28.105 77.100,28.105 77.100,28.100
        </coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>Contour 420m</name>
      <LineString>
        <coordinates>
          77.101,28.101 77.104,28.101 77.104,28.104 77.101,28.104 77.101,28.101
        </coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>Contour 440m</name>
      <LineString>
        <coordinates>
          77.102,28.102 77.103,28.102 77.103,28.103 77.102,28.103 77.102,28.102
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>
"""


def test_pipeline_execution():
    """Verify that analyze_contour_file processes KML bytes and produces CatchmentResponse."""
    kml_bytes = SAMPLE_KML.encode("utf-8")
    response = analyze_contour_file(kml_bytes, params={"dem_resolution_m": 10.0})

    assert isinstance(response, CatchmentResponse)
    assert response.status in ("success", "partial_success")
    assert response.input_summary is not None
    assert response.input_summary.num_contours == 3
    assert response.input_summary.elevation_min == 400.0
    assert response.input_summary.elevation_max == 440.0
    assert len(response.processing_notes) > 0


def test_pipeline_recommended_site_containment_regression_sample_file():
    """
    Regression test: Run full pipeline on the sample file (contours_1m.kml) and verify:
    1. Pipeline succeeds and identifies a top recommended pond site.
    2. Containment sanity check passes with no data quality warning in processing_notes.
    3. Recommended site point falls within or within 1 cell's distance of its suitability region.
    4. Recommended site centroid strictly falls within the KML dataset's bounding box.
    """
    sample_path = None
    for cand in SAMPLE_FILE_CANDIDATES:
        if cand.exists():
            sample_path = cand
            break

    if sample_path is None:
        pytest.skip("contours_1m.kml sample file not found.")

    with open(sample_path, "rb") as f:
        file_bytes = f.read()

    # Parse ground truth bounding box from input KML
    parser = KMLParserService()
    gdf = parser.parse(file_bytes)
    assert not gdf.empty, "Input sample file must have valid contour features."
    min_lon, min_lat, max_lon, max_lat = gdf.total_bounds

    # Run full pipeline on sample file
    response = analyze_contour_file(sample_path)

    assert isinstance(response, CatchmentResponse)
    assert response.status == "success"
    assert response.recommended_site is not None
    rec = response.recommended_site

    # 1. Assert NO data-quality misalignment warning is present in processing_notes
    misalignment_warnings = [
        note for note in response.processing_notes
        if "DATA QUALITY WARNING" in note or "misalignment" in note.lower()
    ]
    assert not misalignment_warnings, f"Containment check failed with warning: {misalignment_warnings}"

    # 2. Assert coordinates fall strictly within input bounding box
    assert min_lat <= rec.latitude <= max_lat, (
        f"Recommended site latitude ({rec.latitude}) outside bounds [{min_lat}, {max_lat}]"
    )
    assert min_lon <= rec.longitude <= max_lon, (
        f"Recommended site longitude ({rec.longitude}) outside bounds [{min_lon}, {max_lon}]"
    )

    # 3. Assert recommended_site.boundary_geojson is present, valid, and contains its own centroid
    assert rec.boundary_geojson is not None, "recommended_site must include boundary_geojson"
    assert rec.boundary_geojson["type"] == "FeatureCollection"
    assert len(rec.boundary_geojson["features"]) > 0
    rec_site_geom = shape(rec.boundary_geojson["features"][0]["geometry"])
    assert rec_site_geom.is_valid and not rec_site_geom.is_empty
    pt_wgs84 = Point(rec.longitude, rec.latitude)
    assert rec_site_geom.covers(pt_wgs84) or rec_site_geom.distance(pt_wgs84) <= 0.001, (
        f"Recommended site centroid {pt_wgs84} is not contained within its boundary polygon"
    )

    # 4. Assert alternative_sites also include valid boundary_geojson
    for alt in response.alternative_sites:
        if alt.boundary_geojson:
            assert alt.boundary_geojson["type"] == "FeatureCollection"
            alt_geom = shape(alt.boundary_geojson["features"][0]["geometry"])
            assert alt_geom.is_valid and not alt_geom.is_empty
            alt_pt = Point(alt.longitude, alt.latitude)
            assert alt_geom.covers(alt_pt) or alt_geom.distance(alt_pt) <= 0.001

    # 5. Assert GeoJSON catchment boundary coordinates are [longitude, latitude] in EPSG:4326
    assert response.catchment is not None
    assert response.catchment.boundary_geojson is not None
    geojson = response.catchment.boundary_geojson
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) > 0

    first_feat = geojson["features"][0]
    cat_geom = shape(first_feat["geometry"])
    assert cat_geom.is_valid and not cat_geom.is_empty
    poly_min_lon, poly_min_lat, poly_max_lon, poly_max_lat = cat_geom.bounds

    # Bounding box of catchment must be geographically plausible (longitude in [min_lon, max_lon], latitude in [min_lat, max_lat])
    assert min_lon - 0.01 <= poly_min_lon <= max_lon + 0.01
    assert min_lat - 0.01 <= poly_min_lat <= max_lat + 0.01

    # Pour point in GeoJSON properties must follow [longitude, latitude] ordering
    props = first_feat.get("properties", {})
    if "pour_point" in props and "input_wgs84" in props["pour_point"]:
        pp_lon, pp_lat = props["pour_point"]["input_wgs84"]
        assert min_lon - 0.01 <= pp_lon <= max_lon + 0.01
        assert min_lat - 0.01 <= pp_lat <= max_lat + 0.01


def test_pipeline_coordinate_ordering_and_geojson_structure():
    """Verify (lng, lat) vs (lat, lng) correctness in GeoJSON and Pydantic schemas."""
    kml_bytes = SAMPLE_KML.encode("utf-8")
    response = analyze_contour_file(kml_bytes, params={"dem_resolution_m": 10.0})

    assert response.recommended_site is not None
    rec = response.recommended_site
    # Latitude ~28.1, Longitude ~77.1
    assert 27.0 <= rec.latitude <= 29.0, f"Expected latitude ~28, got {rec.latitude}"
    assert 76.0 <= rec.longitude <= 78.0, f"Expected longitude ~77, got {rec.longitude}"

    if response.catchment and response.catchment.boundary_geojson:
        geojson = response.catchment.boundary_geojson
        for feat in geojson["features"]:
            geom = feat["geometry"]
            # All coordinates in Polygon must have first element as Longitude (~77) and second as Latitude (~28)
            coords = geom["coordinates"]
            def check_coords(c_list):
                if isinstance(c_list[0], (int, float)):
                    lon_val, lat_val = c_list[0], c_list[1]
                    assert 76.0 <= lon_val <= 78.0, f"Expected lon ~77 as 1st coord, got {lon_val}"
                    assert 27.0 <= lat_val <= 29.0, f"Expected lat ~28 as 2nd coord, got {lat_val}"
                else:
                    for sub in c_list:
                        check_coords(sub)
            check_coords(coords)


def run_pipeline_on_file(file_path: str):
    """Run pipeline against a real KML/KMZ file and print JSON response."""
    path = Path(file_path).resolve()
    print(f"Running pipeline on: {path}")
    response = analyze_contour_file(path)
    print(json.dumps(response.model_dump(), indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        run_pipeline_on_file(sys.argv[1])
    else:
        print("Running unit tests on synthetic and sample datasets...")
        test_pipeline_execution()
        test_pipeline_recommended_site_containment_regression_sample_file()
        test_pipeline_coordinate_ordering_and_geojson_structure()
        print("All pipeline integration & regression tests passed successfully!")
