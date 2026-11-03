"""Bounded in-memory job queue for the sys4 gateway.

Analyses take tens of seconds, so the frontend submits a job and polls it to
show which stage is running on which node. The queue is deliberately small:
uploads wait in gateway memory until a job starts, and the gateway itself has a
500 MB budget. A full queue answers 503 instead of accepting work it cannot hold.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

JOB_TTL_SECONDS = 900.0
KEEP_FINISHED = 24


class QueueFullError(RuntimeError):
    pass


@dataclass
class Job:
    id: str
    params: Dict[str, Any]
    has_upload: bool
    file_bytes: Optional[bytes]
    size_bytes: int
    state: str = "queued"  # queued | running | succeeded | failed
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    stage: Optional[str] = None
    node: Optional[str] = None
    waiting: bool = False
    stages: List[Dict[str, Any]] = field(default_factory=list)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_status: int = 422
    done: threading.Event = field(default_factory=threading.Event)

    def observe(self, event: Dict[str, Any]) -> None:
        kind = event.get("event")
        if kind == "stage_dispatched":
            self.stage, self.node, self.waiting = event["stage"], event["node"], False
        elif kind == "stage_waiting":
            self.stage, self.node, self.waiting = event["stage"], None, True
        elif kind == "stage_completed":
            self.stages.append({k: v for k, v in event.items() if k != "event"})


Runner = Callable[[Job], Dict[str, Any]]


class JobManager:
    def __init__(self, runner: Runner, max_active: int = 2, max_queued: int = 6, max_queued_mb: float = 64.0):
        self._runner = runner
        self._executor = ThreadPoolExecutor(max_workers=max(1, max_active), thread_name_prefix="analysis")
        self.max_active = max(1, max_active)
        self.max_queued = max(0, max_queued)
        self.max_queued_bytes = int(max_queued_mb * 1024 * 1024)
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def _prune(self) -> None:
        now = time.time()
        finished = sorted(
            (job for job in self._jobs.values() if job.finished_at is not None),
            key=lambda job: job.finished_at,
        )
        expired = {job.id for job in finished if now - job.finished_at > JOB_TTL_SECONDS}
        expired.update(job.id for job in finished[: max(0, len(finished) - KEEP_FINISHED)])
        for job_id in expired:
            self._jobs.pop(job_id, None)

    def _pending(self) -> List[Job]:
        return [job for job in self._jobs.values() if job.state in ("queued", "running")]

    def submit(self, file_bytes: Optional[bytes], params: Dict[str, Any], has_upload: bool) -> Job:
        size = len(file_bytes or b"")
        with self._lock:
            self._prune()
            pending = self._pending()
            queued = [job for job in pending if job.state == "queued"]
            running = len(pending) - len(queued)
            held = sum(job.size_bytes for job in pending)
            if running >= self.max_active and len(queued) >= self.max_queued:
                raise QueueFullError("The analysis queue is full. Please retry in a minute.")
            if held + size > self.max_queued_bytes and pending:
                raise QueueFullError("Too many large uploads are waiting. Please retry in a minute.")
            job = Job(
                id=secrets.token_urlsafe(9),
                params=params,
                has_upload=has_upload,
                file_bytes=file_bytes,
                size_bytes=size,
            )
            self._jobs[job.id] = job
        self._executor.submit(self._run, job)
        return job

    def _run(self, job: Job) -> None:
        job.state, job.started_at = "running", time.time()
        try:
            job.result = self._runner(job)
            job.state = "succeeded"
        except Exception as exc:  # the runner maps exceptions to messages
            job.error = str(exc) or exc.__class__.__name__
            job.error_status = getattr(exc, "http_status", 422)
            job.state = "failed"
        finally:
            job.file_bytes = None
            job.finished_at = time.time()
            job.stage, job.node, job.waiting = None, None, False
            job.done.set()

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            self._prune()
            return self._jobs.get(job_id)

    def queue_position(self, job: Job) -> int:
        with self._lock:
            queued = sorted(
                (j for j in self._jobs.values() if j.state == "queued"),
                key=lambda j: j.created_at,
            )
        return next((i + 1 for i, j in enumerate(queued) if j.id == job.id), 0)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            pending = self._pending()
        return {
            "running": sum(job.state == "running" for job in pending),
            "queued": sum(job.state == "queued" for job in pending),
            "max_active": self.max_active,
            "max_queued": self.max_queued,
        }

    def to_public(self, job: Job, include_result: bool = True) -> Dict[str, Any]:
        body = {
            "job_id": job.id,
            "state": job.state,
            "stage": job.stage,
            "node": job.node,
            "waiting_for_capacity": job.waiting,
            "queue_position": self.queue_position(job) if job.state == "queued" else 0,
            "stages": job.stages,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
        }
        if job.state == "failed":
            body["error"] = job.error
        if include_result and job.state == "succeeded":
            body["result"] = job.result
        return body
