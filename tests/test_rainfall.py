"""Unit and integration tests for Rainfall API and Climatological Service."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.rainfall_service import RainfallService, _get_regional_fallback


@pytest.fixture
def rainfall_service():
    return RainfallService()


@pytest.fixture
def client():
    return TestClient(app)


def test_rainfall_service_regional_fallback():
    # Test regional fallback for central India (Bhilai / Raipur region)
    data = _get_regional_fallback(21.26, 81.28)
    assert data["mean_annual_rainfall_mm"] > 1000
    assert data["monsoon_rainfall_mm"] > 800
    assert data["monsoon_share_pct"] > 70
    assert data["design_24h_rainfall_mm"] > 50
    assert len(data["monthly_averages_mm"]) == 12
    assert data["is_fallback"] is True


def test_rainfall_service_caching(rainfall_service):
    # Test cache insertion and retrieval
    res1 = rainfall_service.get_rainfall_data(21.26, 81.28)
    assert res1 is not None
    assert "mean_annual_rainfall_mm" in res1

    # Second call should return cached payload
    res2 = rainfall_service.get_rainfall_data(21.26, 81.28)
    assert res1["mean_annual_rainfall_mm"] == res2["mean_annual_rainfall_mm"]


def test_rainfall_api_get_success(client):
    response = client.get("/v1/rainfall?lat=21.26&lon=81.28")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "mean_annual_rainfall_mm" in data
    assert "monsoon_rainfall_mm" in data
    assert "design_24h_rainfall_mm" in data
    assert len(data["monthly_averages_mm"]) == 12
    assert data["location"]["latitude"] == pytest.approx(21.26, 0.001)
    assert data["location"]["longitude"] == pytest.approx(81.28, 0.001)


def test_rainfall_api_alias_route(client):
    response = client.get("/api/rainfall?latitude=21.26&longitude=81.28")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["mean_annual_rainfall_mm"] > 0


def test_rainfall_api_post(client):
    response = client.post("/v1/rainfall", json={"latitude": 21.26, "longitude": 81.28})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["mean_annual_rainfall_mm"] > 0


def test_rainfall_api_missing_coordinates(client):
    response = client.get("/v1/rainfall")
    assert response.status_code == 400
    assert "required" in response.json()["detail"].lower()
