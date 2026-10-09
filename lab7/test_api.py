import heapq
import math
import random

from fastapi.testclient import TestClient

from app.main import app, store


def brute_force(latitude, longitude, category, radius):
    eligible = {
        index
        for index, row in enumerate(store.rows)
        if row[3] == category
        and math.hypot(row[1] - latitude, row[2] - longitude) <= radius
    }
    distances = {store.start_node(latitude, longitude): 0.0}
    queue = [(0.0, next(iter(distances)))]
    while queue:
        distance, current = heapq.heappop(queue)
        if distance != distances[current]:
            continue
        for neighbor, weight in store.neighbors(current):
            candidate = distance + weight
            if candidate < distances.get(neighbor, math.inf):
                distances[neighbor] = candidate
                heapq.heappush(queue, (candidate, neighbor))
    found = [(distances[index], store.rows[index][0]) for index in eligible if index in distances]
    return [location_id for _, location_id in sorted(found, key=lambda item: (item[0], item[1]))[:10]]


def test_random_queries_match_full_dijkstra_oracle():
    random.seed(19)
    checked = 0
    for _ in range(80):
        query = (random.random(), random.random(), random.choice(["bank", "cafe", "hospital", "park"]), random.uniform(0.08, 0.35))
        expected = brute_force(*query)
        if len(expected) < 10:
            continue
        assert store.recommend(*query, None) == expected
        checked += 1
    assert checked >= 50


def test_numeric_zero_linkage_uses_zero_based_indexes():
    links = "0 1\n1 2\n"
    assert store.links(links)[0][0][0] == 1


def test_api_get_and_post_contract():
    client = TestClient(app)
    get_response = client.get("/IP/search/?lat=0.5&long=0.5&cat=bank&rad=0.1")
    post_response = client.post(
        "/IP/search/",
        data={"lat": "0.5", "long": "0.5", "cat": "bank", "rad": "0.1"},
    )
    assert get_response.status_code == 200
    assert post_response.status_code == 200
    assert get_response.json() == post_response.json()
    assert len(get_response.json()) == 10


def test_extreme_radius_is_bounded_and_nonfinite_values_are_rejected():
    client = TestClient(app)
    huge = client.get("/IP/search/?lat=999&long=-999&cat=bank&rad=999999")
    infinite = client.get("/IP/search/?lat=0.5&long=0.5&cat=bank&rad=inf")
    assert huge.status_code == 200
    assert len(huge.json()) == 10
    assert infinite.status_code == 422
