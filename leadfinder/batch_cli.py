"""Command-line batch runner — the right tool for a 500+ search overnight sweep.

The dashboard is fine for a 20-search batch, but a whole-state sweep runs for
hours and should not depend on a browser tab staying open. Run it from a
terminal instead, ideally under `screen`/`tmux` or with `nohup` so it survives
you closing the laptop lid.

    # 1. sanity check first — 8 searches, ~5 minutes
    python batch_cli.py run --pairs data/starter_geelong.csv --name geelong-test

    # 2. see what a full sweep would cost BEFORE committing to it
    python batch_cli.py run --towns data/towns_victoria.csv \
                            --types data/business_types.csv \
                            --dry-run

    # 3. the real thing, trimmed to a sane size
    python batch_cli.py run --towns data/towns_victoria.csv \
                            --types data/business_types.csv \
                            --max-towns 40 --max-types 12 \
                            --name victoria-sweep

    # 4. it died / you stopped it / your IP got throttled — pick up where it left off
    python batch_cli.py resume latest

    # 5. hand off to the sales team
    python batch_cli.py export latest --no-website --min-score 60 -o hot-leads.csv

Ctrl-C once finishes the search in flight and saves cleanly; twice force-quits.
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from leadfinder.batch import (  # noqa: E402
    BatchConfig,
    BatchRunner,
    estimate_seconds,
    load_input_list,
    load_pairs,
)
from leadfinder.config import settings  # noqa: E402
from leadfinder.store import BatchStore, list_batches  # noqa: E402

BATCH_ROOT = Path(__file__).resolve().parent / "batches"

DIM, BOLD, GREEN, YELLOW, RED, RESET = (
    "\033[2m", "\033[1m", "\033[32m", "\033[33m", "\033[31m", "\033[0m"
)


def fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def resolve_batch(ref: str) -> Optional[Path]:
    """Accept a batch id, a directory path, or the literal 'latest'."""
    if ref in ("latest", "last"):
        batches = list_batches(BATCH_ROOT)
        return Path(batches[0]["dir"]) if batches else None
    p = Path(ref)
    if p.is_dir() and (p / "manifest.json").exists():
        return p
    candidate = BATCH_ROOT / ref
    if candidate.is_dir():
        return candidate
    # Allow a unique prefix.
    matches = [b for b in list_batches(BATCH_ROOT) if b["batch_id"].startswith(ref)]
    return Path(matches[0]["dir"]) if len(matches) == 1 else None


# ---------------------------------------------------------------------------
# Progress printing
# ---------------------------------------------------------------------------
def make_printer(verbose: bool = True):
    async def on_progress(event: str, data: Dict[str, Any]) -> None:
        msg = data.get("message", "")
        if event == "start":
            print(f"{BOLD}{msg}{RESET}")
            print(f"{DIM}  estimated wall-clock: {fmt_duration(data.get('eta_seconds', 0))}{RESET}\n")
        elif event == "task_start" and verbose:
            eta = fmt_duration(data.get("eta_seconds", 0))
            print(f"{DIM}{msg}  · eta {eta}{RESET}", flush=True)
        elif event == "task_done":
            new = data.get("new_leads", 0)
            colour = GREEN if new else DIM
            grades = data.get("grades", {}) or {}
            print(
                f"  {colour}+{new:>3} new{RESET}  "
                f"({data.get('found', 0)} found)  "
                f"total {data.get('leads_total', 0)} "
                f"| no-site {data.get('leads_no_website', 0)} "
                f"| hot {grades.get('Hot', 0)}",
                flush=True,
            )
        elif event == "task_error":
            print(f"  {RED}failed{RESET} — {msg}", flush=True)
        elif event == "blocked":
            print(f"\n{YELLOW}⚠ {msg}{RESET}\n", flush=True)
        elif event == "status":
            print(f"{DIM}  {msg}{RESET}", flush=True)
        elif event == "finished":
            print(f"\n{BOLD}{msg}{RESET}")
            print(f"  CSV: {data.get('csv')}")

    return on_progress


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
async def cmd_run(args: argparse.Namespace) -> int:
    pairs: List[Dict[str, str]] = []
    towns: List[str] = []
    types: List[str] = []

    if args.pairs:
        pairs = load_pairs(Path(args.pairs))
        if not pairs:
            print(f"{RED}No usable rows in {args.pairs}{RESET}")
            return 1
    else:
        if not args.towns or not args.types:
            print(f"{RED}Need --towns and --types (or --pairs).{RESET}")
            return 1
        towns = load_input_list(Path(args.towns), "town")
        types = load_input_list(Path(args.types), "type")
        if args.max_towns:
            towns = towns[: args.max_towns]
        if args.max_types:
            types = types[: args.max_types]
        if not towns or not types:
            print(f"{RED}Empty town or business-type list.{RESET}")
            return 1

    cfg = BatchConfig(
        name=args.name,
        towns=towns,
        business_types=types,
        pairs=pairs,
        max_results=args.max_results,
        provider=args.provider,
        order=args.order,
        pace_seconds=args.pace,
        long_break_every=args.long_break_every,
        long_break_seconds=args.long_break,
        recycle_every=args.recycle_every,
        state=args.state,
        country=args.country,
    )

    tasks = cfg.tasks()
    eta = estimate_seconds(len(tasks), cfg)

    print()
    print(f"{BOLD}Batch plan{RESET}")
    if pairs:
        print(f"  explicit pairs   {len(pairs)}")
    else:
        print(f"  towns            {len(towns)}  {DIM}{', '.join(towns[:6])}"
              f"{'…' if len(towns) > 6 else ''}{RESET}")
        print(f"  business types   {len(types)}  {DIM}{', '.join(types[:6])}"
              f"{'…' if len(types) > 6 else ''}{RESET}")
    print(f"  searches         {BOLD}{len(tasks)}{RESET}")
    print(f"  results/search   {cfg.max_results}  {DIM}(up to {len(tasks) * cfg.max_results:,} "
          f"listings read){RESET}")
    print(f"  pacing           {cfg.pace_seconds}s between, "
          f"{fmt_duration(cfg.long_break_seconds)} break every {cfg.long_break_every}")
    print(f"  estimated time   {BOLD}{fmt_duration(eta)}{RESET}")
    print()

    if eta > 6 * 3600:
        print(f"{YELLOW}⚠ That's over 6 hours on a single IP. Google will very likely "
              f"throttle you.{RESET}")
        print(f"{YELLOW}  Trim with --max-towns / --max-types, or set SCRAPER_PROXY "
              f"in .env, or split it across nights (resume picks up where it stops)."
              f"{RESET}\n")

    if args.dry_run:
        print(f"{DIM}Dry run — nothing was scraped. Drop --dry-run to start.{RESET}\n")
        for t in tasks[:10]:
            print(f"  {t['business_type']} in {t['town']}")
        if len(tasks) > 10:
            print(f"  {DIM}… and {len(tasks) - 10} more{RESET}")
        return 0

    if not args.yes and sys.stdin.isatty():
        if input("Start? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return 0

    store = BatchStore.create(BATCH_ROOT, args.name, cfg.to_dict())
    print(f"\n{DIM}batch dir: {store.dir}{RESET}\n")
    return await _drive(store, cfg, resume=False, verbose=not args.quiet)


async def cmd_resume(args: argparse.Namespace) -> int:
    batch_dir = resolve_batch(args.batch)
    if not batch_dir:
        print(f"{RED}No batch matching {args.batch!r}. Try: python batch_cli.py list{RESET}")
        return 1
    store = BatchStore.open(batch_dir)
    cfg = BatchConfig.from_dict(store.manifest.get("config", {}))
    if args.pace is not None:
        cfg.pace_seconds = args.pace

    total = len(cfg.tasks())
    done = sum(1 for t in store.done_tasks.values() if t.get("status") == "done")
    print(f"\n{BOLD}Resuming {store.manifest.get('batch_id')}{RESET}")
    print(f"  {done}/{total} searches already done, {len(store.leads)} leads collected")
    print(f"{DIM}  batch dir: {store.dir}{RESET}\n")
    return await _drive(store, cfg, resume=True, verbose=not args.quiet)


async def _drive(store: BatchStore, cfg: BatchConfig, resume: bool, verbose: bool) -> int:
    runner = BatchRunner(store, cfg, on_progress=make_printer(verbose))

    interrupts = {"n": 0}

    def handle_sigint(*_):
        interrupts["n"] += 1
        if interrupts["n"] == 1:
            print(f"\n{YELLOW}Finishing the current search, then saving… "
                  f"(Ctrl-C again to force quit){RESET}")
            runner.cancel()
        else:
            print(f"\n{RED}Force quit. Progress up to the last completed search is "
                  f"saved.{RESET}")
            raise SystemExit(130)

    signal.signal(signal.SIGINT, handle_sigint)

    with store:
        summary = await runner.run(resume=resume)

    _print_summary(summary, store)
    return 0


def _print_summary(summary: Dict[str, Any], store: BatchStore) -> None:
    c = summary.get("counts", {})
    g = c.get("grades", {}) or {}
    print(f"\n{BOLD}── Summary ─────────────────────────────────{RESET}")
    print(f"  searches      {c.get('tasks_done', 0)}/{c.get('tasks_total', 0)}"
          + (f"  {RED}({c.get('tasks_failed', 0)} failed){RESET}" if c.get("tasks_failed") else ""))
    print(f"  unique leads  {c.get('leads_total', 0)}  "
          f"{DIM}({c.get('duplicates', 0)} duplicates collapsed){RESET}")
    print(f"  no website    {GREEN}{c.get('leads_no_website', 0)}{RESET}")
    print(f"  grades        {GREEN}Hot {g.get('Hot', 0)}{RESET} · "
          f"Warm {g.get('Warm', 0)} · Cool {g.get('Cool', 0)} · {DIM}Cold {g.get('Cold', 0)}{RESET}")
    if summary.get("top_towns"):
        print(f"\n  {DIM}best towns (no-website leads):{RESET}")
        for town, n in summary["top_towns"][:8]:
            print(f"    {n:>4}  {town}")
    if summary.get("top_types"):
        print(f"\n  {DIM}best business types (no-website leads):{RESET}")
        for t, n in summary["top_types"][:8]:
            print(f"    {n:>4}  {t}")
    print(f"\n  {BOLD}Sales CSV:{RESET} {store.dir / 'leads.csv'}\n")


def cmd_list(args: argparse.Namespace) -> int:
    batches = list_batches(BATCH_ROOT)
    if not batches:
        print(f"{DIM}No batches yet. Start one with: python batch_cli.py run …{RESET}")
        return 0
    print(f"\n{BOLD}{'BATCH ID':<34} {'STATUS':<12} {'SEARCHES':<12} {'LEADS':<8} NO-SITE{RESET}")
    for b in batches:
        c = b.get("counts", {})
        status = b.get("status", "?")
        colour = {"done": GREEN, "running": YELLOW, "blocked": RED,
                  "paused": YELLOW}.get(status, DIM)
        print(f"{b['batch_id']:<34} {colour}{status:<12}{RESET} "
              f"{str(c.get('tasks_done', 0)) + '/' + str(c.get('tasks_total', 0)):<12} "
              f"{c.get('leads_total', 0):<8} {c.get('leads_no_website', 0)}")
    print()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    batch_dir = resolve_batch(args.batch)
    if not batch_dir:
        print(f"{RED}No batch matching {args.batch!r}.{RESET}")
        return 1
    store = BatchStore.open(batch_dir)
    _print_summary(store.summary(), store)

    failed = [t for t in store.done_tasks.values() if t.get("status") in ("failed", "blocked")]
    if failed:
        print(f"  {RED}{len(failed)} failed searches{RESET} "
              f"{DIM}(resume retries them){RESET}")
        for t in failed[:8]:
            print(f"    {t.get('query')} — {t.get('error', '')[:70]}")
        print()
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    batch_dir = resolve_batch(args.batch)
    if not batch_dir:
        print(f"{RED}No batch matching {args.batch!r}.{RESET}")
        return 1
    store = BatchStore.open(batch_dir)
    out = Path(args.output) if args.output else (store.dir / "leads.csv")
    path = store.export_csv(
        out,
        no_website_only=args.no_website,
        min_score=args.min_score,
        grades=args.grade,
        towns=args.town,
        business_types=args.type,
        require_phone=args.require_phone,
    )
    n = len(store.filtered(
        no_website_only=args.no_website, min_score=args.min_score, grades=args.grade,
        towns=args.town, business_types=args.type, require_phone=args.require_phone,
    ))
    print(f"{GREEN}✓{RESET} {n} leads → {path}")
    return 0


# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="batch_cli.py",
        description="Bulk Google Maps lead generation: CSV in → scored, deduplicated CSV out.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="start a new batch")
    r.add_argument("--towns", help="CSV of towns/suburbs")
    r.add_argument("--types", help="CSV of business types")
    r.add_argument("--pairs", help="CSV with explicit town+business_type columns "
                                   "(skips the cross product)")
    r.add_argument("--name", default="batch", help="batch name, used in the folder name")
    r.add_argument("--max-results", type=int, default=20,
                   help="listings per search (default 20 — plenty for a small town)")
    r.add_argument("--max-towns", type=int, help="use only the first N towns")
    r.add_argument("--max-types", type=int, help="use only the first N business types")
    r.add_argument("--order", choices=("type", "town"), default="type",
                   help="type = finish each vertical everywhere before moving on (default)")
    r.add_argument("--provider", choices=("playwright", "places_api"), default="playwright")
    r.add_argument("--pace", type=float, default=8.0, help="seconds between searches")
    r.add_argument("--long-break", type=float, default=180.0, help="long break, seconds")
    r.add_argument("--long-break-every", type=int, default=40)
    r.add_argument("--recycle-every", type=int, default=50, help="relaunch browser every N")
    r.add_argument("--state", default=settings.SEARCH_STATE,
                   help='added to every search, e.g. NSW → "plumber in Albury, NSW, Australia"')
    r.add_argument("--country", default=settings.SEARCH_COUNTRY,
                   help="added to every search; results outside it are dropped")
    r.add_argument("--dry-run", action="store_true", help="show the plan, scrape nothing")
    r.add_argument("--yes", "-y", action="store_true", help="skip the confirmation prompt")
    r.add_argument("--quiet", "-q", action="store_true")

    rs = sub.add_parser("resume", help="continue an interrupted batch")
    rs.add_argument("batch", nargs="?", default="latest", help="batch id, path, or 'latest'")
    rs.add_argument("--pace", type=float, help="override pacing (raise it if you got blocked)")
    rs.add_argument("--quiet", "-q", action="store_true")

    sub.add_parser("list", help="list all batches")

    st = sub.add_parser("status", help="show one batch's progress and stats")
    st.add_argument("batch", nargs="?", default="latest")

    e = sub.add_parser("export", help="write the sales CSV")
    e.add_argument("batch", nargs="?", default="latest")
    e.add_argument("-o", "--output", help="output path (default <batch>/leads.csv)")
    e.add_argument("--no-website", action="store_true", help="only businesses with no website")
    e.add_argument("--min-score", type=int, default=0, help="0-100 booking-fit score floor")
    e.add_argument("--grade", action="append", help="Hot|Warm|Cool|Cold (repeatable)")
    e.add_argument("--town", action="append", help="filter by search town (repeatable)")
    e.add_argument("--type", action="append", help="filter by business type (repeatable)")
    e.add_argument("--require-phone", action="store_true", help="drop leads with no phone")
    return p


def main() -> int:
    args = build_parser().parse_args()
    BATCH_ROOT.mkdir(exist_ok=True)
    settings.EXPORT_DIR.mkdir(exist_ok=True)

    if args.command == "run":
        return asyncio.run(cmd_run(args))
    if args.command == "resume":
        return asyncio.run(cmd_resume(args))
    if args.command == "list":
        return cmd_list(args)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "export":
        return cmd_export(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
