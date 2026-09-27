"""Focused contract and gateway tests for the distributed deployment."""

import json

from distributed.stage_payloads import DEMPayload, ParsedContoursPayload
from distributed.stages import build_dem_stage, parse_contours_stage
from distributed.sys2 import create_app as create_sys2_app
from distributed.sys4 import create_app as create_sys4_app


SAMPLE_KML = b"""<?xml version="1.0"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>Contour 100m</name><LineString><coordinates>
77.10,28.10 77.11,28.10 77.11,28.11 77.10,28.10
</coordinates></LineString></Placemark>
<Placemark><name>Contour 110m</name><LineString><coordinates>
77.101,28.101 77.109,28.101 77.109,28.109 77.101,28.101
</coordinates></LineString></Placemark>
</Document></kml>"""


def test_stage_payloads_are_json_serializable_and_round_trip():
    contours = parse_contours_stage(SAMPLE_KML)
    dem = build_dem_stage(contours, {"dem_resolution_m": 20.0})
    encoded = json.dumps({"contours": contours.to_dict(), "dem": dem.to_dict()})
    restored = DEMPayload.from_dict(json.loads(encoded)["dem"]).to_dem_data()
    assert restored.crs == dem.crs
    assert restored.shape == dem.shape


def test_sys2_and_sys4_health_contracts():
    sys2 = create_sys2_app().test_client()
    sys4 = create_sys4_app().test_client()
    assert sys2.get("/health").get_json()["service"] == "sys2"
    assert sys4.get("/health").get_json()["service"] == "sys4"
    missing = sys4.post("/analyzeContour", data={})
    assert missing.status_code == 422
