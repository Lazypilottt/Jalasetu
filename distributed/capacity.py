"""Per-node memory and storage budgets for the distributed deployment.

Every cluster node is sized at 500 MB of RAM and 1.5 GB of storage. This
module measures what a node is actually using and decides whether it may
start another heavy stage. It only uses the standard library, so the edge
service on sys1 can import it without the geospatial stack.

Memory is read from the cgroup (v2, then v1) because that is the limit the
kernel enforces. The working set is ``memory.current - inactive_file``: the
same figure the OOM killer and Kubernetes use, so reclaimable page cache does
not count against the node.
"""

from __future__ import annotations

import ctypes
import gc
import os
import resource
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

MB = 1024 * 1024

DEFAULT_MEMORY_BUDGET_MB = 500
DEFAULT_STORAGE_BUDGET_MB = 1536
# Peak growth of one heavy stage above an idle, warm worker. Measured on the
# bundled 6.7 MB contour file: sys2 166 -> 241 MB, sys3 166 -> 361 MB.
DEFAULT_STAGE_RESERVE_MB = 150
STORAGE_SCAN_INTERVAL_S = 600.0

_CGROUP_V2 = Path("/sys/fs/cgroup")
_CGROUP_V1 = Path("/sys/fs/cgroup/memory")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return float(default)


def _read_int(path: Path) -> Optional[int]:
    try:
        raw = path.read_text().strip()
    except OSError:
        return None
    if raw in ("", "max"):
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _read_stat(path: Path, key: str) -> int:
    try:
        for line in path.read_text().splitlines():
            name, _, value = line.partition(" ")
            if name == key:
                return int(value)
    except (OSError, ValueError):
        pass
    return 0


def _process_rss_bytes() -> int:
    """Current RSS on Linux; peak RSS elsewhere (development machines)."""
    try:
        with open("/proc/self/statm") as handle:
            pages = int(handle.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS reports bytes, Linux reports kilobytes.
        return int(peak if sys.platform == "darwin" else peak * 1024)


def read_memory() -> Dict[str, Any]:
    """Return the node's working set and limit in bytes, plus their source."""
    current = _read_int(_CGROUP_V2 / "memory.current")
    if current is not None:
        inactive = _read_stat(_CGROUP_V2 / "memory.stat", "inactive_file")
        return {
            "source": "cgroup-v2",
            "working_set": max(0, current - inactive),
            "limit": _read_int(_CGROUP_V2 / "memory.max"),
        }
    current = _read_int(_CGROUP_V1 / "memory.usage_in_bytes")
    if current is not None:
        inactive = _read_stat(_CGROUP_V1 / "memory.stat", "total_inactive_file")
        limit = _read_int(_CGROUP_V1 / "memory.limit_in_bytes")
        # cgroup v1 reports "no limit" as a huge page-aligned number.
        if limit is not None and limit >= 1 << 60:
            limit = None
        return {"source": "cgroup-v1", "working_set": max(0, current - inactive), "limit": limit}
    return {"source": "process-rss", "working_set": _process_rss_bytes(), "limit": None}


def release_memory() -> None:
    """Hand freed heap pages back to the kernel after a heavy stage.

    NumPy and GeoPandas leave large freed arenas behind; without malloc_trim a
    warm worker's RSS ratchets up towards the cgroup limit over many requests.
    """
    gc.collect()
    if sys.platform.startswith("linux"):
        try:
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except (OSError, AttributeError):
            pass


def directory_size_bytes(root: Path) -> int:
    total = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir():
                            stack.append(Path(entry.path))
                        else:
                            total += entry.stat().st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


class StorageMonitor:
    """Measures the deployment directory in a background thread.

    Walking a 1 GB virtualenv takes a moment, so the result is cached and
    refreshed every ten minutes rather than on each health probe.
    """

    def __init__(self, root: Optional[Path] = None, budget_mb: Optional[float] = None):
        default_root = Path(__file__).resolve().parent.parent
        self.root = Path(os.getenv("JALASETU_DEPLOY_ROOT", root or default_root))
        self.budget_mb = budget_mb or _env_float("JALASETU_STORAGE_BUDGET_MB", DEFAULT_STORAGE_BUDGET_MB)
        self._used_bytes: Optional[int] = None
        self._measured_at = 0.0
        self._lock = threading.Lock()
        self._scanning = False

    def _scan(self) -> None:
        try:
            used = directory_size_bytes(self.root)
            with self._lock:
                self._used_bytes = used
                self._measured_at = time.time()
        finally:
            self._scanning = False

    def report(self) -> Dict[str, Any]:
        stale = time.time() - self._measured_at > STORAGE_SCAN_INTERVAL_S
        if stale and not self._scanning:
            self._scanning = True
            threading.Thread(target=self._scan, name="storage-scan", daemon=True).start()
        with self._lock:
            used = self._used_bytes
        used_mb = None if used is None else round(used / MB, 1)
        return {
            "root": self.root.name,
            "used_mb": used_mb,
            "budget_mb": self.budget_mb,
            "within_budget": None if used_mb is None else used_mb <= self.budget_mb,
        }


class CapacityGuard:
    """Admission control for heavy stages on one node.

    A stage is admitted only when a slot is free and the node's working set
    leaves at least ``stage_reserve_mb`` under the memory budget. Callers that
    are refused should send the work elsewhere instead of waiting here.
    """

    def __init__(
        self,
        slots: Optional[int] = None,
        memory_budget_mb: Optional[float] = None,
        stage_reserve_mb: Optional[float] = None,
    ):
        self.slots = max(1, int(slots or _env_float("JALASETU_WORKER_SLOTS", 1)))
        self.stage_reserve_mb = stage_reserve_mb or _env_float(
            "JALASETU_STAGE_RESERVE_MB", DEFAULT_STAGE_RESERVE_MB
        )
        self._configured_budget_mb = memory_budget_mb or _env_float(
            "JALASETU_MEMORY_BUDGET_MB", DEFAULT_MEMORY_BUDGET_MB
        )
        self._lock = threading.Lock()
        self._in_flight = 0
        self.completed = 0
        self.rejected = 0

    @property
    def in_flight(self) -> int:
        return self._in_flight

    def memory(self) -> Dict[str, Any]:
        sample = read_memory()
        budget_mb = self._configured_budget_mb
        if sample["limit"]:
            budget_mb = min(budget_mb, sample["limit"] / MB)
        used_mb = sample["working_set"] / MB
        return {
            "source": sample["source"],
            "used_mb": round(used_mb, 1),
            "budget_mb": round(budget_mb, 1),
            "headroom_mb": round(budget_mb - used_mb, 1),
        }

    def _admissible(self, memory: Dict[str, Any]) -> bool:
        return self._in_flight < self.slots and memory["headroom_mb"] >= self.stage_reserve_mb

    def try_acquire(self) -> bool:
        memory = self.memory()
        with self._lock:
            if not self._admissible(memory):
                self.rejected += 1
                return False
            self._in_flight += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            self.completed += 1
        release_memory()

    @contextmanager
    def slot(self) -> Iterator[bool]:
        """Yield True with a slot held, or False when the node is saturated."""
        acquired = self.try_acquire()
        try:
            yield acquired
        finally:
            if acquired:
                self.release()

    def report(self) -> Dict[str, Any]:
        memory = self.memory()
        return {
            "memory": memory,
            "slots": self.slots,
            "in_flight": self._in_flight,
            "stage_reserve_mb": self.stage_reserve_mb,
            "accepting": self._admissible(memory),
            "completed": self.completed,
            "rejected": self.rejected,
        }
