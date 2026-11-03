"""Existing-infrastructure exclusions, global DEM terrain source, and footprint carving."""

import json

import numpy as np
import pytest
from affine import Affine
from shapely.geometry import Point, shape

from app.services import infrastructure as infra
from app.services import terrain_source
from app.services.dem_builder import DEMData
from app.services.exclusions import (
    apply_exclusions,
    build_exclusion_zones,
    parse_categories,
    parse_manual_zones,
    plan_exclusions,
    summarize,
)
from app.services.pond_site import PondSiteService
from app.services.terrain_analysis import TerrainAnalysisService

LAT, LON = 21.1950, 81.4820  # outside the bundled demo contours


# -- OpenStreetMap classification ---------------------------------------------


@pytest.mark.parametrize(
    "tags, expected",
    [
        ({"amenity": "school"}, "facility"),
        ({"building": "temple"}, "facility"),
        ({"building": "yes"}, "building"),
        ({"natural": "water"}, "water"),
        ({"landuse": "reservoir"}, "water"),
        ({"waterway": "canal"}, "waterway"),
        ({"highway": "track"}, "road"),
        ({"railway": "rail"}, "railway"),
        ({"landuse": "residential"}, "settlement"),
        ({"man_made": "water_well"}, "well"),
        ({"natural": "wetland"}, None),
        ({"highway": "footway"}, None),
        ({}, None),
    ],
)
def test_classify_osm_tags(tags, expected):
    assert infra.classify(tags) == expected


def test_parse_overpass_builds_geometries_by_kind():
    payload = {
        "elements": [
            {"type": "node", "id": 1, "lat": LAT, "lon": LON, "tags": {"amenity": "school", "name": "School"}},
            {"type": "way", "id": 2, "tags": {"building": "yes"}, "geometry": [
                {"lat": 0, "lon": 0}, {"lat": 0, "lon": 1e-4}, {"lat": 1e-4, "lon": 1e-4}, {"lat": 0, "lon": 0}]},
            {"type": "way", "id": 3, "tags": {"waterway": "stream"}, "geometry": [{"lat": 0, "lon": 0}, {"lat": 1e-3, "lon": 1e-3}]},
            {"type": "way", "id": 4, "tags": {"highway": "footway"}, "geometry": [{"lat": 0, "lon": 0}, {"lat": 1, "lon": 1}]},
        ]
    }
    features = infra.parse_overpass(payload)
    assert [f["geometry"]["type"] for f in features] == ["Point", "Polygon", "LineString"]
    assert features[0]["properties"] == {"category": "facility", "name": "School", "osm": "node/1"}


@pytest.fixture(autouse=True)
def fresh_lookup_state(monkeypatch):
    """Each test starts with an empty cache and no cool-down."""
    monkeypatch.setattr(infra, "_cache", {})
    monkeypatch.setattr(infra, "_unavailable_until", 0.0)


def test_failed_lookup_reports_unavailable_instead_of_raising(monkeypatch):
    monkeypatch.setattr(infra, "_fetch", lambda query, budget_s: (_ for _ in ()).throw(RuntimeError("all endpoints down")))
    infra._cache.clear()
    result = infra.fetch_infrastructure(LAT, LON, 400)
    assert result["status"] == "unavailable"
    assert result["features"]["features"] == []


def test_successful_lookup_is_cached(monkeypatch):
    calls = []

    def fake_fetch(query, budget_s):
        calls.append(query)
        return {"elements": [{"type": "node", "id": 9, "lat": LAT, "lon": LON, "tags": {"man_made": "water_well"}}]}, "https://x/api"

    monkeypatch.setattr(infra, "_fetch", fake_fetch)
    infra._cache.clear()
    first = infra.fetch_infrastructure(LAT, LON, 400)
    second = infra.fetch_infrastructure(LAT, LON, 400)
    assert first["counts"] == {"well": 1}
    assert second["cached"] is True
    assert len(calls) == 1
    assert "around:400" in calls[0]


# -- exclusion zones and masking ---------------------------------------------


