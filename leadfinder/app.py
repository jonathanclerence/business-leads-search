"""Google Maps Lead Finder — FastAPI backend.

Run it:
    python app.py
Then open http://localhost:5000
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from leadfinder import __version__
from leadfinder.batch import (
    BatchConfig,
    BatchRunner,
    estimate_seconds,
    load_input_list,
    load_pairs,
)
from leadfinder.config import settings
from leadfinder.exporters import (
    SheetsError,
    export_to_google_sheet,
    suggest_filename,
    to_csv_bytes,
)
from leadfinder.jobs import Job, manager
from leadfinder.models import Business, SearchRequest
from leadfinder.places_api import PlacesAPIError, search_places
from leadfinder.scraper import GoogleMapsScraper
from leadfinder.store import SALES_HEADERS, BatchStore, list_batches

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("leadfinder")

BASE_DIR = Path(__file__).resolve().parent
BATCH_ROOT = BASE_DIR / "batches"
DATA_DIR = BASE_DIR / "data"
BATCH_ROOT.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Google Maps Lead Finder", version=__version__)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class SearchBody(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    location: str = Field("", max_length=200)
    max_results: int = Field(20, ge=1, le=500)
    provider: str = Field("playwright", pattern="^(playwright|places_api)$")


class ExportBody(BaseModel):
    # `Optional[...]` rather than `X | None` so this parses on Python 3.9,
    # where Pydantic can't evaluate PEP 604 unions without eval-type-backport.
    rows: List[dict] = Field(default_factory=list)
    job_id: Optional[str] = None
    filename: Optional[str] = None


class SheetsBody(ExportBody):
    share_with: Optional[str] = None
    spreadsheet_url: Optional[str] = None
    title: Optional[str] = None


class BatchBody(BaseModel):
    name: str = Field("batch", max_length=80)
    towns_file: Optional[str] = None
    types_file: Optional[str] = None
    pairs_file: Optional[str] = None
    towns: List[str] = Field(default_factory=list)
    business_types: List[str] = Field(default_factory=list)
    max_towns: Optional[int] = Field(None, ge=1, le=2000)
    max_types: Optional[int] = Field(None, ge=1, le=500)
    max_results: int = Field(20, ge=1, le=200)
    provider: str = Field("playwright", pattern="^(playwright|places_api)$")
    order: str = Field("type", pattern="^(type|town)$")
    pace_seconds: float = Field(8.0, ge=0.0, le=120.0)
    long_break_every: int = Field(40, ge=0, le=1000)
    long_break_seconds: float = Field(180.0, ge=0.0, le=3600.0)


class LeadFilterBody(BaseModel):
    no_website_only: bool = False
    min_score: int = Field(0, ge=0, le=100)
    grades: List[str] = Field(default_factory=list)
    towns: List[str] = Field(default_factory=list)
    business_types: List[str] = Field(default_factory=list)
    require_phone: bool = False
    filename: Optional[str] = None


# ---------------------------------------------------------------------------
# Job execution
# ---------------------------------------------------------------------------
async def _run_job(job: Job) -> None:
    req = job.request

    async def on_progress(event: str, data: dict) -> None:
        if "found" in data:
            job.found = data["found"]
        if "processed" in data:
            job.processed = data["processed"]
        if "target" in data and data["target"]:
            job.target = data["target"]
        if data.get("message"):
            job.message = data["message"]
        await manager.publish(
            job,
            event,
            {
                "message": job.message,
                "found": job.found,
                "processed": job.processed,
                "target": job.target,
                "item": data.get("item"),
            },
        )

    try:
        job.status = "running"
        job.message = "Starting…"
        await manager.publish(job, "status", {"message": job.message, "status": "running"})

        if req.provider == "places_api":
            results = await search_places(req.full_query, req.max_results, on_progress)
        else:
            async with GoogleMapsScraper(on_progress=on_progress) as scraper:
                results = await scraper.search(req.full_query, req.max_results)

        job.results = results
        job.found = len(results)
        job.status = "done"
        job.message = f"Done — {len(results)} businesses found."
        await manager.publish(
            job,
            "done",
            {
                "message": job.message,
                "count": len(results),
                "found": job.found,
                "items": [b.to_dict() for b in results],
            },
        )
        log.info("job %s finished: %d results", job.id, len(results))

    except asyncio.CancelledError:
        job.status = "cancelled"
        job.message = "Search cancelled."
        await manager.publish(job, "cancelled", {"message": job.message})
        raise
    except (PlacesAPIError, SheetsError) as exc:
        job.status, job.error = "error", str(exc)
        await manager.publish(job, "error", {"message": str(exc), "error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.exception("job %s failed", job.id)
        job.status = "error"
        job.error = f"{type(exc).__name__}: {exc}"
        await manager.publish(job, "error", {"message": job.error, "error": job.error})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "version": __version__,
            "places_api_available": settings.places_api_available,
            "sheets_available": settings.sheets_available,
            "sales_headers": SALES_HEADERS,
        },
    )


@app.get("/api/config")
async def config():
    return {
        "version": __version__,
        "places_api_available": settings.places_api_available,
        "sheets_available": settings.sheets_available,
        "headless": settings.HEADLESS,
        "concurrency": settings.CONCURRENCY,
    }


@app.post("/api/search")
async def start_search(body: SearchBody):
    if body.provider == "places_api" and not settings.places_api_available:
        raise HTTPException(
            400,
            "Places API selected but GOOGLE_MAPS_API_KEY is not set in .env. "
            "Switch to the Playwright scraper or add a key.",
        )

    req = SearchRequest(
        query=body.query.strip(),
        location=body.location.strip(),
        max_results=body.max_results,
        provider=body.provider,
    )
    job = manager.create(req)
    job._task = asyncio.create_task(_run_job(job))
    log.info("job %s started: %r (%s, max=%d)", job.id, req.full_query, req.provider, req.max_results)
    return {"job_id": job.id, **job.snapshot()}


@app.get("/api/stream/{job_id}")
async def stream(job_id: str):
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job id")
    return StreamingResponse(
        manager.stream(job),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/results/{job_id}")
async def results(job_id: str):
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job id")
    return {**job.snapshot(), "items": [b.to_dict() for b in job.results]}


@app.post("/api/cancel/{job_id}")
async def cancel(job_id: str):
    return {"cancelled": manager.cancel(job_id)}


def _rows_from(body: ExportBody) -> list[dict]:
    """Prefer the rows the browser sent (they reflect the user's current
    filter + sort). Fall back to the job's full result set."""
    if body.rows:
        return body.rows
    if body.job_id:
        job = manager.get(body.job_id)
        if job:
            return [b.to_dict() for b in job.results]
    return []


