"""Tracker UI + JSON API, mounted on the main app at /pipeline."""

from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from . import auth, config, db
from . import coverage as cov
from . import dncr, documents, importer, offer, payments, publish
from .sri_lanka import router as sri_lanka_router

router = APIRouter()
router.include_router(sri_lanka_router)
UI = Path(__file__).resolve().parent / "ui" / "tracker.html"
TEXTS_UI = UI.with_name("texts.html")
PLAYBOOK = UI.with_name("playbook.html")

LIST_COLUMNS = ("slug, name, category, kind, theme, suburb, state, region, phone, phone_display, mobile, "
                "rating, reviews, score, grade, stage, attempts, last_contact, follow_up, updated_at, owner, working_since")
# Rapid-fire call list: preview is live, not closed, fewer than 4 tries,
# not waiting on a call-back that isn't due yet, not on the Do Not Call Register.
# It's also what a rep may take when nobody owns the lead yet.
QUEUE_SQL = ("stage IN ('preview_hosted','contacted','follow_up') AND attempts < 4 "
             "AND (follow_up IS NULL OR follow_up <= date('now', '+11 hours')) AND (dncr IS NULL OR dncr != 'Y')")
ADMIN = [Depends(auth.admin_only)]
SORTS = {"score": "score DESC, reviews DESC", "recent": "updated_at DESC", "name": "name",
         "follow_up": "follow_up IS NULL, follow_up, score DESC", "reviews": "reviews DESC"}


class StageBody(BaseModel):
    stage: str
    note: str = Field("", max_length=500)


class CallBody(BaseModel):
    outcome: str
    note: str = Field("", max_length=1000)
    follow_up: Optional[str] = Field(None, max_length=10)


class SentBody(BaseModel):
    via: str = Field(..., pattern="^(email|sms|request)$")   # request: a rep asking sales@ to email it
    to: str = Field("", max_length=200)


class HandoverBody(BaseModel):
    email: str = Field(..., max_length=200)
    contact_name: str = Field("", max_length=100)
    package: str = Field("", max_length=60)
    note: str = Field("", max_length=1000)


class TextBody(BaseModel):
    body: str = Field(..., min_length=10, max_length=600)
    consent: bool = False


class OwnerBody(BaseModel):
    owner: Optional[str] = Field(None, max_length=32)


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


DUE_SQL = ("follow_up IS NOT NULL AND follow_up <= date('now', '+11 hours') "
           "AND stage NOT IN ('not_interested','do_not_contact','live')")
MINE_SQL = f"owner = ? AND stage NOT IN {db.CLOSED_STAGES}"


@router.get("/pipeline/api/meta")
def meta(request: Request) -> Dict[str, Any]:
    u = auth.user(request)
    rep = auth.is_rep(u)
    with db.connect() as con:
        regions = [r[0] for r in con.execute("SELECT DISTINCT region FROM leads WHERE region != '' ORDER BY region")]
        themes = [r[0] for r in con.execute("SELECT DISTINCT theme FROM leads ORDER BY theme")]
        grades = {r["grade"]: r["n"] for r in con.execute("SELECT grade, COUNT(*) n FROM leads GROUP BY grade")}
        mine = (" AND owner = ?", [u["username"]]) if rep else ("", [])
        due = con.execute(f"SELECT COUNT(*) FROM leads WHERE {DUE_SQL}{mine[0]}", mine[1]).fetchone()[0]
        counts = db.stage_counts(con)
        dncr_due = 0 if rep else len(dncr.due(con, "calling"))
        current = db.working(con, u["username"]) if u["username"] else None
        pool = {"available": con.execute(f"SELECT COUNT(*) FROM leads WHERE owner IS NULL AND {QUEUE_SQL}").fetchone()[0],
                "mine": con.execute(f"SELECT COUNT(*) FROM leads WHERE {MINE_SQL}", (u["username"],)).fetchone()[0]}
    return {"stages": [{"key": k, "label": l, "count": counts[k]} for k, l in db.STAGES],
            "outcomes": db.CALL_OUTCOMES, "regions": regions, "themes": themes, "grades": grades,
            "follow_ups_due": due, "preview_base": config.SITE_URL + config.PREVIEW_PATH,
            "orders_sync": config.ONLINE_PAYMENTS and bool(config.ORDERS_API_TOKEN) and not rep, "dncr_due": dncr_due,
            "sales_email": config.SALES_EMAIL, "site_url": config.SITE_URL,
            "texts_waiting": 0 if rep else _texts_waiting(),
            "contact": {"phone": config.PHONE_DISPLAY, "whatsapp": config.WHATSAPP_DISPLAY}, "cloud": config.CLOUD,
            "user": {k: u[k] for k in ("username", "name", "role")}, "signed_in": bool(u["username"]),
            "working": {"slug": current["slug"], "name": current["name"]} if current else None,
            "rep_stages": sorted(db.REP_STAGES), "team": [] if rep else auth.team(), **pool,
            "offer": {"packages": [{k: p[k] for k in ("id", "name", "price", "launch_days")} for p in offer.PACKAGES],
                      "recommended": offer.recommended()["id"], "hosting_yearly": offer.HOSTING["yearly"],
                      "hourly": offer.HOURLY_RATE}}


