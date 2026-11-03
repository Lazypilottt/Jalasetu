"""Shared fixtures: keep the suite off the network by default."""

import pytest

EMPTY_INFRASTRUCTURE = {
    "status": "ok",
    "source": "test",
    "message": "No mapped infrastructure (test stub).",
    "features": {"type": "FeatureCollection", "features": []},
    "counts": {},
}


@pytest.fixture(autouse=True)
def offline_infrastructure(request, monkeypatch):
    """Stub the OpenStreetMap lookup unless a test is marked ``live_infrastructure``."""
    if request.node.get_closest_marker("live_infrastructure"):
        return
    import app.services.pipeline as pipeline
    import distributed.sys4 as sys4

    stub = lambda *args, **kwargs: dict(EMPTY_INFRASTRUCTURE)  # noqa: E731
    monkeypatch.setattr(pipeline, "fetch_infrastructure", stub)
    monkeypatch.setattr(sys4, "fetch_infrastructure", stub)


def pytest_configure(config):
    config.addinivalue_line("markers", "live_infrastructure: use the real infrastructure lookup")