@app.post("/api/export/csv")
async def export_csv(body: ExportBody):
    rows = _rows_from(body)
    if not rows:
        raise HTTPException(400, "Nothing to export.")
    filename = body.filename or suggest_filename("leads", "")
    if not filename.endswith(".csv"):
        filename += ".csv"
    return Response(
        content=to_csv_bytes(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/export/sheets")
async def export_sheets(body: SheetsBody):
    rows = _rows_from(body)
    if not rows:
        raise HTTPException(400, "Nothing to export.")
    if not settings.sheets_available and not body.spreadsheet_url:
        raise HTTPException(
            400,
            "Google Sheets export isn't configured. Add GOOGLE_SERVICE_ACCOUNT_FILE "
            "to .env (see README → Google Sheets export).",
        )
    try:
        info = await asyncio.to_thread(
            export_to_google_sheet,
            rows,
            body.title or "Google Maps Leads",
            body.share_with,
            body.spreadsheet_url,
        )
    except SheetsError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc
    return JSONResponse(info)


@app.get("/api/health")
async def health():
    return {"ok": True, "version": __version__}


# ===========================================================================
# Bulk batch: CSV in → deduplicated, scored leads out
# ===========================================================================
class BatchJob:
    """A running batch, plus the SSE queue the dashboard subscribes to.

    Progress lives in memory only; the *data* is already durable on disk in
    the batch folder, so losing this object costs nothing but the live view.
    """

    def __init__(self, store: BatchStore, config: BatchConfig) -> None:
        self.store = store
        self.config = config
        self.batch_id = store.manifest.get("batch_id", store.dir.name)
        self.runner: Optional[BatchRunner] = None
        self.task: Optional[asyncio.Task] = None
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=4000)
        self.last: Dict[str, Any] = {"event": "queued", "message": "Queued…"}

    async def publish(self, event: str, data: Dict[str, Any]) -> None:
        payload = {"event": event, "batch_id": self.batch_id, **data}
        self.last = payload
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass  # a slow browser tab must never stall the scraper

    async def stream(self):
        yield f"data: {json.dumps(self.last, default=str)}\n\n"
        while True:
            try:
                payload = await asyncio.wait_for(self.queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                if self.task and self.task.done():
                    break
                continue
            yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
            if payload.get("event") == "finished":
                break


batch_jobs: Dict[str, BatchJob] = {}


def _resolve_batch_dir(batch_id: str) -> Path:
    if batch_id in ("latest", "last"):
        found = list_batches(BATCH_ROOT)
        if not found:
            raise HTTPException(404, "No batches yet.")
        return Path(found[0]["dir"])
    d = BATCH_ROOT / batch_id
    if not (d / "manifest.json").exists():
        raise HTTPException(404, f"Unknown batch {batch_id!r}")
    return d


def _safe_data_file(name: str) -> Path:
    """Only ever read CSVs from data/ — never an arbitrary path from the browser."""
    p = (DATA_DIR / Path(name).name).resolve()
    if not str(p).startswith(str(DATA_DIR.resolve())) or not p.exists():
        raise HTTPException(400, f"No such input file: {name}")
    return p


def _config_from_body(body: BatchBody) -> BatchConfig:
    pairs: List[Dict[str, str]] = []
    towns: List[str] = list(body.towns)
    types: List[str] = list(body.business_types)

    if body.pairs_file:
        pairs = load_pairs(_safe_data_file(body.pairs_file))
        if not pairs:
            raise HTTPException(400, f"No usable rows in {body.pairs_file}")
    else:
        if body.towns_file:
            towns = load_input_list(_safe_data_file(body.towns_file), "town")
        if body.types_file:
            types = load_input_list(_safe_data_file(body.types_file), "type")
        if body.max_towns:
            towns = towns[: body.max_towns]
        if body.max_types:
            types = types[: body.max_types]
        if not towns or not types:
            raise HTTPException(400, "Need at least one town and one business type.")

    return BatchConfig(
        name=body.name or "batch",
        towns=towns,
        business_types=types,
        pairs=pairs,
        max_results=body.max_results,
        provider=body.provider,
        order=body.order,
        pace_seconds=body.pace_seconds,
        long_break_every=body.long_break_every,
        long_break_seconds=body.long_break_seconds,
    )


@app.get("/api/batch/inputs")
async def batch_inputs():
    """List the CSVs in data/, with a peek at what each one can be used for.

    Each probe is independent: a file that can't be read as pairs must still
    report its town/type counts, or it silently vanishes from the dropdowns.
    """
    def probe(fn):
        try:
            return fn()
        except Exception:
            return []

    out = []
    for p in sorted(DATA_DIR.glob("*.csv")):
        header = ""
        try:
            with p.open("r", encoding="utf-8-sig") as fh:
                header = (fh.readline() or "").lower()
        except Exception:
            pass
        looks_like_pairs = "business_type" in header and any(
            t in header for t in ("town", "suburb", "location", "city")
        )
        towns = probe(lambda: load_input_list(p, "town"))
        types = probe(lambda: load_input_list(p, "type"))
        pairs = probe(lambda: load_pairs(p)) if looks_like_pairs else []
        out.append({
            "file": p.name,
            "size": p.stat().st_size,
            "town_count": len(towns),
            "type_count": len(types),
            "pair_count": len(pairs),
            "sample": (towns or types)[:5],
        })
    return {"files": out}


@app.post("/api/batch/upload")
async def batch_upload(file: UploadFile = File(...)):
    name = Path(file.filename or "upload.csv").name
    if not name.lower().endswith(".csv"):
        raise HTTPException(400, "Only .csv files, please.")
    dest = DATA_DIR / name
    dest.write_bytes(await file.read())
    return {"file": name, "size": dest.stat().st_size}


@app.post("/api/batch/preview")
async def batch_preview(body: BatchBody):
    """What this batch will cost, before committing hours to it."""
    cfg = _config_from_body(body)
    tasks = cfg.tasks()
    eta = estimate_seconds(len(tasks), cfg)
    return {
        "searches": len(tasks),
        "towns": len(cfg.towns),
        "business_types": len(cfg.business_types),
        "pairs": len(cfg.pairs),
        "max_listings": len(tasks) * cfg.max_results,
        "eta_seconds": round(eta),
        "sample": [f"{t['business_type']} in {t['town']}" for t in tasks[:8]],
        "warning": (
            "Over 6 hours on one IP — Google will very likely throttle you. Trim the "
            "lists, add SCRAPER_PROXY to .env, or split it across nights (resume "
            "picks up exactly where it stopped)."
            if eta > 6 * 3600 else ""
        ),
    }


async def _drive_batch(job: BatchJob, resume: bool) -> None:
    async def on_progress(event: str, data: Dict[str, Any]) -> None:
        await job.publish(event, data)

    job.runner = BatchRunner(job.store, job.config, on_progress=on_progress)
    try:
        with job.store:
            await job.runner.run(resume=resume)
    except asyncio.CancelledError:
        job.store.save_manifest(status="paused")
        await job.publish("finished", {"status": "paused", "message": "Batch paused."})
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("batch %s failed", job.batch_id)
        job.store.save_manifest(status="error")
        await job.publish("finished", {"status": "error",
                                       "message": f"{type(exc).__name__}: {exc}"})


@app.post("/api/batch/start")
async def batch_start(body: BatchBody):
    for j in batch_jobs.values():
        if j.task and not j.task.done():
            raise HTTPException(
                409,
                f"Batch {j.batch_id} is still running. Only one batch at a time — "
                f"they'd compete for the same browser and get you rate-limited faster.",
            )
    cfg = _config_from_body(body)
    store = BatchStore.create(BATCH_ROOT, cfg.name, cfg.to_dict())
    job = BatchJob(store, cfg)
    batch_jobs[job.batch_id] = job
    job.task = asyncio.create_task(_drive_batch(job, resume=False))
    log.info("batch %s started: %d searches", job.batch_id, len(cfg.tasks()))
    return {"batch_id": job.batch_id, "searches": len(cfg.tasks()), "dir": str(store.dir)}


@app.post("/api/batch/{batch_id}/resume")
async def batch_resume(batch_id: str):
    for j in batch_jobs.values():
        if j.task and not j.task.done():
            raise HTTPException(409, f"Batch {j.batch_id} is still running.")
    batch_dir = _resolve_batch_dir(batch_id)
    store = BatchStore.open(batch_dir)
    cfg = BatchConfig.from_dict(store.manifest.get("config", {}))
    job = BatchJob(store, cfg)
    batch_jobs[job.batch_id] = job
    job.task = asyncio.create_task(_drive_batch(job, resume=True))
    log.info("batch %s resumed", job.batch_id)
    return {"batch_id": job.batch_id, "resumed": True}


@app.post("/api/batch/{batch_id}/cancel")
async def batch_cancel(batch_id: str):
    job = batch_jobs.get(batch_id)
    if not job or not job.runner:
        return {"cancelled": False}
    # Cooperative: finish the search in flight, then checkpoint and stop.
    job.runner.cancel()
    return {"cancelled": True}


@app.get("/api/batch/stream/{batch_id}")
async def batch_stream(batch_id: str):
    job = batch_jobs.get(batch_id)
    if not job:
        raise HTTPException(404, "That batch isn't running in this process. "
                                 "Its data is still on disk — reload the batch list.")
    return StreamingResponse(
        job.stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                 "X-Accel-Buffering": "no"},
    )


@app.get("/api/batch/list")
async def batch_list():
    items = list_batches(BATCH_ROOT)
    for b in items:
        job = batch_jobs.get(b["batch_id"])
        b["live"] = bool(job and job.task and not job.task.done())
    return {"batches": items}


@app.get("/api/batch/{batch_id}")
async def batch_detail(batch_id: str):
    store = BatchStore.open(_resolve_batch_dir(batch_id))
    job = batch_jobs.get(store.manifest.get("batch_id", ""))
    return {
        **store.summary(),
        "live": bool(job and job.task and not job.task.done()),
        "config": store.manifest.get("config", {}),
        "recent_tasks": sorted(
            store.done_tasks.values(), key=lambda t: t.get("at", ""), reverse=True
        )[:25],
    }


@app.post("/api/batch/{batch_id}/leads")
async def batch_leads(batch_id: str, body: LeadFilterBody, limit: int = 500):
    store = BatchStore.open(_resolve_batch_dir(batch_id))
    rows = store.filtered(
        no_website_only=body.no_website_only,
        min_score=body.min_score,
        grades=body.grades or None,
        towns=body.towns or None,
        business_types=body.business_types or None,
        require_phone=body.require_phone,
    )
    towns = sorted({l.get("search_town", "") for l in store.leads if l.get("search_town")})
    types = sorted({l.get("search_business_type", "") for l in store.leads
                    if l.get("search_business_type")})
    return {
        "total": len(rows),
        "shown": min(len(rows), limit),
        "items": rows[:limit],
        "facets": {"towns": towns, "business_types": types},
    }


@app.post("/api/batch/{batch_id}/export")
async def batch_export(batch_id: str, body: LeadFilterBody):
    store = BatchStore.open(_resolve_batch_dir(batch_id))
    text = store.export_csv_string(
        no_website_only=body.no_website_only,
        min_score=body.min_score,
        grades=body.grades or None,
        towns=body.towns or None,
        business_types=body.business_types or None,
        require_phone=body.require_phone,
    )
    if text.count("\r\n") <= 1:
        raise HTTPException(400, "No leads match those filters.")
    filename = body.filename or f"{store.manifest.get('batch_id', 'leads')}.csv"
    if not filename.endswith(".csv"):
        filename += ".csv"
    return Response(
        content=text.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if __name__ == "__main__":
    print(f"\n  Google Maps Lead Finder v{__version__}")
    print(f"  → http://localhost:{settings.PORT}\n")
    uvicorn.run(
        "app:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        log_level="info",
    )
