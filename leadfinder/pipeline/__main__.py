"""python -m pipeline <command>  —  see pipeline/__init__.py or `--help`."""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import coverage as cov
from . import db, importer, publish


def _list(value: str):
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m pipeline", description="Leads → previews → paying clients.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("import", help="rebuild the clean list from batches/*/leads.csv and add new leads to the tracker")

    pub = sub.add_parser("publish", help="generate previews for the next leads and push them live")
    pub.add_argument("--grade", default="Hot", help="comma list, e.g. Hot,Warm (default Hot). Use 'all' for every grade")
    pub.add_argument("--limit", type=int, help="at most this many new previews")
    pub.add_argument("--min-score", type=int, default=0)
    pub.add_argument("--region", default="", help="comma list of regions, e.g. Geelong,Ballarat")
    pub.add_argument("--no-push", action="store_true", help="commit in the publish worktree but don't push")
    pub.add_argument("--local", action="store_true", help="write into your own marketing-site checkout for `npm run dev`")
    pub.add_argument("--wait", action="store_true", help="after pushing, wait for the deploy and mark previews live")

    sub.add_parser("verify", help="mark published previews whose URL loads as 'Preview live'")
    sub.add_parser("coverage", help="towns × business types searched, by region")
    sub.add_parser("stats", help="how many leads are at each stage")

    ex = sub.add_parser("export-site", help="the finished site for a client, ready to upload to their Cloudflare")
    ex.add_argument("slug")

    st = sub.add_parser("stage", help="move a lead to a stage")
    st.add_argument("slug")
    st.add_argument("stage", choices=db.STAGE_KEYS)
    st.add_argument("--note", default="")

    a = p.parse_args(argv)

    if a.cmd == "import":
        print(json.dumps(importer.run(), indent=2))
    elif a.cmd == "publish":
        grades = [] if a.grade.lower() == "all" else _list(a.grade)
        res = publish.publish(grades=grades, limit=a.limit, min_score=a.min_score, regions=_list(a.region),
                              push=not a.no_push, local=a.local)
        print(json.dumps(res, indent=2))
        if a.wait and res["pushed"]:
            deadline = time.time() + 15 * 60
            time.sleep(60)
            while time.time() < deadline:
                left = publish.verify()["missing"]
                if not left:
                    break
                time.sleep(45)
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
    elif a.cmd == "stage":
        with db.connect() as con:
            changed = db.set_stage(con, a.slug, a.stage, a.note)
        print("updated" if changed else "no change")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except publish.PublishError as exc:
        print(f"\n✗ {exc}", file=sys.stderr)
        sys.exit(1)