def _texts_waiting() -> int:
    with db.connect() as con:
        return con.execute("SELECT COUNT(*) FROM texts WHERE status = 'pending'").fetchone()[0]


def _where(stage, grade, region, theme, q, mobile, due, queue, owner="", u=None, mine=False):
    sql, args = [], []
    if u and auth.is_rep(u):
        # A rep sees the lead they're working on and nothing else; otherwise
        # what's free to take, or (My leads) the ones already theirs.
        with db.connect() as con:
            current = db.working(con, u["username"])
        if current:
            return " WHERE slug = ?", [current["slug"]]
        sql.append(MINE_SQL if mine else f"owner IS NULL AND {QUEUE_SQL}")
        args += [u["username"]] if mine else []
    elif owner == "none":
        sql.append("owner IS NULL")
    elif owner:
        sql.append("owner = ?")
        args.append(owner)
    if queue:
        sql.append(QUEUE_SQL)
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
        sql.append(DUE_SQL)
    if q:
        like = f"%{q.strip()}%"
        sql.append("(name LIKE ? OR suburb LIKE ? OR phone LIKE ? OR phone_display LIKE ? OR category LIKE ? OR slug LIKE ?)")
        args += [like] * 6
    return (" WHERE " + " AND ".join(sql)) if sql else "", args