def flat_dem(size=60, res=10.0, lat=LAT, lon=LON):
    from pyproj import Transformer

    cx, cy = Transformer.from_crs("EPSG:4326", "EPSG:32644", always_xy=True).transform(lon, lat)
    minx, maxy = cx - size * res / 2, cy + size * res / 2
    rows, cols = np.indices((size, size))
    # A shallow bowl: lowest (most pond-like) at the centre.
    array = 100.0 + 0.002 * ((rows - size / 2) ** 2 + (cols - size / 2) ** 2)
    return DEMData(
        array=array,
        transform=Affine(res, 0, minx, 0, -res, maxy),
        crs="EPSG:32644",
        resolution=res,
        bounds=(minx, maxy - size * res, minx + size * res, maxy),
    )


def point_feature(category, lat=LAT, lon=LON):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": {"category": category}}


def test_zone_buffers_follow_category_and_scale():
    one = build_exclusion_zones([point_feature("facility")], LAT, LON, survey_radius_m=300)
    two = build_exclusion_zones([point_feature("facility")], LAT, LON, survey_radius_m=300, buffer_scale=2.0)
    area_one, area_two = one["excluded_area_m2"], two["excluded_area_m2"]
    assert area_one == pytest.approx(np.pi * 30 ** 2, rel=0.02)  # facility buffer is 30 m
    assert area_two == pytest.approx(4 * area_one, rel=0.02)
    assert one["counts"] == {"facility": 1}


def test_categories_filter_and_manual_zones():
    feats = [point_feature("building"), point_feature("road")]
    zones = build_exclusion_zones(
        feats, LAT, LON, 300, categories=["road"], manual_zones=parse_manual_zones('[{"lat": 21.195, "lon": 81.482, "radius_m": 50}]')
    )
    assert zones["counts"] == {"road": 1, "manual": 1}
    assert parse_categories("water, bogus,road") == ["water", "road"]
    assert parse_manual_zones("not json") == []
    assert parse_manual_zones([{"lat": 200, "lon": 0}]) == []


def test_apply_exclusions_masks_zone_and_outside_survey():
    dem = flat_dem()
    result = TerrainAnalysisService().analyze_terrain(dem)
    plan = build_exclusion_zones([point_feature("facility")], LAT, LON, survey_radius_m=200)
    stats = apply_exclusions(result, plan["zones"], plan["survey"])
    assert stats["zone_cells"] > 20
    assert stats["outside_survey_cells"] > 0
    # Cell at the centre (under the facility) and a corner (outside the survey) are both blocked.
    assert result.suitability_score[30, 30] == 0
    assert result.suitability_score[0, 0] == 0


def test_ranked_sites_never_sit_on_excluded_infrastructure():
    dem = flat_dem()
    baseline = PondSiteService().identify_candidate_sites(TerrainAnalysisService().analyze_terrain(dem), top_n=5)
    assert baseline.candidates
    top = baseline.candidates[0]
    plan = build_exclusion_zones([point_feature("water", top.latitude, top.longitude)], LAT, LON, survey_radius_m=280)
    zone = shape(plan["zones"]["features"][0]["geometry"])
    result = TerrainAnalysisService().analyze_terrain(dem)
    apply_exclusions(result, plan["zones"], plan["survey"])
    sited = PondSiteService().identify_candidate_sites(result, top_n=5, max_footprint_m2=20000)
    for candidate in sited.candidates:
        assert not zone.contains(Point(candidate.longitude, candidate.latitude))
        assert candidate.polygon_wgs84.intersection(zone).area < 1e-12


def test_oversized_regions_are_carved_and_pin_stays_on_footprint():
    dem = flat_dem(size=80)
    result = TerrainAnalysisService().analyze_terrain(dem)
    sited = PondSiteService().identify_candidate_sites(result, top_n=3, max_footprint_m2=5000)
    assert sited.candidates
    assert all(c.area_m2 <= 5000 for c in sited.candidates)
    assert any("Carved" in note for note in sited.notes)
    for c in sited.candidates:
        assert c.polygon_wgs84.buffer(1e-6).contains(Point(c.longitude, c.latitude))


