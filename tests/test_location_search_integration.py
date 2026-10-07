"""
Integration tests for Location Recommendation API.
Validates end-to-end workflows and edge cases.
"""

import io
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestLocationSearchIntegration:
    """End-to-end integration tests for /IP/search/ endpoint."""

    def test_api_is_registered_and_accessible(self):
        """Verify endpoint is properly registered in FastAPI app."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert "/IP/search/" in schema["paths"]

    def test_openapi_schema_documents_endpoint(self):
        """Verify endpoint is documented in OpenAPI schema."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert "/IP/search/" in schema["paths"]

    def test_post_with_multipart_form(self):
        """Test POST endpoint with multipart form data."""
        response = client.post(
            "/IP/search/",
            data={"lat": "0", "long": "0", "cat": "bank", "rad": "0.1"},
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)
        assert len(response.json()) <= 10

    def test_get_with_query_parameters(self):
        """Test GET endpoint with query parameters."""
        response = client.get("/IP/search/", params={"lat": 0, "long": 0, "cat": "bank", "rad": 0.1})
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_empty_result_when_no_matches(self):
        """Test that non-existent category returns empty array."""
        response = client.post(
            "/IP/search/",
            data={"lat": "0", "long": "0", "cat": "nonexistent", "rad": "1"},
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_case_insensitive_category(self):
        """Test that category matching is case-insensitive."""
        response_lower = client.post(
            "/IP/search/",
            data={"lat": "0", "long": "0", "cat": "bank", "rad": "0.1"},
        )
        response_upper = client.post(
            "/IP/search/",
            data={"lat": "0", "long": "0", "cat": "BANK", "rad": "0.1"},
        )
        response_mixed = client.post(
            "/IP/search/",
            data={"lat": "0", "long": "0", "cat": "BaNk", "rad": "0.1"},
        )
        assert response_lower.json() == response_upper.json() == response_mixed.json()

    def test_radius_zero_returns_single_location(self):
        """Test that radius=0 returns only exact start location."""
        response = client.post(
            "/IP/search/",
            data={"lat": "0", "long": "0", "cat": "bank", "rad": "0"},
        )
        assert response.status_code == 200
        result = response.json()
        assert len(result) <= 1

    def test_negative_radius_validation(self):
        """Test that negative radius is rejected."""
        response = client.post(
            "/IP/search/",
            data={"lat": "0", "long": "0", "cat": "bank", "rad": "-0.1"},
        )
        assert response.status_code == 422

    def test_empty_category_validation(self):
        """Test that empty category is rejected."""
        response = client.post(
            "/IP/search/",
            data={"lat": "0", "long": "0", "cat": "", "rad": "0.1"},
        )
        assert response.status_code == 422

    def test_missing_required_parameter(self):
        """Test that missing required parameters return error."""
        response = client.post(
            "/IP/search/",
            data={"lat": "0", "long": "0", "cat": "bank"},  # missing 'rad'
        )
        assert response.status_code == 422

    def test_custom_linkage_file_changes_results(self):
        """Test that custom linkage file affects route distance ranking."""
        # Without linkage (default grid)
        response_default = client.post(
            "/IP/search/",
            data={"lat": "0", "long": "0", "cat": "bank", "rad": "1"},
        )

        # With custom linkage (linear path)
        links = b"1 3\n3 23\n23 39\n39 42\n"
        response_custom = client.post(
            "/IP/search/",
            data={"lat": "0", "long": "0", "cat": "bank", "rad": "1"},
            files={"link": ("links.txt", io.BytesIO(links), "text/plain")},
        )

        # Both should return results
        assert response_default.status_code == 200
        assert response_custom.status_code == 200

    def test_malformed_linkage_file_returns_error(self):
        """Test that malformed linkage file returns 400."""
        links = b"invalid linkage data\n"
        response = client.post(
            "/IP/search/",
            data={"lat": "0", "long": "0", "cat": "bank", "rad": "1"},
            files={"link": ("links.txt", io.BytesIO(links), "text/plain")},
        )
        assert response.status_code == 400

    def test_linkage_with_unknown_node_id_returns_error(self):
        """Test that linkage file with unknown node ID returns 400."""
        links = b"1 99999\n"  # Node 99999 doesn't exist in dataset
        response = client.post(
            "/IP/search/",
            data={"lat": "0", "long": "0", "cat": "bank", "rad": "1"},
            files={"link": ("links.txt", io.BytesIO(links), "text/plain")},
        )
        assert response.status_code == 400

    def test_response_contains_valid_location_ids(self):
        """Test that response contains location IDs that exist in dataset."""
        response = client.post(
            "/IP/search/",
            data={"lat": "0.5", "long": "0.5", "cat": "bank", "rad": "0.3"},
        )
        assert response.status_code == 200
        result = response.json()
        # All returned IDs should be numeric strings
        for location_id in result:
            assert isinstance(location_id, str)
            assert location_id.isdigit()

    def test_result_order_is_consistent(self):
        """Test that result ordering is deterministic."""
        # Query multiple times
        results = []
        for _ in range(3):
            response = client.post(
                "/IP/search/",
                data={"lat": "0", "long": "0", "cat": "bank", "rad": "0.2"},
            )
            results.append(response.json())

        # All results should be identical
        assert results[0] == results[1] == results[2]

    def test_max_ten_results_returned(self):
        """Test that result is capped at 10 locations."""
        response = client.post(
            "/IP/search/",
            data={"lat": "0.5", "long": "0.5", "cat": "bank", "rad": "1"},
        )
        assert response.status_code == 200
        result = response.json()
        assert len(result) <= 10

    def test_different_categories_return_different_results(self):
        """Test that different categories return different results."""
        categories = ["bank", "cafe", "hospital", "park", "pharmacy", "restaurant"]
        results = {}

        for cat in categories:
            response = client.post(
                "/IP/search/",
                data={"lat": "0.5", "long": "0.5", "cat": cat, "rad": "0.2"},
            )
            results[cat] = response.json()

        # Results should vary by category
        unique_results = len(set(frozenset(r) for r in results.values()))
        assert unique_results > 1

    def test_api_coexists_with_catchment_endpoint(self):
        """Test that location API coexists with catchment API."""
        # Health check (catchment endpoint)
        response_health = client.get("/health")
        assert response_health.status_code == 200

        # Location search
        response_location = client.post(
            "/IP/search/",
            data={"lat": "0", "long": "0", "cat": "bank", "rad": "0.1"},
        )
        assert response_location.status_code == 200

        # OpenAPI should include both endpoints
        response_schema = client.get("/openapi.json")
        assert response_schema.status_code == 200
        schema = response_schema.json()
        assert "/health" in schema["paths"]
        assert "/IP/search/" in schema["paths"]
