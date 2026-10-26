"""python -m pipeline <command>  —  see pipeline/__init__.py or `--help`."""

from __future__ import annotations

import argparse
import getpass
import json
import secrets
import sys
import time

from . import auth
from . import coverage as cov
from . import db, dncr, documents, importer, publish
from .content import KIND_GROUPS, expand_kinds


def _list(value: str):
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _kinds(p, value: str):
    try:
        return expand_kinds(_list(value))
    except ValueError as exc:
        p.error(str(exc))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m pipeline", description="Leads → previews → paying clients.")
    sub = p.add_subparsers(dest="cmd", required=True)

    im = sub.add_parser("import", help="rebuild the clean list from batches/*/leads.csv and add new leads to the tracker")
    im.add_argument("--batch", action="append", default=[],
                    help="import only this batch (folder name under batches/; repeatable). Default: every batch")
    im.add_argument("--add-only", action="store_true",
                    help="only add businesses the tracker doesn't have; leave tracked leads untouched")

    pub = sub.add_parser("publish", help="generate previews for the next leads and push them live")
    pub.add_argument("--grade", default="Hot", help="comma list, e.g. Hot,Warm (default Hot). Use 'all' for every grade")
    pub.add_argument("--limit", type=int, help="at most this many new previews (0 = just update the live ones)")
    pub.add_argument("--min-score", type=int, default=0)
    pub.add_argument("--region", default="", help="comma list of regions, e.g. Geelong,Ballarat")
    pub.add_argument("--kind", default="", help=f"comma list of kinds or groups ({', '.join(KIND_GROUPS)}), e.g. blue-collar")
    pub.add_argument("--no-push", action="store_true", help="commit in the publish worktree but don't push")
    pub.add_argument("--local", action="store_true", help="write into your own marketing-site checkout for `npm run dev`")
    pub.add_argument("--wait", action="store_true", help="after pushing, wait for the deploy and mark previews live")

    en = sub.add_parser("enrich", help="add real opening hours + Google review quotes to the next leads (run before publish)")
    en.add_argument("--grade", default="Hot", help="comma list (default Hot)")
    en.add_argument("--limit", type=int, default=100)
    en.add_argument("--kind", default="", help="comma list of kinds or groups, as for publish")
    en.add_argument("--pace", type=float, default=6.0, help="seconds between businesses (keep ≥ 6)")

    cm = sub.add_parser("campaign", help="batches of previews start to finish: enrich, publish, wait until live, website packs")
    cm.add_argument("--kind", default="", help="comma list of kinds or groups, e.g. blue-collar")
    cm.add_argument("--grade", default="Hot,Warm", help="comma list (default Hot,Warm), or 'all'")
    cm.add_argument("--batches", type=int, default=1, help="how many batches (default 1)")
    cm.add_argument("--size", type=int, default=100, help="previews per batch (default 100)")
    cm.add_argument("--no-enrich", action="store_true", help="skip opening hours and review quotes")
    cm.add_argument("--pace", type=float, default=6.0, help="enrich: seconds between businesses (keep ≥ 6)")

    sub.add_parser("verify", help="mark published previews whose URL loads as 'Preview live'")
    sub.add_parser("coverage", help="towns × business types searched, by region")
    sub.add_parser("stats", help="how many leads are at each stage")

    ex = sub.add_parser("export-site", help="the finished site for a client, ready to upload to their Cloudflare")
    ex.add_argument("slug")

    dc = sub.add_parser("docs", help="client PDFs: proposal, agreement, onboarding form, or all three as one pack")
    dc.add_argument("slugs", nargs="*", metavar="slug", help="the lead(s) (omit with --generic or --live)")
    dc.add_argument("--kind", default="pack", choices=list(documents.DOCUMENTS) + ["all"])
    dc.add_argument("--generic", action="store_true",
                    help="rebuild the generic pack linked from every preview (pipeline/assets/)")
    dc.add_argument("--live", action="store_true",
                    help="every lead with a live preview that doesn't have this document in exports/docs/ yet")
    dc.add_argument("--business", default="", help="with --live: only these kinds or groups, e.g. blue-collar")
    dc.add_argument("--redo", action="store_true", help="with --live: rebuild documents that already exist")

    dn = sub.add_parser("dncr", help="Do Not Call Register: export numbers to wash, import the results")
    dn.add_argument("action", choices=["export", "import"])
    dn.add_argument("file", nargs="?", help="import: the results file from donotcall.gov.au")
    dn.add_argument("--scope", default="calling", choices=dncr.SCOPES,
                    help="export: calling (live previews, default), next (the next leads publish will pick) or all")
    dn.add_argument("--limit", type=int, help="export: at most this many leads")
    dn.add_argument("--registered-only", action="store_true",
                    help="import: the file lists only numbers that ARE on the register (no Y/N/I column)")

    us = sub.add_parser("users", help="who can sign in to the tracker (sign-in turns on with the first user)")
    us.add_argument("action", choices=["add", "list", "password", "rename", "remove"])
    us.add_argument("username", nargs="?", help="lowercase letters, digits, - or _, e.g. sam")
    us.add_argument("--name", help="add/rename: the name history and the call scripts use (default: the username, capitalised)")
    us.add_argument("--admin", action="store_true", help="add: full access (lead finder, publishing, every lead)")
    us.add_argument("--texter", action="store_true",
                    help="add: sends the reps' texts from their phone (sees only the texts page)")
    us.add_argument("--ask", action="store_true", help="add/password: type the password instead of generating one")

    cp = sub.add_parser("copy-to-cloud", help="one-off: copy batches/pipeline.db into the shared database (DATABASE_URL)")
    cp.add_argument("--replace", action="store_true", help="empty the shared database first (it already has leads)")

    st = sub.add_parser("stage", help="move a lead to a stage")
    st.add_argument("slug")
    st.add_argument("stage", choices=db.STAGE_KEYS)
    st.add_argument("--note", default="")

    a = p.parse_args(argv)

    if a.cmd == "import":
        paths = [importer.BATCH_ROOT / b / "leads.csv" for b in a.batch]
        missing = [str(x) for x in paths if not x.exists()]
        if missing:
            p.error(f"no leads.csv for: {', '.join(missing)}")
        print(json.dumps(importer.run(paths or None, add_only=a.add_only), indent=2))
    elif a.cmd == "publish":
        grades = [] if a.grade.lower() == "all" else _list(a.grade)
        res = publish.publish(grades=grades, limit=a.limit, min_score=a.min_score, regions=_list(a.region),
                              push=not a.no_push, local=a.local, kinds=_kinds(p, a.kind))
        print(json.dumps(res, indent=2))
        if a.wait and res["pushed"]:
            deadline = time.time() + 15 * 60
            time.sleep(60)
            while time.time() < deadline:
                left = publish.verify()["missing"]
                if not left:
                    break
                time.sleep(45)
    elif a.cmd == "enrich":
        from .enrich import enrich
        with db.connect() as con:
            # The same leads `publish` will pick next, in the same order.
            slugs = publish.select_new(con, _list(a.grade), a.limit, kinds=_kinds(p, a.kind))
            slugs = [s for s in slugs if not con.execute(
                "SELECT enriched_at FROM leads WHERE slug = ?", (s,)).fetchone()[0]]
        print(json.dumps(enrich(slugs, pace=a.pace), indent=2))
    elif a.cmd == "campaign":
        from .campaign import run
        grades = [] if a.grade.lower() == "all" else _list(a.grade)
        print(json.dumps(run(_kinds(p, a.kind), grades, a.batches, a.size, not a.no_enrich, a.pace), indent=2))
    elif a.cmd == "verify":
        print(json.dumps(publish.verify(), indent=2))
    elif a.cmd == "coverage":
        c = cov.coverage()
        print(f"{c['searches_done']} searches done across {c['types']} business types\n")
        print(f"{'Region':24} {'State':10} {'Towns':>6} {'Done':>5} {'Part':>5} {'Search%':>8} {'Leads':>6}  Not searched yet")
        for r in c["regions"]:
            todo = ", ".join(r["todo"][:6]) + ("…" if len(r["todo"]) > 6 else "")
            print(f"{r['region'][:24]:24} {r['state'][:10]:10} {r['towns']:>6} {r['towns_done']:>5} "
                  f"{r['towns_partial']:>5} {r['percent']:>7}% {r['leads']:>6}  {todo}")
    elif a.cmd == "stats":
        with db.connect() as con:
            for k, n in db.stage_counts(con).items():
                print(f"{db.STAGE_LABELS[k]:20} {n:>6}")
    elif a.cmd == "export-site":
        publish.export_site(a.slug)
    elif a.cmd == "docs":
        if a.generic:
            changed = documents.ensure_generic_pack(force=True)
            print(f"{'Rebuilt' if changed else 'Up to date:'} {documents.GENERIC_PACK}")
            return 0
        kinds = list(documents.DOCUMENTS) if a.kind == "all" else [a.kind]
        with db.connect() as con:
            if a.live:
                leads = publish.active_leads(con)
                if a.business:
                    wanted = set(_kinds(p, a.business))
                    leads = [l for l in leads if l["kind"] in wanted]
                leads.sort(key=lambda l: (-(l["score"] or 0), -(l["reviews"] or 0), l["slug"]))
            elif a.slugs:
                leads = [db.get(con, s) for s in a.slugs]
                missing = [s for s, l in zip(a.slugs, leads) if not l]
                if missing:
                    p.error(f"no lead {', '.join(map(repr, missing))}")
            else:
                p.error("docs needs a lead slug, --live or --generic")
        jobs = [(k, l) for l in leads for k in kinds
                if a.redo or not a.live or not documents.export_path(k, l).exists()]
        if not jobs:
            print("Nothing to make: every live preview already has its documents.")
            return 0
        res = documents.save_many(jobs)
        print(json.dumps({"made": len(res["made"]), "failed": res["failed"],
                          "folder": str(documents.EXPORT_DIR)}, indent=2))
    elif a.cmd == "dncr":
        if a.action == "export":
            out = dncr.export(a.scope, a.limit)
            n = out.read_text().count("\n")
            print(f"{n} numbers to wash → {out}" if n else "Nothing to wash: every number was washed in the last 30 days.")
        else:
            if not a.file:
                p.error("dncr import needs the results file")
            with open(a.file, encoding="utf-8-sig", errors="replace") as f:
                print(json.dumps(dncr.load_results(f.read(), a.registered_only), indent=2))
    elif a.cmd == "users":
        return _users(p, a)
    elif a.cmd == "copy-to-cloud":
        return _copy_to_cloud(p, a)
    elif a.cmd == "stage":
        with db.connect() as con:
            changed = db.set_stage(con, a.slug, a.stage, a.note)
        print("updated" if changed else "no change")
    return 0