@router.get("/pipeline/api/leads")
def leads(request: Request, stage: str = "", grade: str = "", region: str = "", theme: str = "", q: str = "",
          mobile: bool = False, due: bool = False, queue: bool = False, owner: str = "", mine: bool = False,
          sort: str = "score", limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    u = auth.user(request)
    where, args = _where(stage, grade, region, theme, q, mobile, due, queue, owner, u, mine)
    order = SORTS.get(sort, SORTS["score"])
    with db.connect() as con:
        total = con.execute(f"SELECT COUNT(*) FROM leads{where}", args).fetchone()[0]
        rows = [dict(r) for r in con.execute(f"SELECT {LIST_COLUMNS} FROM leads{where} ORDER BY {order} LIMIT ? OFFSET ?",
                                             args + [limit, offset])]
    if auth.is_rep(u):
        # No dialling from the list: the number comes with the lead once it's theirs.
        for r in rows:
            if not r["working_since"]:
                r["phone"] = r["phone_display"] = ""
    return {"total": total, "leads": rows}


@router.get("/pipeline/api/leads.csv", dependencies=ADMIN)
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


def _mac_only() -> None:
    if config.CLOUD:
        raise HTTPException(400, "That runs on your Mac (it needs the marketing-site checkout): "
                                 "./run.sh there, or the python -m pipeline command.")


def _lead_or_404(con, slug: str, u: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The lead — and for a rep, only the one they're working on right now."""
    lead = db.get(con, slug)
    if not lead:
        raise HTTPException(404, "No such lead")
    if u and auth.is_rep(u) and not (lead["owner"] == u["username"] and lead["working_since"]):
        raise HTTPException(403, "Take this lead first (you can work on one at a time).")
    return lead


def _detail(con, slug: str) -> Dict[str, Any]:
    lead = _lead_or_404(con, slug)
    lead["history"] = db.history(con, slug)
    lead["preview_url"] = config.preview_url(slug)
    lead["stage_label"] = db.STAGE_LABELS[lead["stage"]]
    lead["short_name"] = documents.short_name(lead["name"])
    owner = con.execute("SELECT name FROM users WHERE username = ?", (lead["owner"],)).fetchone()
    lead["owner_name"] = owner["name"] if owner else lead["owner"]
    return lead


@router.get("/pipeline/api/leads/{slug}")
def lead_detail(slug: str, request: Request):
    with db.connect() as con:
        _lead_or_404(con, slug, auth.user(request))
        return _detail(con, slug)


@router.post("/pipeline/api/leads/{slug}/claim")
def claim_lead(slug: str, request: Request):
    """A rep takes a lead: it's theirs, and it's the only one they can see until they mark it done."""
    u = auth.user(request)
    if not u["username"]:
        raise HTTPException(400, "Sign-in is off: add users first (python -m pipeline users add).")
    with db.connect() as con:
        _lead_or_404(con, slug)
        try:
            db.claim(con, slug, u["username"], u["name"], QUEUE_SQL)
        except db.ClaimError as exc:
            raise HTTPException(409, str(exc))
        return _detail(con, slug)


@router.post("/pipeline/api/leads/{slug}/done")
def finish_lead(slug: str, request: Request):
    u = auth.user(request)
    with db.connect() as con:
        try:
            db.finish(con, slug, u["username"], u["name"])
        except db.ClaimError as exc:
            raise HTTPException(409, str(exc))
    return {"ok": True}


@router.post("/pipeline/api/leads/{slug}/owner", dependencies=ADMIN)
def set_owner(slug: str, body: OwnerBody, request: Request):
    with db.connect() as con:
        _lead_or_404(con, slug)
        try:
            db.assign(con, slug, body.owner or None, auth.user(request)["username"])
        except db.ClaimError as exc:
            raise HTTPException(400, str(exc))
        return _detail(con, slug)


@router.post("/pipeline/api/leads/{slug}/stage")
def change_stage(slug: str, body: StageBody, request: Request):
    u = auth.user(request)
    if body.stage not in db.STAGE_LABELS:
        raise HTTPException(400, "Unknown stage")
    if auth.is_rep(u) and body.stage not in db.REP_STAGES:
        raise HTTPException(403, f"Ask an admin to move it to “{db.STAGE_LABELS[body.stage]}”.")
    with db.connect() as con:
        _lead_or_404(con, slug, u)
        db.set_stage(con, slug, body.stage, body.note, u["username"])
        return _detail(con, slug)


@router.post("/pipeline/api/leads/{slug}/call")
def log_call(slug: str, body: CallBody, request: Request):
    u = auth.user(request)
    if body.outcome not in db.CALL_OUTCOMES:
        raise HTTPException(400, "Unknown outcome")
    with db.connect() as con:
        lead = _lead_or_404(con, slug, u)
        if not lead["owner"] and u["username"]:
            # An admin calling a free lead makes it theirs, so a rep doesn't ring it next.
            db.assign(con, slug, u["username"], u["username"])
        ts = db.now()
        con.execute("UPDATE leads SET attempts = attempts + 1, last_contact = ?, updated_at = ? WHERE slug = ?",
                    (ts, ts, slug))
        detail = db.CALL_OUTCOMES[body.outcome] + (f" — {body.note}" if body.note else "")
        db.log(con, slug, "call", detail, u["username"])
        if body.follow_up:
            con.execute("UPDATE leads SET follow_up = ? WHERE slug = ?", (body.follow_up, slug))
            db.advance(con, slug, "follow_up", f"call back {body.follow_up}", u["username"])
        elif body.outcome in ("gatekeeper", "owner", "sms", "email", "voicemail", "no_answer"):
            db.advance(con, slug, "contacted", by=u["username"])
        if body.outcome == "wrong_number":
            db.set_stage(con, slug, "do_not_contact", "wrong number", u["username"])
        return _detail(con, slug)


@router.post("/pipeline/api/leads/{slug}/sent")
def preview_sent(slug: str, body: SentBody, request: Request):
    """The rep opened an email or a text with the preview link (we can't see it go)."""
    u = auth.user(request)
    if body.via == "email" and auth.is_rep(u):
        raise HTTPException(403, f"Customer emails come from {config.SALES_EMAIL}: ask DuNous to email it.")
    what = {"email": "Preview link emailed", "sms": "Preview link texted",
            "request": f"Asked {config.SALES_EMAIL} to email the preview"}[body.via]
    with db.connect() as con:
        _lead_or_404(con, slug, u)
        db.log(con, slug, "sent", what + (f" to {body.to}" if body.to else ""), u["username"])
        return _detail(con, slug)


@router.post("/pipeline/api/leads/{slug}/handover")
def handover(slug: str, body: HandoverBody, request: Request):
    """They're interested: the rep emails the details to sales@, who sends the
    website pack and the invoice and talks to the customer from here on."""
    u = auth.user(request)
    email = body.email.strip()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "Add the customer's email first — that's where the website pack goes.")
    with db.connect() as con:
        _lead_or_404(con, slug, u)
        fields = {"email": email, **({"contact_name": body.contact_name.strip()} if body.contact_name.strip() else {})}
        con.execute(f"UPDATE leads SET {', '.join(f'{k} = ?' for k in fields)}, updated_at = ? WHERE slug = ?",
                    list(fields.values()) + [db.now(), slug])
        wants = f" — wants {body.package}" if body.package else ""
        db.log(con, slug, "handover", f"Handed to {config.SALES_EMAIL} for the website pack and invoice "
                                      f"(customer: {email}){wants}" + (f" · {body.note}" if body.note else ""),
               u["username"])
        db.advance(con, slug, "interested", f"handed to {config.SALES_EMAIL}", u["username"])
        return _detail(con, slug)


# ---- Texts: reps ask, someone with the DuNous phone sends -------------------
# No SMS service yet: a rep queues the text and a "texter" (or an admin) sends
# it from their phone with one tap on /pipeline/texts. An iPhone sends it as
# iMessage when the business has an iPhone, as a normal text otherwise.

@router.post("/pipeline/api/leads/{slug}/text")
def queue_text(slug: str, body: TextBody, request: Request):
    u = auth.user(request)
    if not body.consent:
        raise HTTPException(400, "Only text people who said yes to a text (the Spam Act).")
    with db.connect() as con:
        lead = _lead_or_404(con, slug, u)
        if not lead["mobile"]:
            raise HTTPException(400, "That's a landline — it can't get texts. Ask DuNous to email it instead.")
        if lead["dncr"] == "Y" or lead["stage"] == "do_not_contact":
            raise HTTPException(400, "This business asked not to be contacted.")
        if con.execute("SELECT 1 FROM texts WHERE slug = ? AND status = 'pending'", (slug,)).fetchone():
            raise HTTPException(409, "A text to them is already waiting to be sent.")
        con.execute("INSERT INTO texts (slug, phone, body, requested_by, requested_at) VALUES (?, ?, ?, ?, ?)",
                    (slug, lead["phone"], body.body.strip(), u["username"], db.now()))
        db.log(con, slug, "sent", "Text queued for DuNous to send (they said yes to a text)", u["username"])
        return _detail(con, slug)


@router.get("/pipeline/texts", include_in_schema=False, dependencies=[Depends(auth.can_text)])
def texts_page():
    return FileResponse(TEXTS_UI, headers={"Cache-Control": "no-store"})


@router.get("/pipeline/api/texts", dependencies=[Depends(auth.can_text)])
def texts(request: Request):
    with db.connect() as con:
        rows = con.execute(
            "SELECT t.*, l.name AS business, l.phone_display, COALESCE(u.name, t.requested_by) AS rep, "
            "COALESCE(d.name, t.done_by) AS sender FROM texts t JOIN leads l ON l.slug = t.slug "
            "LEFT JOIN users u ON u.username = t.requested_by LEFT JOIN users d ON d.username = t.done_by "
            "WHERE t.status = 'pending' OR t.id IN (SELECT id FROM texts WHERE status != 'pending' ORDER BY id DESC LIMIT 20) "
            "ORDER BY t.status != 'pending', t.id DESC").fetchall()
    return {"me": auth.user(request)["name"], "texts": [dict(r) for r in rows]}


@router.post("/pipeline/api/texts/{text_id}/{action}", dependencies=[Depends(auth.can_text)])
def text_done(text_id: int, action: str, request: Request):
    """sent: they sent it · skipped: not sending it · stop: they replied STOP."""
    if action not in ("sent", "skipped", "stop"):
        raise HTTPException(404, "Use sent, skipped or stop")
    u = auth.user(request)
    with db.connect() as con:
        t = con.execute("SELECT * FROM texts WHERE id = ?", (text_id,)).fetchone()
        if not t:
            raise HTTPException(404, "No such text")
        if action == "stop":
            # Spam Act: an unsubscribe request is honoured, so no more contact at all.
            db.set_stage(con, t["slug"], "do_not_contact", "replied STOP to our text", u["username"])
            return {"ok": True}
        if t["status"] != "pending":
            raise HTTPException(409, "Someone already dealt with that one.")
        con.execute("UPDATE texts SET status = ?, done_by = ?, done_at = ? WHERE id = ?",
                    (action, u["username"], db.now(), text_id))
        db.log(con, t["slug"], "sent", "Preview texted from the DuNous phone" if action == "sent"
               else "Text not sent (skipped)", u["username"])
    return {"ok": True}


@router.patch("/pipeline/api/leads/{slug}")
def edit_lead(slug: str, body: Dict[str, Any], request: Request):
    u = auth.user(request)
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
        before = _lead_or_404(con, slug, u)
        sets = ", ".join(f"{k} = ?" for k in fields)
        con.execute(f"UPDATE leads SET {sets}, updated_at = ? WHERE slug = ?", list(fields.values()) + [db.now(), slug])
        changed = [k for k, v in fields.items() if (before.get(k) or None) != (v or None)]
        if changed and changed != ["notes"]:
            db.log(con, slug, "edit", ", ".join(f"{k}: {fields[k]}" for k in changed if k != "notes"), u["username"])
        return _detail(con, slug)


@router.get("/pipeline/api/coverage", dependencies=ADMIN)
def coverage():
    _mac_only()
    return cov.coverage()


@router.post("/pipeline/api/import", dependencies=ADMIN)
def run_import():
    _mac_only()
    return importer.run()


@router.post("/pipeline/api/publish", dependencies=ADMIN)
def run_publish(body: PublishBody):
    _mac_only()
    lines: List[str] = []
    try:
        res = publish.publish(grades=body.grades, limit=body.limit, regions=body.regions,
                              min_score=body.min_score, log=lines.append)
    except publish.PublishError as exc:
        raise HTTPException(409, str(exc))
    return {**res, "log": lines}


@router.post("/pipeline/api/verify", dependencies=ADMIN)
def run_verify():
    lines: List[str] = []
    res = publish.verify(log=lines.append)
    return {**res, "log": lines}


@router.post("/pipeline/api/payments/sync", dependencies=ADMIN)
def run_payment_sync():
    lines: List[str] = []
    try:
        res = payments.sync(log=lines.append)
    except payments.SyncError as exc:
        raise HTTPException(409, str(exc))
    return {**res, "log": lines}


def _pdf(kind: str, lead: Optional[Dict[str, Any]]) -> Response:
    if kind not in documents.DOCUMENTS:
        raise HTTPException(404, f"Documents: {', '.join(documents.DOCUMENTS)}")
    try:
        pdf = documents.build(kind, lead)
    except Exception as exc:  # noqa: BLE001 — show why in the browser rather than a bare 500
        raise HTTPException(500, f"Couldn't build the PDF: {exc}")
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{documents.filename(kind, lead)}"',
        "Cache-Control": "no-store"})


