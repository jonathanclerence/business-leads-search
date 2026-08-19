"""Google Maps Lead Finder — FastAPI backend.

Run it:
    python app.py
Then open http://localhost:5000
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from leadfinder import __version__
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("leadfinder")

BASE_DIR = Path(__file__).resolve().parent

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
    rows: list[dict] = Field(default_factory=list)
    job_id: str | None = None
    filename: str | None = None


class SheetsBody(ExportBody):
    share_with: str | None = None
    spreadsheet_url: str | None = None
    title: str | None = None


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
