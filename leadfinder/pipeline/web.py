"""Tracker UI + JSON API, mounted on the main app at /pipeline."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from . import config, db
from . import coverage as cov
from . import importer, publish

router = APIRouter()
UI = Path(__file__).resolve().parent / "ui" / "tracker.html"
PLAYBOOK = UI.with_name("playbook.html")

LIST_COLUMNS = ("slug, name, category, kind, theme, suburb, state, region, phone, phone_display, mobile, "
                "rating, reviews, score, grade, stage, attempts, last_contact, follow_up, updated_at")
SORTS = {"score": "score DESC, reviews DESC", "recent": "updated_at DESC", "name": "name",
         "follow_up": "follow_up IS NULL, follow_up, score DESC", "reviews": "reviews DESC"}


class StageBody(BaseModel):
    stage: str
    note: str = Field("", max_length=500)


class CallBody(BaseModel):
    outcome: str
    note: str = Field("", max_length=1000)
    follow_up: Optional[str] = Field(None, max_length=10)


class PublishBody(BaseModel):
    grades: List[str] = Field(default_factory=lambda: ["Hot"])
    limit: Optional[int] = Field(100, ge=0, le=20000)
    regions: List[str] = Field(default_factory=list)
    min_score: int = Field(0, ge=0, le=100)


@router.get("/pipeline", include_in_schema=False)
def tracker_page():
    return FileResponse(UI, headers={"Cache-Control": "no-store"})


@router.get("/pipeline/playbook", include_in_schema=False)
def playbook_page():
    return HTMLResponse(PLAYBOOK.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/pipeline/api/meta")
def meta() -> Dict[str, Any]:
    with db.connect() as con:
        regions = [r[0] for r in con.execute("SELECT DISTINCT region FROM leads WHERE region != '' ORDER BY region")]
        themes = [r[0] for r in con.execute("SELECT DISTINCT theme FROM leads ORDER BY theme")]
        grades = {r["grade"]: r["n"] for r in con.execute("SELECT grade, COUNT(*) n FROM leads GROUP BY grade")}
        due = con.execute("SELECT COUNT(*) FROM leads WHERE follow_up IS NOT NULL AND follow_up <= date('now', '+11 hours') "
                          "AND stage NOT IN ('not_interested','do_not_contact','live')").fetchone()[0]
        counts = db.stage_counts(con)
    return {"stages": [{"key": k, "label": l, "count": counts[k]} for k, l in db.STAGES],
            "outcomes": db.CALL_OUTCOMES, "regions": regions, "themes": themes, "grades": grades,
            "follow_ups_due": due, "preview_base": config.SITE_URL + config.PREVIEW_PATH}


def _where(stage, grade, region, theme, q, mobile, due, queue):
    sql, args = [], []
    if queue:
        # Rapid-fire call list: preview is live, not closed, fewer than 4 tries,
        # and not waiting on a call-back that isn't due yet.
        sql.append("stage IN ('preview_hosted','contacted','follow_up') AND attempts < 4 "
                   "AND (follow_up IS NULL OR follow_up <= date('now', '+11 hours'))")
    if stage:
        keys = [s for s in stage.split(",") if s in db.STAGE_LABELS]
        if keys:
            sql.append(f"stage IN ({','.join('?' * len(keys))})")
            args += keys
    if grade:
        g = grade.split(",")
        sql.append(f"grade IN ({','.join('?' * len(g))})")
        args += g
    if region:
        sql.append("region = ?")
        args.append(region)
    if theme:
        sql.append("theme = ?")
        args.append(theme)
    if mobile:
        sql.append("mobile = 1")
    if due:
        sql.append("follow_up IS NOT NULL AND follow_up <= date('now', '+11 hours') "
                   "AND stage NOT IN ('not_interested','do_not_contact','live')")
    if q:
        like = f"%{q.strip()}%"
        sql.append("(name LIKE ? OR suburb LIKE ? OR phone LIKE ? OR phone_display LIKE ? OR category LIKE ? OR slug LIKE ?)")
        args += [like] * 6
    return (" WHERE " + " AND ".join(sql)) if sql else "", args


@router.get("/pipeline/api/leads")
def leads(stage: str = "", grade: str = "", region: str = "", theme: str = "", q: str = "",
          mobile: bool = False, due: bool = False, queue: bool = False,
          sort: str = "score", limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    where, args = _where(stage, grade, region, theme, q, mobile, due, queue)
    order = SORTS.get(sort, SORTS["score"])
    with db.connect() as con:
        total = con.execute(f"SELECT COUNT(*) FROM leads{where}", args).fetchone()[0]
        rows = con.execute(f"SELECT {LIST_COLUMNS} FROM leads{where} ORDER BY {order} LIMIT ? OFFSET ?",
                           args + [limit, offset]).fetchall()
    return {"total": total, "leads": [dict(r) for r in rows]}


@router.get("/pipeline/api/leads.csv")
def leads_csv(stage: str = "", grade: str = "", region: str = "", theme: str = "", q: str = "",
              mobile: bool = False, due: bool = False, queue: bool = False, sort: str = "score"):
    where, args = _where(stage, grade, region, theme, q, mobile, due, queue)
    with db.connect() as con:
        rows = con.execute(f"SELECT * FROM leads{where} ORDER BY {SORTS.get(sort, SORTS['score'])}", args).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = ["name", "phone_display", "mobile", "category", "suburb", "state", "region", "address", "rating",
            "reviews", "score", "grade", "stage", "attempts", "last_contact", "follow_up", "contact_name",
            "email", "price_quoted", "price_agreed", "domain", "notes", "slug"]
    w.writerow(cols + ["preview_url"])
    for r in rows:
        w.writerow([r[c] if c != "stage" else db.STAGE_LABELS[r[c]] for c in cols] + [config.preview_url(r["slug"])])
    return Response("﻿" + buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="pipeline.csv"'})


def _lead_or_404(con, slug: str) -> Dict[str, Any]:
    lead = db.get(con, slug)
    if not lead:
        raise HTTPException(404, "No such lead")
    return lead


@router.get("/pipeline/api/leads/{slug}")
def lead_detail(slug: str):
    with db.connect() as con:
        lead = _lead_or_404(con, slug)
        lead["history"] = db.history(con, slug)
    lead["preview_url"] = config.preview_url(slug)
    lead["stage_label"] = db.STAGE_LABELS[lead["stage"]]
    return lead


@router.post("/pipeline/api/leads/{slug}/stage")
def change_stage(slug: str, body: StageBody):
    if body.stage not in db.STAGE_LABELS:
        raise HTTPException(400, "Unknown stage")
    with db.connect() as con:
        _lead_or_404(con, slug)
        db.set_stage(con, slug, body.stage, body.note)
    return lead_detail(slug)


@router.post("/pipeline/api/leads/{slug}/call")
def log_call(slug: str, body: CallBody):
    if body.outcome not in db.CALL_OUTCOMES:
        raise HTTPException(400, "Unknown outcome")
    with db.connect() as con:
        _lead_or_404(con, slug)
        ts = db.now()
        con.execute("UPDATE leads SET attempts = attempts + 1, last_contact = ?, updated_at = ? WHERE slug = ?",
                    (ts, ts, slug))
        detail = db.CALL_OUTCOMES[body.outcome] + (f" — {body.note}" if body.note else "")
        db.log(con, slug, "call", detail)
        if body.follow_up:
            con.execute("UPDATE leads SET follow_up = ? WHERE slug = ?", (body.follow_up, slug))
            db.advance(con, slug, "follow_up", f"call back {body.follow_up}")
        elif body.outcome in ("gatekeeper", "owner", "sms", "email", "voicemail", "no_answer"):
            db.advance(con, slug, "contacted")
        if body.outcome == "wrong_number":
            db.set_stage(con, slug, "do_not_contact", "wrong number")
    return lead_detail(slug)


@router.patch("/pipeline/api/leads/{slug}")
def edit_lead(slug: str, body: Dict[str, Any]):
    fields = {k: v for k, v in body.items() if k in db.EDITABLE}
    if not fields:
        raise HTTPException(400, f"Editable fields: {', '.join(sorted(db.EDITABLE))}")
    for k in ("price_quoted", "price_agreed"):
        if k in fields:
            try:
                fields[k] = int(str(fields[k]).replace("$", "").replace(",", "").strip()) if fields[k] not in (None, "") else None
            except ValueError:
                raise HTTPException(400, f"{k} must be a number")
    with db.connect() as con:
        before = _lead_or_404(con, slug)
        sets = ", ".join(f"{k} = ?" for k in fields)
        con.execute(f"UPDATE leads SET {sets}, updated_at = ? WHERE slug = ?", list(fields.values()) + [db.now(), slug])
        changed = [k for k, v in fields.items() if (before.get(k) or None) != (v or None)]
        if changed and changed != ["notes"]:
            db.log(con, slug, "edit", ", ".join(f"{k}: {fields[k]}" for k in changed if k != "notes"))
    return lead_detail(slug)


@router.get("/pipeline/api/coverage")
def coverage():
    return cov.coverage()


@router.post("/pipeline/api/import")
def run_import():
    return importer.run()


@router.post("/pipeline/api/publish")
def run_publish(body: PublishBody):
    lines: List[str] = []
    try:
        res = publish.publish(grades=body.grades, limit=body.limit, regions=body.regions,
                              min_score=body.min_score, log=lines.append)
    except publish.PublishError as exc:
        raise HTTPException(409, str(exc))
    return {**res, "log": lines}


@router.post("/pipeline/api/verify")
def run_verify():
    lines: List[str] = []
    res = publish.verify(log=lines.append)
    return {**res, "log": lines}


@router.post("/pipeline/api/leads/{slug}/export")
def run_export(slug: str):
    try:
        out = publish.export_site(slug, log=lambda _m: None)
    except publish.PublishError as exc:
        raise HTTPException(404, str(exc))
    return {"folder": str(out)}