def _password(a) -> str:
    if not a.ask:
        return secrets.token_urlsafe(9)
    pw = getpass.getpass("Password: ")
    if len(pw) < 8 or pw != getpass.getpass("Again: "):
        sys.exit("✗ Passwords must match and be at least 8 characters.")
    return pw


def _users(p, a) -> int:
    if a.action == "list":
        with db.connect() as con:
            rows = con.execute(
                "SELECT u.username, u.name, u.role, w.name AS working, "
                f"(SELECT COUNT(*) FROM leads l WHERE l.owner = u.username AND l.stage NOT IN {db.CLOSED_STAGES}) AS open_leads "
                "FROM users u LEFT JOIN leads w ON w.owner = u.username AND w.working_since IS NOT NULL "
                "ORDER BY u.role, u.name").fetchall()
        if not rows:
            print("No users yet: sign-in is off. Start with: python -m pipeline users add <you> --admin")
        for r in rows:
            print(f"{r['username']:16} {r['name']:20} {r['role']:6} {r['open_leads']:>4} open leads"
                  + (f" · working on {r['working']}" if r["working"] else ""))
        return 0
    if not a.username:
        p.error(f"users {a.action} needs a username")
    username = a.username.strip().lower()
    with db.connect() as con:
        existing = con.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if a.action == "add":
            if existing:
                p.error(f"{username!r} already exists (use: users password {username})")
            if not auth.valid_username(username):
                p.error("usernames are 2–32 lowercase letters, digits, - or _")
            if not con.execute("SELECT 1 FROM users WHERE role = 'admin'").fetchone() and not a.admin:
                p.error("the first user must be you, with --admin (once sign-in is on, everyone needs an account)")
            pw = _password(a)
            role = "admin" if a.admin else "texter" if a.texter else "rep"
            con.execute("INSERT INTO users (username, name, role, pw_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                        (username, (a.name or "").strip()[:40] or username.capitalize(),
                         role, auth.hash_password(pw), db.now()))
            print(f"Added {username} ({role}).")
        elif not existing:
            p.error(f"no user {username!r}")
        elif a.action == "password":
            pw = _password(a)
            con.execute("UPDATE users SET pw_hash = ? WHERE username = ?", (auth.hash_password(pw), username))
            print(f"New password for {username} — they're signed out everywhere.")
        elif a.action == "rename":
            if not (a.name or "").strip():
                p.error("users rename needs --name")
            con.execute("UPDATE users SET name = ? WHERE username = ?", (a.name.strip()[:40], username))
            print(f"{username} is now shown as {a.name.strip()[:40]}.")
        else:  # remove
            if existing["role"] == "admin" and con.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0] == 1 \
                    and con.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 1:
                p.error("that's the last admin — add another admin first")
            # Their open leads go back to the pool; closed ones keep their name for the record.
            freed = con.execute(f"UPDATE leads SET owner = NULL, working_since = NULL WHERE owner = ? "
                                f"AND stage NOT IN {db.CLOSED_STAGES}", (username,)).rowcount
            con.execute("UPDATE leads SET working_since = NULL WHERE owner = ?", (username,))
            con.execute("DELETE FROM users WHERE username = ?", (username,))
            print(f"Removed {username}; {freed} open leads are back in the pool for anyone.")
            return 0
    if a.action in ("add", "password") and not a.ask:
        print(f"Password: {pw}")
    return 0


