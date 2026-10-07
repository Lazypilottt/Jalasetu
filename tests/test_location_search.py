import io

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_location_search_filters_radius_and_category():
    response = client.post(
        "/IP/search/",
        data={"lat": "0", "long": "0", "cat": "bank", "rad": "0.04"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result[0] == "1"
    assert len(result) >= 1


def test_location_search_uses_link_graph_distance():
    links = b"1 101\n101 201\n201 301\n"
    response = client.post(
        "/IP/search/",
        data={"lat": "0", "long": "0", "cat": "bank", "rad": "1"},
        files={"link": ("links.txt", io.BytesIO(links), "text/plain")},
    )
    assert response.status_code == 200
    assert response.json()[0] == "1"


def test_location_search_query_form():
    response = client.get("/IP/search/", params={"lat": 0, "long": 0, "cat": "bank", "rad": 0})
    assert response.status_code == 200
    assert response.json() == ["1"]
