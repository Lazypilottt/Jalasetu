"""Environment-driven configuration shared by distributed services."""

from dataclasses import dataclass, field
import os
from typing import Tuple


def _parse_workers(raw: str) -> Tuple[Tuple[str, str], ...]:
    """Parse ``name=url,name=url``; a bare URL is named after its position."""
    workers = []
    for index, item in enumerate(part.strip() for part in raw.split(",")):
        if not item:
            continue
        name, sep, url = item.partition("=")
        if not sep:
            name, url = f"worker{index + 1}", item
        workers.append((name.strip(), url.strip().rstrip("/")))
    return tuple(workers)


@dataclass(frozen=True)
class ServiceConfig:
    sys2_url: str = ""
    sys3_url: str = ""
    request_timeout_seconds: float = 120.0
    # Stage workers as (name, base_url). Empty means "run every stage locally".
    workers: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)
    # sys1 edge service: rainfall/climate API and cluster view.
    edge_url: str = ""
    node_name: str = "sys4"
    probe_timeout_seconds: float = 1.5
    # How long a stage may wait for any node to have capacity before the
    # request is answered with 503.
    queue_timeout_seconds: float = 90.0
    max_active_jobs: int = 2
    max_queued_jobs: int = 6
    # Uploads wait in gateway memory until a job starts; cap the total.
    max_queued_mb: float = 64.0

    @classmethod
    def from_env(cls) -> "ServiceConfig":
        sys2_url = os.getenv("JALASETU_SYS2_URL", "").rstrip("/")
        sys3_url = os.getenv("JALASETU_SYS3_URL", "").rstrip("/")
        workers = _parse_workers(os.getenv("JALASETU_WORKERS", ""))
        if not workers:
            workers = tuple((name, url) for name, url in (("sys2", sys2_url), ("sys3", sys3_url)) if url)
        return cls(
            sys2_url=sys2_url,
            sys3_url=sys3_url,
            request_timeout_seconds=float(os.getenv("JALASETU_REQUEST_TIMEOUT", "120")),
            workers=workers,
            edge_url=os.getenv("JALASETU_EDGE_URL", "").rstrip("/"),
            node_name=os.getenv("JALASETU_NODE_NAME", "sys4"),
            probe_timeout_seconds=float(os.getenv("JALASETU_PROBE_TIMEOUT", "1.5")),
            queue_timeout_seconds=float(os.getenv("JALASETU_QUEUE_TIMEOUT", "90")),
            max_active_jobs=int(os.getenv("JALASETU_MAX_ACTIVE_JOBS", "2")),
            max_queued_jobs=int(os.getenv("JALASETU_MAX_QUEUED_JOBS", "6")),
            max_queued_mb=float(os.getenv("JALASETU_MAX_QUEUED_MB", "64")),
        )