def _copy_to_cloud(p, a) -> int:
    """Users, leads and their whole history from the SQLite file into Postgres, as they are."""
    if not db.DATABASE_URL:
        p.error("set DATABASE_URL (in .env) to the shared database first")
    with db.connect(db.DB_PATH) as src:   # by path: always the SQLite file
        tables = {t: [dict(r) for r in src.execute(f"SELECT * FROM {t} ORDER BY rowid")]
                  for t in ("users", "leads", "events")}
    with db.connect() as dst:
        if dst.execute("SELECT COUNT(*) FROM leads").fetchone()[0] and not a.replace:
            p.error("the shared database already has leads; --replace empties it first")
        dst.execute("TRUNCATE events, leads, users RESTART IDENTITY")
        for table, rows in tables.items():
            if rows:
                cols = list(rows[0])
                dst.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                [[r[c] for c in cols] for r in rows])
        # New history continues after the copied rows' ids.
        dst.execute("SELECT setval(pg_get_serial_sequence('events', 'id'), (SELECT COALESCE(MAX(id), 1) FROM events))")
    print("Copied " + ", ".join(f"{len(rows):,} {t}" for t, rows in tables.items()) + f" from {db.DB_PATH.name}.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except publish.PublishError as exc:
        print(f"\n✗ {exc}", file=sys.stderr)
        sys.exit(1)
