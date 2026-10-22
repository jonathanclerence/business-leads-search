"""Sign-in for the team, so the tracker can be shared with sales reps.

Off until the first user exists (`python -m pipeline users add …`): until
then everything works as before on your own machine, and any request that
arrives through a tunnel or proxy is refused, so the app is never on the
internet without a login.

Once on, every page needs a signed-in user:
  admin — everything: the lead finder, publishing, payments, every lead.
  rep   — only the tracker, and only the leads they're allowed (see web.py).

Sessions are a signed cookie (HMAC over the user and expiry, keyed with a
secret kept next to the database plus the user's password hash), so changing
someone's password or removing them signs them out everywhere.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import os
import secrets
import time
from collections import defaultdict, deque
from typing import Any, Dict, Optional
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.requests import HTTPConnection

from . import config, db

COOKIE = "lf_session"
SESSION_DAYS = 30
ITERATIONS = 240_000
USERNAME_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
# Anyone may load these (the login page itself).
OPEN_PATHS = {"/login", "/logout", "/favicon.ico"}
# Signed in on your own machine with no users set up yet.
LOCAL = {"username": "", "name": "", "role": "admin"}


# ---- Passwords ----------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f"pbkdf2${ITERATIONS}${salt}${digest}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
    except ValueError:
        return False
    return hmac.compare_digest(got, digest)


def valid_username(username: str) -> bool:
    return 2 <= len(username) <= 32 and set(username) <= USERNAME_CHARS


# ---- Users --------------------------------------------------------------------

_enabled = False


def enabled() -> bool:
    """Sign-in is on once anyone has an account. Remembered once true: every
    request asks, and on the shared database each question is a round trip."""
    global _enabled
    if not _enabled:
        with db.connect() as con:
            _enabled = con.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None
    return _enabled


def get_user(username: str) -> Optional[Dict[str, Any]]:
    with db.connect() as con:
        row = con.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


def team() -> list:
    with db.connect() as con:
        return [dict(r) for r in con.execute("SELECT username, name, role FROM users ORDER BY role, name")]


def user(request: Request) -> Dict[str, Any]:
    """The signed-in user (set by the middleware)."""
    return getattr(request.state, "user", None) or LOCAL


def is_rep(u: Dict[str, Any]) -> bool:
    return u["role"] != "admin"


def admin_only(request: Request) -> None:
    """FastAPI dependency for endpoints reps mustn't use."""
    if is_rep(user(request)):
        raise HTTPException(403, "Only an admin can do that.")


# ---- Sessions -----------------------------------------------------------------

def _secret() -> bytes:
    env = os.getenv("SESSION_SECRET", "").strip()
    if env:
        return env.encode()
    if config.CLOUD:  # no disk to keep one on, and every instance must agree
        raise RuntimeError("Set SESSION_SECRET in the Vercel project's environment variables.")
    path = db.DB_PATH.parent / ".session_secret"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    return path.read_text().strip().encode()


def _sign(username: str, expires: int, pw_hash: str) -> str:
    msg = f"{username}.{expires}".encode()
    return hmac.new(_secret() + pw_hash.encode(), msg, hashlib.sha256).hexdigest()


def make_cookie(u: Dict[str, Any]) -> str:
    expires = int(time.time()) + SESSION_DAYS * 86400
    return f"{u['username']}.{expires}.{_sign(u['username'], expires, u['pw_hash'])}"


def from_cookie(value: str) -> Optional[Dict[str, Any]]:
    try:
        username, expires, sig = value.split(".")
        if int(expires) < time.time():
            return None
    except ValueError:
        return None
    u = get_user(username)
    if not u or not hmac.compare_digest(sig, _sign(username, int(expires), u["pw_hash"])):
        return None
    return u


# A few wrong passwords are typos; dozens are someone guessing.
_FAILS: Dict[str, deque] = defaultdict(deque)
FAIL_LIMIT, FAIL_WINDOW = 8, 15 * 60


def _throttled(key: str) -> bool:
    q = _FAILS[key]
    while q and q[0] < time.time() - FAIL_WINDOW:
        q.popleft()
    return len(q) >= FAIL_LIMIT


def _client_ip(conn: HTTPConnection) -> str:
    return (conn.headers.get("cf-connecting-ip") or conn.headers.get("x-real-ip")
            or (conn.client.host if conn.client else ""))


def _proxied(conn: HTTPConnection) -> bool:
    """Arrived through a tunnel or proxy rather than from this computer's own browser."""
    host = conn.headers.get("host", "").rsplit(":", 1)[0].strip("[]")
    return bool(conn.headers.get("cf-connecting-ip") or conn.headers.get("x-forwarded-for")
                or host not in ("localhost", "127.0.0.1", "::1"))


