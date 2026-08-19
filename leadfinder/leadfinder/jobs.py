"""Tiny in-process job runner with Server-Sent-Events progress.

A scrape takes 30s–3min, which is far too long for a synchronous HTTP request:
the browser would time out and the user would stare at a spinner with no idea
whether anything is happening. So a search POST returns a job id immediately
and the frontend subscribes to `/api/stream/{job_id}` for live progress.

State lives in memory — perfect for a single-user local tool, and the reason
this app needs no database. Restarting the server clears history.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from .models import Business, SearchRequest


@dataclass
class Job:
    id: str
    request: SearchRequest
    status: str = "queued"  # queued|running|done|error|cancelled
    message: str = ""
    error: str = ""
    found: int = 0
    processed: int = 0
    target: int = 0
    results: list[Business] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    _queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=2000))
    _task: asyncio.Task | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "status": self.status,
            "message": self.message,
            "error": self.error,
            "found": self.found,
            "processed": self.processed,
            "target": self.target,
            "count": len(self.results),
            "query": self.request.query,
            "location": self.request.location,
            "provider": self.request.provider,
            "created_at": self.created_at,
        }


class JobManager:
    def __init__(self, max_jobs: int = 50) -> None:
        self._jobs: dict[str, Job] = {}
        self._max_jobs = max_jobs

    def create(self, req: SearchRequest) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], request=req, target=req.max_results)
        self._jobs[job.id] = job
        # Keep memory bounded: evict oldest finished jobs.
        if len(self._jobs) > self._max_jobs:
            for jid, j in sorted(self._jobs.items(), key=lambda kv: kv[1].created_at):
                if j.status in {"done", "error", "cancelled"}:
                    self._jobs.pop(jid, None)
                if len(self._jobs) <= self._max_jobs:
                    break
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    async def publish(self, job: Job, event: str, data: dict[str, Any]) -> None:
        payload = {"event": event, **data}
        try:
            job._queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass  # A slow client must not stall the scraper.

    async def stream(self, job: Job) -> AsyncIterator[str]:
        """SSE generator. Replays current state first so a late subscriber
        (or a page refresh) never sees an empty screen."""
        yield _sse({"event": "snapshot", **job.snapshot()})

        # Replay whatever has already been collected.
        if job.results:
            yield _sse(
                {"event": "bulk", "items": [b.to_dict() for b in job.results]}
            )

        while True:
            try:
                payload = await asyncio.wait_for(job._queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"  # stops proxies from closing the pipe
                if job.status in {"done", "error", "cancelled"}:
                    break
                continue

            yield _sse(payload)
            if payload.get("event") in {"done", "error", "cancelled"}:
                break

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or not job._task or job._task.done():
            return False
        job._task.cancel()
        return True


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


manager = JobManager()
