"""Build preview pages and put them live on dunous.com.

publish():
  1. picks the next leads to publish (stage "new", best score first) and
     moves them to "preview_created";
  2. renders a page for every lead that should have one (see
     db.PREVIEW_STAGES) and removes pages for leads that shouldn't any more
     (said no, asked us to stop, or are live on their own domain);
  3. commits that to the production branch of the marketing site from a
     separate git worktree — your own checkout is never touched — and pushes.
     Cloudflare Pages deploys the push in a minute or two.

verify() then checks each published URL and moves the ones that load to
"preview_hosted".
"""

from __future__ import annotations

import concurrent.futures
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import config, db
from .render import ASSET_SRC, render

Log = Callable[[str], None]


class PublishError(RuntimeError):
    pass


def _git(cwd: Path, *args: str) -> str:
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if res.returncode:
        raise PublishError(f"git {' '.join(args)} failed:\n{(res.stderr or res.stdout).strip()}")
    return res.stdout.strip()


def select_new(con, grades: Sequence[str], limit: Optional[int], min_score: int = 0,
               regions: Sequence[str] = ()) -> List[str]:
    sql = "SELECT slug FROM leads WHERE stage = 'new' AND score >= ?"
    args: List[Any] = [min_score]
    if grades:
        sql += f" AND grade IN ({','.join('?' * len(grades))})"
        args += list(grades)
    if regions:
        sql += f" AND region IN ({','.join('?' * len(regions))})"
        args += list(regions)
    sql += " ORDER BY score DESC, reviews DESC"
    if limit:
        sql += " LIMIT ?"
        args.append(limit)
    return [r["slug"] for r in con.execute(sql, args)]


def active_leads(con) -> List[Dict[str, Any]]:
    marks = ",".join("?" * len(db.PREVIEW_STAGES))
    rows = con.execute(f"SELECT * FROM leads WHERE stage IN ({marks})", sorted(db.PREVIEW_STAGES))
    return [dict(r) for r in rows]


def write_site_files(site_dir: Path, leads: List[Dict[str, Any]]) -> Dict[str, int]:
    """Render pages into <site>/public/previewsite-pages and sync the shared css/js."""
    pages = site_dir / config.PAGES_DIR
    pages.mkdir(parents=True, exist_ok=True)
    assets = site_dir / config.ASSETS_DIR
    assets.mkdir(parents=True, exist_ok=True)
    for f in ASSET_SRC.iterdir():
        shutil.copyfile(f, assets / f.name)

    wanted = set()
    written = 0
    for lead in leads:
        wanted.add(lead["slug"])
        target = pages / lead["slug"]
        html = render(lead)
        if not target.exists() or target.read_text(encoding="utf-8") != html:
            target.write_text(html, encoding="utf-8")
            written += 1
    removed = 0
    for f in pages.iterdir():
        if f.is_file() and f.name not in wanted and not f.name.startswith("."):
            f.unlink()
            removed += 1
    return {"pages": len(wanted), "written": written, "removed": removed}


def prepare_worktree(log: Log) -> Path:
    site, wt = config.MARKETING_SITE_DIR, config.PUBLISH_WORKTREE
    remote, branch = config.PUBLISH_REMOTE, config.PUBLISH_BRANCH
    if not (site / ".git").exists():
        raise PublishError(f"Marketing site repo not found at {site} (set MARKETING_SITE_DIR in .env)")
    log(f"Fetching {remote}/{branch}…")
    _git(site, "fetch", remote, branch)
    if not (wt / ".git").exists():
        log(f"Creating publish worktree at {wt}")
        _git(site, "worktree", "prune")
        _git(site, "worktree", "add", "--detach", str(wt), f"{remote}/{branch}")
    else:
        _git(wt, "checkout", "--force", "--detach", f"{remote}/{branch}")
        _git(wt, "clean", "-fdq", "--", config.PAGES_DIR)
    if not (wt / "src/app/previewsite/[slug]/route.ts").exists():
        raise PublishError(
            f"{branch} doesn't have the /previewsite route yet. Merge the branch with the preview "
            f"feature (development) into {branch} and push it first.")
    if not (wt / config.ASSETS_DIR / "img").exists():
        raise PublishError(f"{branch} is missing {config.ASSETS_DIR}/img (the stock photos). Merge development first.")
    return wt


