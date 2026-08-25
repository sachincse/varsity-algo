"""A tiny in-process job runner, so a long scan reports progress.

The first scan downloads a few hundred symbols and takes minutes. Doing that
inside a request means the browser sits on a spinner with no idea whether it is
working, stuck, or dead — which is the point at which a new user closes the tab
and decides the thing is broken.

So scans run on a worker thread and the browser polls for progress. This is
deliberately not Celery/Redis/a task queue: it is one user on one laptop, and a
job that dies with the process is the correct behaviour.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("varsity.jobs")

MAX_KEPT = 20          # finished jobs to retain for polling
STALE_AFTER = 3600     # seconds before a finished job is discarded


@dataclass
class Job:
    id: str
    kind: str
    state: str = "queued"            # queued | running | done | error
    message: str = ""
    current: int = 0
    total: int = 0
    result: Any = None
    error: str = ""
    started: float = field(default_factory=time.time)
    finished: float = 0.0

    def to_dict(self) -> dict:
        pct = round(self.current / self.total * 100) if self.total else None
        return {
            "id": self.id, "kind": self.kind, "state": self.state,
            "message": self.message, "current": self.current,
            "total": self.total, "percent": pct,
            "elapsed": round(time.time() - (self.finished or time.time())
                             + (self.finished - self.started if self.finished
                                else time.time() - self.started), 1),
            "error": self.error,
            "result": self.result if self.state == "done" else None,
        }


class JobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}

    def create(self, kind: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job
            self._evict()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _evict(self) -> None:
        now = time.time()
        finished = [j for j in self._jobs.values() if j.finished]
        for j in finished:
            if now - j.finished > STALE_AFTER:
                self._jobs.pop(j.id, None)
        finished = sorted((j for j in self._jobs.values() if j.finished),
                          key=lambda j: j.finished)
        while len(finished) > MAX_KEPT:
            self._jobs.pop(finished.pop(0).id, None)

    def run(self, job: Job, fn: Callable[[Job], Any]) -> Job:
        """Run ``fn(job)`` on a worker thread. ``fn`` updates job.current /
        job.total / job.message as it goes."""
        def target() -> None:
            job.state = "running"
            try:
                job.result = fn(job)
                job.state = "done"
                job.message = "complete"
            except Exception as e:
                job.state = "error"
                job.error = f"{type(e).__name__}: {e}"
                log.error("job %s (%s) failed: %s", job.id, job.kind, job.error)
                log.debug(traceback.format_exc())
            finally:
                job.finished = time.time()

        threading.Thread(target=target, daemon=True,
                         name=f"job-{job.kind}-{job.id}").start()
        return job


STORE = JobStore()
