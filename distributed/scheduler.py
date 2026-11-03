"""Capacity-aware placement of pipeline stages across the cluster.

The gateway asks every node for its ``/health`` capacity report and places
each stage on the node that is accepting work, has the fewest stages in
flight, matches the stage's affinity, and has the most memory headroom, in
that order. A node that answers 503 busy is skipped for the next one. If every
reachable node is busy the stage waits, up to the queue timeout, rather than
being forced onto a saturated 500 MB node. Only when no remote node is
reachable at all does the gateway run the stage itself without a reserve
check, which preserves the original fail-over behaviour.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from .capacity import CapacityGuard, StorageMonitor
from .config import ServiceConfig

logger = logging.getLogger(__name__)

ALL_STAGES = ("prepare", "analyze", "catchment")
HEALTH_TTL_SECONDS = 2.0
BUSY_BACKOFF_SECONDS = (0.5, 1.0, 2.0, 3.0)

Observer = Callable[[Dict[str, Any]], None]


class ClusterBusyError(RuntimeError):
    """No node had capacity for a stage before the queue timeout."""


class StageRejectedError(ValueError):
    """A worker rejected the stage input itself (HTTP 4xx); retrying elsewhere cannot help."""


@dataclass
class NodeState:
    name: str
    url: str  # empty for the gateway itself
    role: str = "stage-worker"
    stages: Tuple[str, ...] = ()
    affinity: Tuple[str, ...] = ()
    reachable: Optional[bool] = None
    capacity: Dict[str, Any] = field(default_factory=dict)
    storage: Dict[str, Any] = field(default_factory=dict)
    latency_ms: Optional[float] = None
    last_seen: Optional[float] = None
    last_error: Optional[str] = None
    pending: int = 0  # dispatches this gateway has in flight to the node
    stages_run: int = 0

    @property
    def is_local(self) -> bool:
        return not self.url

    def accepting(self) -> bool:
        return bool(self.reachable) and bool(self.capacity.get("accepting")) and self.pending == 0

    def load(self) -> int:
        return int(self.capacity.get("in_flight", 0)) + self.pending

    def headroom_mb(self) -> float:
        return float(self.capacity.get("memory", {}).get("headroom_mb", 0.0))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "local": self.is_local,
            "reachable": self.reachable,
            "stages": list(self.stages),
            "affinity": list(self.affinity),
            "capacity": self.capacity,
            "storage": self.storage,
            "latency_ms": self.latency_ms,
            "last_seen": self.last_seen,
            "last_error": self.last_error,
            "pending": self.pending,
            "stages_run": self.stages_run,
        }


class WorkerPool:
    def __init__(self, config: ServiceConfig, local_guard: CapacityGuard):
        self.config = config
        self.local_guard = local_guard
        self.local_storage = StorageMonitor()
        self._lock = threading.Lock()
        self._refreshed_at = 0.0
        self._refresh_lock = threading.Lock()
        self.local = NodeState(
            name=config.node_name,
            url="",
            role="gateway",
            stages=ALL_STAGES,
            reachable=True,
        )
        self.workers = [NodeState(name=name, url=url) for name, url in config.workers]
        self.edge = NodeState(name="sys1", url=config.edge_url, role="edge") if config.edge_url else None
        self._probe_pool = ThreadPoolExecutor(max_workers=max(1, len(self.remote_nodes)), thread_name_prefix="probe")

    @property
    def remote_nodes(self) -> List[NodeState]:
        return self.workers + ([self.edge] if self.edge else [])

    @property
    def nodes(self) -> List[NodeState]:
        return ([self.edge] if self.edge else []) + self.workers + [self.local]

    # -- health ---------------------------------------------------------

    def _probe(self, node: NodeState) -> None:
        started = time.perf_counter()
        try:
            response = requests.get(f"{node.url}/health", timeout=self.config.probe_timeout_seconds)
            body = response.json() if response.ok else {}
            if not response.ok:
                raise RuntimeError(f"HTTP {response.status_code}")
        except Exception as exc:
            with self._lock:
                node.reachable = False
                node.last_error = str(exc)[:160]
                node.latency_ms = None
            return
        with self._lock:
            node.reachable = True
            node.last_error = None
            node.latency_ms = round((time.perf_counter() - started) * 1000, 1)
            node.last_seen = time.time()
            node.role = body.get("role", node.role)
            node.stages = tuple(body.get("stages") or ())
            node.affinity = tuple(body.get("affinity") or ())
            node.capacity = body.get("capacity") or {}
            node.storage = body.get("storage") or {}

    def refresh(self, force: bool = False) -> None:
        if not force and time.time() - self._refreshed_at < HEALTH_TTL_SECONDS:
            return
        with self._refresh_lock:
            if not force and time.time() - self._refreshed_at < HEALTH_TTL_SECONDS:
                return
            list(self._probe_pool.map(self._probe, self.remote_nodes))
            with self._lock:
                self.local.capacity = self.local_guard.report()
                self.local.storage = self.local_storage.report()
                self.local.last_seen = time.time()
            self._refreshed_at = time.time()

    def snapshot(self) -> Dict[str, Any]:
        self.refresh()
        with self._lock:
            nodes = [node.to_dict() for node in self.nodes]
        reachable = [node for node in nodes if node["reachable"]]
        return {
            "cluster_status": "ok" if len(reachable) == len(nodes) else "degraded",
            "nodes": nodes,
            "updated_at": time.time(),
        }

    # -- placement ------------------------------------------------------

    def ranked(self, stage: str) -> List[NodeState]:
        """Eligible nodes for ``stage``, best first."""
        self.refresh()
        with self._lock:
            local_capacity = self.local_guard.report()
            self.local.capacity = local_capacity
            eligible = [n for n in self.workers + [self.local] if stage in n.stages and n.reachable]
            return sorted(
                eligible,
                key=lambda n: (
                    not n.accepting(),
                    n.load(),
                    stage not in n.affinity,
                    -n.headroom_mb(),
                    n.is_local,
                ),
            )

    def _post(self, node: NodeState, endpoint: str, body: bytes) -> requests.Response:
        return requests.post(
            f"{node.url}{endpoint}",
            data=body,
            headers={"Content-Type": "application/json"},
            timeout=(3.0, self.config.request_timeout_seconds),
        )

    def run(
        self,
        stage: str,
        endpoint: str,
        payload: Dict[str, Any],
        local_fn: Callable[[], Any],
        decode: Callable[[Dict[str, Any]], Any],
        observer: Optional[Observer] = None,
    ) -> Tuple[Any, Dict[str, Any]]:
        """Run one stage on the best node. Returns ``(result, trace_record)``."""
        started = time.perf_counter()
        deadline = time.monotonic() + self.config.queue_timeout_seconds
        attempts: List[Dict[str, str]] = []
        encoded: Optional[bytes] = None
        waits = 0

        def finish(node: NodeState, mode: str, result: Any) -> Tuple[Any, Dict[str, Any]]:
            with self._lock:
                node.stages_run += 1
            record = {
                "stage": stage,
                "node": node.name,
                "mode": mode,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "attempts": attempts,
            }
            if observer:
                observer({"event": "stage_completed", **record})
            return result, record

        while True:
            candidates = self.ranked(stage)
            for node in candidates:
                if observer:
                    observer({"event": "stage_dispatched", "stage": stage, "node": node.name})
                if node.is_local:
                    with self.local_guard.slot() as admitted:
                        if admitted:
                            return finish(node, "local", local_fn())
                    attempts.append({"node": node.name, "outcome": "busy"})
                    continue

                if encoded is None:
                    encoded = json.dumps(payload).encode("utf-8")
                with self._lock:
                    node.pending += 1
                try:
                    response = self._post(node, endpoint, encoded)
                except requests.RequestException as exc:
                    logger.warning("Stage %s on %s failed: %s", stage, node.name, exc)
                    with self._lock:
                        node.reachable = False
                        node.last_error = str(exc)[:160]
                    attempts.append({"node": node.name, "outcome": "unreachable"})
                    continue
                finally:
                    with self._lock:
                        node.pending -= 1

                if response.status_code == 200:
                    return finish(node, "remote", decode(response.json()))
                if response.status_code == 503:
                    body = _json_or_empty(response)
                    with self._lock:
                        node.capacity = body.get("capacity", node.capacity) or {}
                        node.capacity["accepting"] = False
                    attempts.append({"node": node.name, "outcome": "busy"})
                    continue
                if 400 <= response.status_code < 500:
                    message = _json_or_empty(response).get("error") or response.text[:200]
                    raise StageRejectedError(message)
                attempts.append({"node": node.name, "outcome": f"http_{response.status_code}"})
                logger.warning("Stage %s on %s returned HTTP %s", stage, node.name, response.status_code)

            if not any(n.reachable for n in self.workers):
                # Nothing to wait for: degrade to the pre-scheduler behaviour.
                logger.warning("No stage worker reachable; running %s on %s", stage, self.local.name)
                attempts.append({"node": self.local.name, "outcome": "degraded"})
                return finish(self.local, "local-degraded", local_fn())

            if time.monotonic() >= deadline:
                raise ClusterBusyError(
                    f"No node had capacity for the {stage} stage within "
                    f"{self.config.queue_timeout_seconds:.0f}s. Please retry shortly."
                )
            if observer:
                observer({"event": "stage_waiting", "stage": stage})
            time.sleep(BUSY_BACKOFF_SECONDS[min(waits, len(BUSY_BACKOFF_SECONDS) - 1)])
            waits += 1
            self.refresh(force=True)


def _json_or_empty(response: requests.Response) -> Dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}
