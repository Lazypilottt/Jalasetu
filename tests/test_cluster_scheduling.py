"""Capacity guard, stage placement, job queue, and edge service contracts."""

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from distributed import capacity as capacity_module
from distributed import scheduler as scheduler_module
from distributed.capacity import CapacityGuard
from distributed.config import ServiceConfig, _parse_workers
from distributed.jobs import JobManager, QueueFullError
from distributed.scheduler import ClusterBusyError, StageRejectedError, WorkerPool


def fixed_memory(used_mb, limit_mb=None):
    def reader():
        return {
            "source": "test",
            "working_set": int(used_mb * capacity_module.MB),
            "limit": int(limit_mb * capacity_module.MB) if limit_mb else None,
        }

    return reader


# -- capacity ----------------------------------------------------------------


def test_guard_refuses_when_headroom_below_stage_reserve(monkeypatch):
    monkeypatch.setattr(capacity_module, "read_memory", fixed_memory(400))
    guard = CapacityGuard(slots=2, memory_budget_mb=500, stage_reserve_mb=150)
    assert guard.report()["memory"]["headroom_mb"] == 100
    assert guard.try_acquire() is False
    assert guard.rejected == 1


def test_guard_limits_concurrent_slots(monkeypatch):
    monkeypatch.setattr(capacity_module, "read_memory", fixed_memory(100))
    guard = CapacityGuard(slots=1, memory_budget_mb=500, stage_reserve_mb=150)
    with guard.slot() as first:
        assert first is True
        with guard.slot() as second:
            assert second is False
    assert guard.in_flight == 0
    assert guard.completed == 1


def test_guard_budget_never_exceeds_cgroup_limit(monkeypatch):
    monkeypatch.setattr(capacity_module, "read_memory", fixed_memory(100, limit_mb=400))
    guard = CapacityGuard(memory_budget_mb=500)
    assert guard.memory()["budget_mb"] == 400


def test_parse_workers_accepts_names_and_bare_urls():
    assert _parse_workers("sys2=http://a:1/, http://b:2") == (("sys2", "http://a:1"), ("worker2", "http://b:2"))


# -- placement ---------------------------------------------------------------


class FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.ok = status < 400
        self.text = json.dumps(body)

    def json(self):
        return self._body


def worker_health(name, accepting=True, in_flight=0, headroom=300, affinity=()):
    return {
        "status": "ok",
        "service": name,
        "role": "stage-worker",
        "stages": ["prepare", "analyze", "catchment"],
        "affinity": list(affinity),
        "capacity": {"accepting": accepting, "in_flight": in_flight, "memory": {"headroom_mb": headroom}},
    }


@pytest.fixture
def pool_factory(monkeypatch):
    monkeypatch.setattr(capacity_module, "read_memory", fixed_memory(450))  # gateway itself is full

    def build(health, post_status=None, queue_timeout=0.0):
        posts = []

        def fake_get(url, timeout):
            name = url.split("//")[1].split("/")[0]
            return FakeResponse(200, health[name])

        def fake_post(url, data, headers, timeout):
            name = url.split("//")[1].split("/")[0]
            posts.append(name)
            status = (post_status or {}).get(name, 200)
            return FakeResponse(status, {"ok": name} if status == 200 else {"error": "nope"})

        monkeypatch.setattr(scheduler_module.requests, "get", fake_get)
        monkeypatch.setattr(scheduler_module.requests, "post", fake_post)
        monkeypatch.setattr(scheduler_module, "BUSY_BACKOFF_SECONDS", (0.0,))
        config = ServiceConfig(
            workers=tuple((name, f"http://{name}") for name in health),
            queue_timeout_seconds=queue_timeout,
        )
        guard = CapacityGuard(memory_budget_mb=500, stage_reserve_mb=150)
        return WorkerPool(config, guard), posts

    return build


def run_stage(pool, stage="prepare"):
    return pool.run(stage, f"/v1/{stage}", {"x": 1}, local_fn=lambda: "local", decode=lambda d: d["ok"])


def test_affinity_breaks_ties_between_idle_workers(pool_factory):
    pool, _ = pool_factory(
        {"sys2": worker_health("sys2", affinity=("prepare",)), "sys3": worker_health("sys3", affinity=("analyze",))}
    )
    assert run_stage(pool, "prepare")[0] == "sys2"
    assert run_stage(pool, "analyze")[0] == "sys3"


def test_least_loaded_worker_wins_over_affinity(pool_factory):
    pool, _ = pool_factory(
        {
            "sys2": worker_health("sys2", in_flight=1, affinity=("prepare",)),
            "sys3": worker_health("sys3", in_flight=0),
        }
    )
    result, record = run_stage(pool, "prepare")
    assert result == "sys3"
    assert record["node"] == "sys3" and record["mode"] == "remote"