# ---- Middleware ---------------------------------------------------------------

class AuthMiddleware:
    """Pure ASGI, so the lead finder's live progress streams aren't buffered."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        conn = HTTPConnection(scope)
        path = scope["path"]
        if path in OPEN_PATHS:
            return await self.app(scope, receive, send)
        if not enabled():
            if _proxied(conn):
                return await _deny(scope, receive, send, 403, "Team access isn't set up: add a user first "
                                   "(python -m pipeline users add <name> --admin).")
            scope.setdefault("state", {})["user"] = LOCAL
            return await self.app(scope, receive, send)
        u = from_cookie(conn.cookies.get(COOKIE, ""))
        if not u:
            if scope["type"] == "http" and "/api/" not in path and scope.get("method") == "GET":
                nxt = path + (f"?{scope['query_string'].decode()}" if scope.get("query_string") else "")
                return await RedirectResponse(f"/login?next={quote(nxt)}", 303)(scope, receive, send)
            return await _deny(scope, receive, send, 401, "Please sign in again.")
        if is_rep(u) and not (path == "/pipeline" or path.startswith("/pipeline/")):
            if scope["type"] == "http" and scope.get("method") == "GET" and "/api/" not in path:
                return await RedirectResponse("/pipeline", 303)(scope, receive, send)
            return await _deny(scope, receive, send, 403, "Only an admin can do that.")
        scope.setdefault("state", {})["user"] = u
        return await self.app(scope, receive, send)


async def _deny(scope, receive, send, status: int, message: str):
    if scope["type"] == "websocket":
        return await send({"type": "websocket.close", "code": 1008})
    return await JSONResponse({"detail": message}, status)(scope, receive, send)


# ---- Login page ---------------------------------------------------------------

def _safe_next(nxt: str) -> str:
    return nxt if nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt else "/pipeline"


def _login_page(nxt: str, error: str = "") -> HTMLResponse:
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Sign in · Pipeline</title>
<style>
:root{{--bg:#f5f5f3;--panel:#fff;--ink:#16181c;--muted:#6b7079;--line:#e4e4e0;--accent:#1f5eff;--bad:#c23030}}
@media (prefers-color-scheme:dark){{:root{{--bg:#121316;--panel:#1b1d21;--ink:#ececee;--muted:#9a9ea7;--line:#2b2e34;--accent:#6b93ff}}}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);
font:15px/1.45 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding:16px}}
form{{width:min(360px,100%);background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:24px;display:grid;gap:12px}}
h1{{font-size:20px;margin:0}}p{{margin:0;color:var(--muted)}}label{{display:grid;gap:4px;font-size:13px;font-weight:600;color:var(--muted)}}
input{{font:inherit;color:inherit;background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:9px 11px;outline:none}}
input:focus{{border-color:var(--accent)}}button{{font:inherit;font-weight:700;border:0;border-radius:9px;padding:10px;background:var(--accent);color:#fff;cursor:pointer}}
.err{{color:var(--bad);font-weight:600}}
</style></head><body>
<form method="post" action="/login"><h1>Pipeline</h1><p>Sign in to see your leads.</p>{err}
<input type="hidden" name="next" value="{html.escape(nxt)}">
<label>Username<input name="username" autocomplete="username" autocapitalize="none" required autofocus></label>
<label>Password<input name="password" type="password" autocomplete="current-password" required></label>
<button>Sign in</button></form></body></html>""", headers={"Cache-Control": "no-store"})


def install(app: FastAPI) -> None:
    app.add_middleware(AuthMiddleware)

    @app.get("/login", include_in_schema=False)
    def login_form(next: str = "/pipeline"):  # noqa: A002 — the query parameter is called next
        return _login_page(_safe_next(next))

    @app.post("/login", include_in_schema=False)
    def login(request: Request, username: str = Form(""), password: str = Form(""), next: str = Form("/pipeline")):  # noqa: A002
        username, nxt = username.strip().lower(), _safe_next(next)
        keys = (f"ip:{_client_ip(request)}", f"user:{username}")
        if any(_throttled(k) for k in keys):
            return _login_page(nxt, "Too many wrong passwords — wait 15 minutes and try again.")
        u = get_user(username)
        if not u or not check_password(password, u["pw_hash"]):
            for k in keys:
                _FAILS[k].append(time.time())
            return _login_page(nxt, "Wrong username or password.")
        res = RedirectResponse(nxt if u["role"] == "admin" else "/pipeline", 303)
        res.set_cookie(COOKIE, make_cookie(u), max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                       secure=request.url.scheme == "https")
        return res

    @app.get("/logout", include_in_schema=False)
    def logout():
        res = RedirectResponse("/login", 303)
        res.delete_cookie(COOKIE)
        return res