def commit_and_push(wt: Path, message: str, push: bool, log: Log) -> bool:
    # -f: the pages folder is gitignored in the site repo so nobody commits
    # previews by hand on a feature branch; only this publisher adds them.
    _git(wt, "add", "-A", "-f", "--", config.PAGES_DIR, config.ASSETS_DIR)
    if not _git(wt, "status", "--porcelain", "--", config.PAGES_DIR, config.ASSETS_DIR):
        log("No changes — dunous.com already has these previews.")
        return False
    _git(wt, "commit", "-q", "-m", message)
    if not push:
        log("Committed in the publish worktree (not pushed: --no-push).")
        return True
    remote, branch = config.PUBLISH_REMOTE, config.PUBLISH_BRANCH
    log(f"Pushing to {remote}/{branch}…")
    try:
        _git(wt, "push", remote, f"HEAD:{branch}")
    except PublishError:
        # Someone pushed to the branch meanwhile; previews only touch their own
        # folders, so a rebase never conflicts with real site work.
        log("Branch moved on — rebasing and retrying once.")
        _git(wt, "fetch", remote, branch)
        _git(wt, "rebase", f"{remote}/{branch}")
        _git(wt, "push", remote, f"HEAD:{branch}")
    log("Pushed. Cloudflare Pages usually deploys within 1–3 minutes.")
    return True


def publish(grades: Sequence[str] = ("Hot",), limit: Optional[int] = None, min_score: int = 0,
            regions: Sequence[str] = (), push: bool = True, local: bool = False,
            log: Log = print) -> Dict[str, Any]:
    """`local=True` writes into your own marketing-site checkout instead (for
    `npm run dev`) and leaves every lead's stage alone.

    Stage changes share one transaction with the publish: if the commit or
    push fails, nothing is marked as published.
    """
    with db.connect() as con:
        fresh = select_new(con, grades, limit, min_score, regions)
        target = config.MARKETING_SITE_DIR if local else prepare_worktree(log)
        leads = active_leads(con) + [db.get(con, s) for s in fresh]
        log(f"Rendering {len(leads)} preview pages ({len(fresh)} new)…")
        stats = write_site_files(target, leads)
        if local:
            log(f"Wrote pages into {target / config.PAGES_DIR} — run `npm run dev` there and open "
                f"http://localhost:3000/previewsite/<slug>")
            return {"new": len(fresh), **stats, "pushed": False, "new_slugs": fresh[:20]}

        msg = f"Previews: {stats['pages']} live (+{len(fresh)} new, {stats['removed']} removed)"
        committed = commit_and_push(target, msg, push, log)
        for slug in fresh:
            db.set_stage(con, slug, "preview_created", "preview page generated")
            if committed and push:
                db.log(con, slug, "publish", config.preview_url(slug))
    return {"new": len(fresh), **stats, "pushed": committed and push, "new_slugs": fresh[:20]}


def _is_live(url: str) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": "DuNous-pipeline/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200 and b"pv-slug" in r.read(4096)
    except Exception:  # noqa: BLE001 — 404s, timeouts: simply not live (yet)
        return False


def verify(slugs: Optional[Sequence[str]] = None, log: Log = print) -> Dict[str, Any]:
    """Mark leads whose preview URL loads as "preview_hosted"."""
    with db.connect() as con:
        if slugs is None:
            slugs = [r["slug"] for r in con.execute("SELECT slug FROM leads WHERE stage = 'preview_created'")]
        slugs = list(slugs)
        if not slugs:
            log("Nothing waiting to be verified.")
            return {"checked": 0, "live": 0, "missing": []}
        log(f"Checking {len(slugs)} preview URLs…")
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            results = dict(zip(slugs, pool.map(lambda s: _is_live(config.preview_url(s)), slugs)))
        live = [s for s, ok in results.items() if ok]
        for slug in live:
            db.advance(con, slug, "preview_hosted", config.preview_url(slug))
        missing = [s for s, ok in results.items() if not ok]
        log(f"{len(live)} live, {len(missing)} not live yet.")
    return {"checked": len(slugs), "live": len(live), "missing": missing[:50]}


def export_site(slug: str, log: Log = print) -> Path:
    """The finished site for a paying client: a folder you can drag into
    Cloudflare Pages → Create → Upload assets on *their* account."""
    with db.connect() as con:
        lead = db.get(con, slug)
    if not lead:
        raise PublishError(f"No lead {slug!r}")
    out = config.EXPORT_DIR / slug
    if out.exists():
        shutil.rmtree(out)
    (out / "assets" / "img").mkdir(parents=True)
    (out / "index.html").write_text(render(lead, final=True, assets="assets"), encoding="utf-8")
    for name in ("preview.css", "preview-icons.svg"):
        shutil.copyfile(ASSET_SRC / name, out / "assets" / name)
    img_src = config.MARKETING_SITE_DIR / config.ASSETS_DIR / "img"
    for part in ("hero", "about"):
        f = img_src / f"{lead['theme']}-{part}.webp"
        if f.exists():
            shutil.copyfile(f, out / "assets" / "img" / f.name)
    log(f"Exported {out} — swap in the client's own photos in assets/img/ before going live.")
    return out