def test_busy_worker_is_skipped(pool_factory):
    pool, posts = pool_factory(
        {"sys2": worker_health("sys2", affinity=("prepare",)), "sys3": worker_health("sys3")},
        post_status={"sys2": 503},
    )
    result, record = run_stage(pool)
    assert posts == ["sys2", "sys3"]
    assert result == "sys3"
    assert record["attempts"] == [{"node": "sys2", "outcome": "busy"}]


def test_saturated_cluster_raises_busy_instead_of_overloading_gateway(pool_factory):
    pool, _ = pool_factory(
        {"sys2": worker_health("sys2", accepting=False), "sys3": worker_health("sys3", accepting=False)},
        post_status={"sys2": 503, "sys3": 503},
    )
    with pytest.raises(ClusterBusyError):
        run_stage(pool)


def test_unreachable_workers_degrade_to_local_execution(pool_factory, monkeypatch):
    pool, _ = pool_factory({"sys2": worker_health("sys2")})

    def down(*args, **kwargs):
        raise scheduler_module.requests.ConnectionError("refused")

    monkeypatch.setattr(scheduler_module.requests, "get", down)
    monkeypatch.setattr(scheduler_module.requests, "post", down)
    pool.refresh(force=True)
    result, record = run_stage(pool)
    assert result == "local"
    assert record["mode"] == "local-degraded"


def test_worker_input_rejection_is_not_retried(pool_factory):
    pool, posts = pool_factory(
        {"sys2": worker_health("sys2", affinity=("prepare",)), "sys3": worker_health("sys3")},
        post_status={"sys2": 422},
    )
    with pytest.raises(StageRejectedError):
        run_stage(pool)
    assert posts == ["sys2"]


# -- job queue ---------------------------------------------------------------


def test_job_queue_lifecycle_and_capacity():
    release = threading.Event()

    def runner(job):
        job.observe({"event": "stage_dispatched", "stage": "prepare", "node": "sys2"})
        release.wait(5)
        job.observe({"event": "stage_completed", "stage": "prepare", "node": "sys2", "mode": "remote"})
        return {"status": "success"}

    manager = JobManager(runner, max_active=1, max_queued=1, max_queued_mb=1)
    first = manager.submit(b"a", {}, True)
    second = manager.submit(b"b", {}, True)
    deadline = time.time() + 5
    while first.state != "running" and time.time() < deadline:
        time.sleep(0.01)
    with pytest.raises(QueueFullError):
        manager.submit(b"c", {}, True)
    assert manager.to_public(first)["node"] == "sys2"
    assert manager.queue_position(second) == 1
    release.set()
    assert second.done.wait(5)
    body = manager.to_public(first)
    assert body["state"] == "succeeded"
    assert body["result"] == {"status": "success"}
    assert body["stages"][0]["node"] == "sys2"
    assert first.file_bytes is None  # upload released once the job finishes


def test_job_queue_rejects_oversized_backlog():
    release = threading.Event()
    manager = JobManager(lambda job: release.wait(5) or {}, max_active=1, max_queued=5, max_queued_mb=1)
    manager.submit(b"x" * 800_000, {}, True)
    with pytest.raises(QueueFullError):
        manager.submit(b"y" * 800_000, {}, True)
    release.set()


# -- worker and gateway HTTP contracts -----------------------------------------


def test_worker_answers_503_when_guard_refuses(monkeypatch):
    from distributed.worker import create_worker_app

    monkeypatch.setattr(capacity_module, "read_memory", fixed_memory(480))
    client = create_worker_app("sysX", affinity=("prepare",)).test_client()
    health = client.get("/health").get_json()
    assert health["capacity"]["accepting"] is False
    assert health["affinity"] == ["prepare"]
    response = client.post("/v1/analyze", json={"dem": {}})
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "2"


NO_INFRASTRUCTURE = {"status": "ok", "source": "test", "message": "none", "features": {"type": "FeatureCollection", "features": []}}


def test_gateway_job_runs_all_stages_and_honours_selected_area(monkeypatch):
    import distributed.sys4 as sys4
    from distributed.sys4 import create_app

    monkeypatch.setattr(sys4, "fetch_infrastructure", lambda *args, **kwargs: NO_INFRASTRUCTURE)
    app = create_app(ServiceConfig(node_name="gw"))
    client = app.test_client()
    submitted = client.post(
        "/v1/jobs",
        data={"selected_latitude": "21.2517", "selected_longitude": "81.2970", "selected_radius_m": "250", "dem_resolution_m": "20"},
    )
    assert submitted.status_code == 202
    poll_url = submitted.get_json()["poll_url"]
    job = app.extensions["jalasetu_jobs"].get(poll_url.rsplit("/", 1)[1])
    assert job.done.wait(180)
    body = client.get(poll_url).get_json()
    assert body["state"] == "succeeded", body.get("error")
    result = body["result"]
    assert result["selected_area"]["radius_m"] == 250
    stages = result["execution"]["stages"]
    assert [s["stage"] for s in stages] == ["prepare", "infrastructure", "analyze", "climate", "catchment"]
    assert {s["node"] for s in stages} == {"gw"}
    assert result["terrain_source"] == "bundled_contours"
    assert result["infrastructure"]["status"] == "ok"
    assert "bundled contours_1m.kml" in result["processing_notes"][0]
    cluster = client.get("/v1/cluster").get_json()
    assert cluster["budgets"]["memory_mb"] <= 500
    assert client.get("/v1/jobs/missing").status_code == 404