def test_summary_notes_for_unavailable_lookup():
    plan = plan_exclusions({"status": "unavailable"}, LAT, LON, 300, manual_zones=parse_manual_zones([{"lat": LAT, "lon": LON}]))
    assert plan["apply_survey"] is False
    outcome = summarize({"status": "unavailable"}, plan, {"zone_area_m2": 0}, None, 1.0)
    assert outcome["summary"]["status"] == "unavailable"
    assert "could not be checked" in outcome["note"]
    assert "1 user-marked" in outcome["note"]


# -- global DEM terrain source ---------------------------------------------------


def terrarium_png(elevation):
    """Encode a 256x256 elevation array as a Terrarium PNG with rasterio."""
    from rasterio.io import MemoryFile

    value = elevation + 32768.0
    r = np.floor(value / 256)
    g = np.floor(value - r * 256)
    b = np.round((value - np.floor(value)) * 256).clip(0, 255)
    with MemoryFile() as memfile:
        with memfile.open(driver="PNG", width=256, height=256, count=3, dtype="uint8") as ds:
            ds.write(np.stack([r, g, b]).astype("uint8"))
        return memfile.read()


def test_terrarium_decoding_round_trips():
    elevation = np.full((256, 256), 287.25, dtype="float32")
    assert np.allclose(terrain_source.decode_terrarium(terrarium_png(elevation)), 287.25, atol=0.01)


def test_global_dem_is_resampled_to_local_utm(monkeypatch):
    # A plane rising 1 m per tile pixel eastwards, so slope and orientation are known.
    plane = np.tile(np.arange(256, dtype="float32"), (256, 1)) + 200.0
    monkeypatch.setattr(terrain_source, "_fetch_tile", lambda z, x, y: plane + 256.0 * (x % 2))
    dem = terrain_source.fetch_global_dem(LAT, LON, half_size_m=500, resolution_m=10)
    assert dem.crs == "EPSG:32644"
    assert dem.shape == (100, 100)
    assert dem.resolution == 10
    assert np.all(np.diff(dem.array[50, 5:-5]) > 0)  # still rising eastwards after resampling