@router.get("/pipeline/api/leads/{slug}/docs/{kind}.pdf")
def lead_document(slug: str, kind: str, request: Request):
    """The proposal, agreement, onboarding form or all three (pack), made for this lead."""
    u = auth.user(request)
    if auth.is_rep(u):
        raise HTTPException(403, f"The website pack goes out from {config.SALES_EMAIL}: use “Hand it to DuNous”.")
    with db.connect() as con:
        lead = _lead_or_404(con, slug, u)
    res = _pdf(kind, lead)
    with db.connect() as con:
        db.log(con, slug, "docs", f"{documents.DOCUMENTS[kind]['title']} PDF made", u["username"])
    return res


@router.get("/pipeline/api/docs/{kind}.pdf")
def generic_document(kind: str):
    """The same documents with no business filled in."""
    return _pdf(kind, None)


@router.get("/pipeline/api/dncr/wash.txt", dependencies=ADMIN)
def dncr_wash_file(scope: str = "calling", limit: Optional[int] = Query(None, ge=1, le=20000)):
    """Numbers to upload at donotcall.gov.au (not washed in the last 30 days)."""
    try:
        with db.connect() as con:
            text = dncr.wash_file(con, scope, limit)
    except dncr.WashError as exc:
        raise HTTPException(400, str(exc))
    if not text:
        raise HTTPException(404, "Nothing to wash: every number was washed in the last 30 days.")
    name = f"wash_{date.today():%Y%m%d}_{scope}.txt"
    return Response(text, media_type="text/plain",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.post("/pipeline/api/dncr/import", dependencies=ADMIN)
async def dncr_import(file: UploadFile = File(...), registered_only: bool = Form(False)):
    raw = await file.read()
    if len(raw) > 20_000_000:
        raise HTTPException(413, "That file is too big.")
    try:
        return dncr.load_results(raw.decode("utf-8-sig", errors="replace"), registered_only)
    except dncr.WashError as exc:
        raise HTTPException(400, str(exc))


@router.post("/pipeline/api/leads/{slug}/export", dependencies=ADMIN)
def run_export(slug: str):
    _mac_only()
    try:
        out = publish.export_site(slug, log=lambda _m: None)
    except publish.PublishError as exc:
        raise HTTPException(404, str(exc))
    return {"folder": str(out)}