# -- sys1 edge ---------------------------------------------------------------


@pytest.fixture
def edge_server(tmp_path, monkeypatch):
    from distributed import sys1

    (tmp_path / "index.html").write_text("<html>spa</html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setattr(sys1, "DIST_DIR", tmp_path.resolve())
    monkeypatch.setattr(sys1, "GATEWAY_URL", "http://127.0.0.1:9")
    server = sys1.ThreadingServer(("127.0.0.1", 0), sys1.EdgeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def fetch(url, headers=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=5) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def test_edge_health_reports_capacity_without_heavy_stages(edge_server):
    status, _, body = fetch(edge_server + "/health")
    health = json.loads(body)
    assert status == 200
    assert health["role"] == "edge" and health["stages"] == []
    assert health["capacity"]["accepting"] is False
    assert health["capacity"]["memory"]["budget_mb"] <= 500


def test_edge_rainfall_validates_coordinates(edge_server):
    assert fetch(edge_server + "/v1/rainfall?lat=21")[0] == 400
    assert fetch(edge_server + "/v1/rainfall?lat=abc&lon=81")[0] == 422
    assert fetch(edge_server + "/v1/rainfall?lat=95&lon=81")[0] == 422


def test_edge_serves_spa_shell_and_cacheable_assets(edge_server):
    status, headers, body = fetch(edge_server + "/some/client/route")
    assert status == 200 and b"spa" in body
    assert headers["Cache-Control"] == "no-cache"
    status, headers, _ = fetch(edge_server + "/assets/app.js")
    assert status == 200 and "immutable" in headers["Cache-Control"]
    # Path traversal falls back to the SPA shell instead of leaving dist/.
    assert b"spa" in fetch(edge_server + "/../../etc/passwd")[2]


def test_edge_refuses_to_proxy_a_looped_request(edge_server):
    status, _, body = fetch(edge_server + "/v1/cluster", headers={"X-JalaSetu-Edge": "sys1"})
    assert status == 508
    status, _, _ = fetch(edge_server + "/v1/cluster")
    assert status == 502  # gateway at port 9 is down


def test_edge_redirects_direct_outside_clients_to_public_entry(edge_server, monkeypatch):
    import http.client
    import ipaddress

    from distributed import sys1

    monkeypatch.setattr(sys1, "PUBLIC_URL", "http://10.1.75.51:3204")
    # Treat the test client (127.0.0.1) as an outside visitor.
    monkeypatch.setattr(sys1, "TRUSTED_NETWORKS", (ipaddress.ip_network("172.17.0.5/32"),))
    host, port = edge_server.split("//")[1].split(":")
    for method, path in (("GET", "/"), ("GET", "/assets/app.js?v=1"), ("POST", "/v1/jobs")):
        conn = http.client.HTTPConnection(host, int(port), timeout=5)
        conn.request(method, path)
        response = conn.getresponse()
        assert response.status == 308
        assert response.getheader("Location") == f"http://10.1.75.51:3204{path}"
        conn.close()

    monkeypatch.setattr(sys1, "TRUSTED_NETWORKS", (ipaddress.ip_network("127.0.0.0/8"),))
    assert fetch(edge_server + "/")[0] == 200


def test_page_cache_does_not_count_as_used_memory(tmp_path, monkeypatch):
    stat = "\n".join([
        "anon 144703488", "file 227540992", "active_file 110100480", "inactive_file 117440512",
        "shmem 0", "slab_unreclaimable 1048576", "kernel_stack 524288", "sock 0",
    ])
    (tmp_path / "memory.current").write_text("483393536")
    (tmp_path / "memory.stat").write_text(stat)
    (tmp_path / "memory.max").write_text("536870912")
    monkeypatch.setattr(capacity_module, "_CGROUP_V2", tmp_path)
    sample = capacity_module.read_memory()
    assert sample["source"] == "cgroup-v2"
    assert round(sample["working_set"] / capacity_module.MB) == 140  # anon + slab + stack, not the cache
    assert CapacityGuard(memory_budget_mb=500, stage_reserve_mb=150).try_acquire() is True