def test_global_dem_reports_unavailable_source(monkeypatch):
    monkeypatch.setattr(terrain_source, "_fetch_tile", lambda z, x, y: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(ValueError, match="Global elevation data is unavailable"):
        terrain_source.fetch_global_dem(LAT, LON)


def test_bundled_extent_check():
    assert terrain_source.point_in_bundled_extent(21.2517, 81.2970)
    assert not terrain_source.point_in_bundled_extent(LAT, LON)


# -- API: click anywhere, avoid infrastructure ---------------------------------


@pytest.fixture
def synthetic_global_dem(monkeypatch):
    import app.services.pipeline as pipeline

    dem = flat_dem(size=120)
    monkeypatch.setattr(pipeline, "fetch_global_dem", lambda *args, **kwargs: dem)
    monkeypatch.setattr(terrain_source, "fetch_global_dem", lambda *args, **kwargs: dem)
    return dem


def school_at(lat, lon):
    return {"status": "ok", "source": "test", "message": "1", "features": {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": {"category": "facility"}}]}}


def test_fastapi_recommends_anywhere_and_avoids_infrastructure(synthetic_global_dem, monkeypatch):
    from fastapi.testclient import TestClient

    import app.services.pipeline as pipeline
    from app.main import app

    client = TestClient(app)
    form = {"selected_latitude": LAT, "selected_longitude": LON, "selected_radius_m": 250}
    first = client.post("/analyzeContour", data=form).json()
    assert first["terrain_source"] == "global_dem"
    top = first["recommended_site"]

    monkeypatch.setattr(pipeline, "fetch_infrastructure", lambda *a, **k: school_at(top["latitude"], top["longitude"]))
    body = client.post("/analyzeContour", data={**form, "manual_exclusions": json.dumps([{"lat": LAT, "lon": LON + 0.002, "radius_m": 40}])}).json()
    assert body["infrastructure"]["counts"] == {"facility": 1, "manual": 1}
    zones = [shape(f["geometry"]) for f in body["infrastructure"]["zones_geojson"]["features"]]
    for site in [body["recommended_site"], *body["alternative_sites"]]:
        assert not any(z.contains(Point(site["longitude"], site["latitude"])) for z in zones)
    assert any("Excluded existing infrastructure" in n for n in body["processing_notes"])


def test_fastapi_can_disable_infrastructure_avoidance(synthetic_global_dem, monkeypatch):
    from fastapi.testclient import TestClient

    import app.services.pipeline as pipeline
    from app.main import app

    monkeypatch.setattr(pipeline, "fetch_infrastructure", lambda *a, **k: pytest.fail("lookup should be skipped"))
    body = TestClient(app).post(
        "/analyzeContour",
        data={"selected_latitude": LAT, "selected_longitude": LON, "selected_radius_m": 250, "avoid_infrastructure": "false"},
    ).json()
    assert body["infrastructure"] is None


def test_gateway_global_dem_job_applies_exclusions(synthetic_global_dem, monkeypatch):
    import distributed.stages as stages
    import distributed.sys4 as sys4
    from distributed.config import ServiceConfig

    monkeypatch.setattr(
        stages, "global_dem_stage",
        lambda lat, lon, params=None: (stages.ParsedContoursPayload(features=[]), stages.DEMPayload.from_dem_data(synthetic_global_dem)),
    )
    monkeypatch.setattr(sys4, "global_dem_stage", stages.global_dem_stage)
    monkeypatch.setattr(sys4, "fetch_infrastructure", lambda *a, **k: school_at(LAT, LON))
    app = sys4.create_app(ServiceConfig(node_name="gw"))
    client = app.test_client()
    submitted = client.post("/v1/jobs", data={"selected_latitude": LAT, "selected_longitude": LON, "selected_radius_m": 250})
    job = app.extensions["jalasetu_jobs"].get(submitted.get_json()["job_id"])
    assert job.done.wait(120)
    result = client.get(f"/v1/jobs/{job.id}").get_json()["result"]
    assert result["terrain_source"] == "global_dem"
    assert result["infrastructure"]["counts"] == {"facility": 1}
    zone = shape(result["infrastructure"]["zones_geojson"]["features"][0]["geometry"])
    assert not zone.contains(Point(result["recommended_site"]["longitude"], result["recommended_site"]["latitude"]))
    assert "infrastructure" in [s["stage"] for s in result["execution"]["stages"]]


@pytest.mark.live_infrastructure
def test_concurrent_lookups_of_one_area_share_a_single_request(monkeypatch):
    import threading
    import time as time_module

    from app.services import infrastructure

    calls = []

    def slow_fetch(query, budget_s):
        calls.append(query)
        time_module.sleep(0.3)
        return {"elements": []}, "https://overpass.example/api/interpreter"

    monkeypatch.setattr(infrastructure, "_fetch", slow_fetch)
    monkeypatch.setattr(infrastructure, "_cache", {})
    results = []
    threads = [threading.Thread(target=lambda: results.append(infrastructure.fetch_infrastructure(21.3, 81.6, 400))) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(calls) == 1
    assert [r["status"] for r in results] == ["ok"] * 4


@pytest.mark.live_infrastructure
def test_failed_lookup_fails_fast_during_cooldown(monkeypatch):
    from app.services import infrastructure

    calls = []

    def down(query, budget_s):
        calls.append(query)
        raise RuntimeError("overpass down")

    monkeypatch.setattr(infrastructure, "_fetch", down)
    monkeypatch.setattr(infrastructure, "_cache", {})
    monkeypatch.setattr(infrastructure, "_unavailable_until", 0.0)
    assert infrastructure.fetch_infrastructure(21.31, 81.61, 400)["status"] == "unavailable"
    assert infrastructure.fetch_infrastructure(21.32, 81.62, 400)["status"] == "unavailable"
    assert len(calls) == 1
