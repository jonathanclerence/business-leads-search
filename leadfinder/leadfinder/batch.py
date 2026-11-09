"""Bulk batch runner — CSV in, deduplicated scored leads out.

Feed it a list of towns and a list of business types; it runs the cross
product ("pet groomers in Geelong", "salons in Geelong", "pet groomers in
Highton", …), deduplicates across every search, scores each lead for
booking-system fit, and checkpoints after every single search so an
interrupted overnight run resumes instead of restarting.

Design notes that matter at 500+ searches
-----------------------------------------
**One browser, not 500.** Chromium cold-starts in ~3s. Launching per search
would add 25 minutes of pure startup to a 500-search sweep. The browser is
reused and recycled every ``recycle_every`` searches to shed accumulated
cookies and memory.

**Type-major ordering.** Tasks run as "every town for business type #1, then
every town for type #2". If the run dies at 30%, you have *complete* coverage
of your highest-value verticals rather than a partial map of everywhere.
Put your best-converting types at the top of business_types.csv.

**Blocking is treated as a first-class outcome.** Google will throttle a single
IP at this volume. A CAPTCHA raises ``BlockedError``; four consecutive empty
searches is treated as a soft block. Either way the runner backs off
exponentially, recycles the browser, and retries — and if it still can't get
through, it stops cleanly with everything resumable rather than grinding out
hundreds of empty results.

**Pacing.** A jittered delay between searches plus a longer break every N
searches. The defaults are deliberately unhurried; going faster is how you get
blocked.

**The fast provider.** ``provider="fast"`` (fastmaps.py) reads the search
response over plain HTTP instead of driving a browser: one request per 20
businesses, no detail pages. It runs ``concurrency`` searches at once under one
shared request-rate cap (``rate`` per second), keeps paging a search while the
pages keep turning up businesses with no website (``more_if_no_site``), and
all workers stop together when Google pushes back.
"""

from __future__ import annotations

import asyncio
import csv
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from collections import deque

from . import geo
from .config import settings
from .scraper import BlockedError, GoogleMapsScraper
from .store import BatchStore, task_key

ProgressFn = Callable[[str, Dict[str, Any]], Awaitable[None]]

# Column names we'll accept in the input CSVs, so you can hand it a file
# exported from anywhere without renaming headers first.
TOWN_COLUMNS = ("town", "towns", "location", "locations", "place", "places",
                "suburb", "suburbs", "city", "cities", "area", "name")
TYPE_COLUMNS = ("business_type", "business type", "type", "types", "keyword",
                "keywords", "query", "category", "niche", "name")
PRIORITY_COLUMNS = ("priority", "rank", "order", "weight")


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------
def _sniff_rows(path: Path) -> List[List[str]]:
    text = Path(path).read_text(encoding="utf-8-sig")
    rows = [r for r in csv.reader(text.splitlines()) if any((c or "").strip() for c in r)]
    return [[(c or "").strip() for c in r] for r in rows]


def load_input_list(path: Path, kind: str = "town") -> List[str]:
    """Read a one-column-ish CSV of towns or business types.

    Deliberately forgiving: works with a header row (any of the accepted
    names), with no header at all, with extra columns present, and with
    ``#`` comment lines. Preserves order, drops duplicates.
    """
    rows = _sniff_rows(path)
    if not rows:
        return []

    wanted = TOWN_COLUMNS if kind == "town" else TYPE_COLUMNS
    header = [c.lower() for c in rows[0]]
    col = 0
    prio_col: Optional[int] = None
    body = rows

    if any(h in wanted for h in header):
        col = next(i for i, h in enumerate(header) if h in wanted)
        prio_col = next((i for i, h in enumerate(header) if h in PRIORITY_COLUMNS), None)
        body = rows[1:]

    items: List[tuple] = []
    seen = set()
    for i, row in enumerate(body):
        if col >= len(row):
            continue
        value = row[col].strip()
        if not value or value.startswith("#"):
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        prio = i
        if prio_col is not None and prio_col < len(row):
            try:
                prio = int(float(row[prio_col]))
            except (TypeError, ValueError):
                prio = i
        items.append((prio, i, value))

    items.sort(key=lambda t: (t[0], t[1]))
    return [v for _, _, v in items]


def load_pairs(path: Path) -> List[Dict[str, str]]:
    """Read a CSV that already contains explicit town+type pairs.

    Use this instead of the cross product when you want a hand-picked list
    (e.g. only cafés in the CBD but every trade in the regions).
    """
    rows = _sniff_rows(path)
    if not rows:
        return []
    header = [c.lower() for c in rows[0]]
    t_col = next((i for i, h in enumerate(header) if h in TOWN_COLUMNS), None)
    b_col = next((i for i, h in enumerate(header) if h in TYPE_COLUMNS), None)
    if t_col is None or b_col is None:
        raise ValueError(
            f"{path.name} needs both a town column {TOWN_COLUMNS[:4]} and a "
            f"business-type column {TYPE_COLUMNS[:4]}."
        )
    out, seen = [], set()
    for row in rows[1:]:
        if t_col >= len(row) or b_col >= len(row):
            continue
        town, btype = row[t_col].strip(), row[b_col].strip()
        if not town or not btype or town.startswith("#"):
            continue
        k = task_key(town, btype)
        if k in seen:
            continue
        seen.add(k)
        out.append({"town": town, "business_type": btype})
    return out


# ---------------------------------------------------------------------------
# Config + task list
# ---------------------------------------------------------------------------
@dataclass
class BatchConfig:
    name: str = "batch"
    towns: List[str] = field(default_factory=list)
    business_types: List[str] = field(default_factory=list)
    pairs: List[Dict[str, str]] = field(default_factory=list)

    max_results: int = 20          # per individual search
    provider: str = "playwright"   # "playwright" | "places_api" | "fast"
    order: str = "type"            # "type" | "town" | "as-listed"

    # fast provider only
    concurrency: int = 1           # searches in flight at once
    rate: float = 1.5              # requests per second, across all of them
    more_if_no_site: int = 3       # fetch the next page only if this page had
                                   # this many no-website leads with a phone (0 = always)

    # pacing — the defaults assume a big overnight run on one IP
    pace_seconds: float = 8.0
    pace_jitter: float = 0.4       # ±40%
    long_break_every: int = 40
    long_break_seconds: float = 180.0
    recycle_every: int = 50        # relaunch the browser this often

    # where — appended to every search, and results elsewhere are dropped
    state: str = settings.SEARCH_STATE
    country: str = settings.SEARCH_COUNTRY

    # block handling
    block_threshold: int = 4       # consecutive empty searches == suspicious
    block_backoff: Sequence[float] = (300.0, 900.0, 1800.0)  # 5m, 15m, 30m

    def tasks(self) -> List[Dict[str, str]]:
        if self.pairs:
            return list(self.pairs)
        out: List[Dict[str, str]] = []
        if self.order == "town":
            for town in self.towns:
                for btype in self.business_types:
                    out.append({"town": town, "business_type": btype})
        else:  # "type" (default) and "as-listed" both lead with business type
            for btype in self.business_types:
                for town in self.towns:
                    out.append({"town": town, "business_type": btype})
        return out

    def to_dict(self) -> Dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items()}
        d["block_backoff"] = list(self.block_backoff)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BatchConfig":
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


def build_query(business_type: str, town: str, state: str = "", country: str = "") -> str:
    """'plumber in Portland, VIC, Australia'.

    Without the state and country Google resolves ambiguous names abroad
    (Portland → Oregon, Torquay → Devon). A town that already names its own
    region ("Albury, NSW") keeps it.
    """
    where = town.strip()
    if state and "," not in where:
        where += f", {state.strip()}"
    if country and country.strip().lower() not in where.lower():
        where += f", {country.strip()}"
    return f"{business_type.strip()} in {where}"


_AU_ADDRESS = re.compile(r"\b(VIC|NSW|QLD|SA|WA|TAS|ACT|NT)(\s+\d{4}\b|\s*$)")
_CALLING_CODES = {"australia": "61", "sri lanka": "94", "new zealand": "64", "united kingdom": "44",
                  "united states": "1", "canada": "1"}
_COUNTRIES = {"australia", "united states", "usa", "united kingdom", "uk", "canada",
              "new zealand", "ireland", "south africa", "italy", "india", "philippines",
              "singapore", "malaysia", "germany", "france", "spain", "netherlands", "sri lanka"}


def in_country(lead: Dict[str, Any], country: str) -> bool:
    """False when a result is clearly outside ``country``.

    Google appends the country to addresses, so a different trailing country
    (or, for Australia, no "VIC 3220"-style state + postcode) means abroad.
    With no address, a foreign "+44…" phone number gives it away.
    """
    want = (country or "").strip().lower()
    if not want:
        return True
    if want == "sri lanka":
        lat, lng = lead.get("lat"), lead.get("lng")
        if lat is not None and lng is not None and not (5.8 <= lat <= 9.9 and 79.5 <= lng <= 82.0):
            return False
        phone = re.sub(r"[^\d+]", "", lead.get("phone") or "")
        if phone.startswith("+") and not phone.startswith("+94"):
            return False
    address = (lead.get("address") or "").strip()
    if address:
        if address.lower().endswith(want):
            return True
        if want == "australia":
            return bool(_AU_ADDRESS.search(address))
        return address.rsplit(",", 1)[-1].strip().lower() not in _COUNTRIES
    phone = re.sub(r"[^\d+]", "", lead.get("phone") or "")
    code = _CALLING_CODES.get(want)
    if phone.startswith("+") and code:
        return phone.startswith("+" + code)
    return True


def estimate_seconds(n_tasks: int, cfg: BatchConfig) -> float:
    """Rough wall-clock estimate, used for the ETA in the dashboard."""
    if cfg.provider == "fast":
        pages = 1.0 if cfg.max_results <= 20 else 1.4
        breaks = (n_tasks / cfg.long_break_every) * cfg.long_break_seconds if cfg.long_break_every else 0
        return n_tasks * pages / max(0.05, cfg.rate) + breaks
    per_search = 12.0 + cfg.max_results * 1.6 / max(1, settings.CONCURRENCY)
    pacing = cfg.pace_seconds
    breaks = (n_tasks / max(1, cfg.long_break_every)) * cfg.long_break_seconds
    return n_tasks * (per_search + pacing) + breaks


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
class BatchRunner:
    def __init__(
        self,
        store: BatchStore,
        config: BatchConfig,
        on_progress: Optional[ProgressFn] = None,
    ) -> None:
        self.store = store
        self.cfg = config
        self.on_progress = on_progress
        self._scraper: Optional[Any] = None   # GoogleMapsScraper or FastMapsClient
        self._scraper_lock = asyncio.Lock()
        self._since_recycle = 0
        self._consecutive_empty = 0
        self._block_hits = 0
        self._block_lock = asyncio.Lock()
        self._last_backoff_end = 0.0
        self._gate = asyncio.Event()          # cleared while every worker should wait
        self._gate.set()
        self._durations: List[float] = []
        self._last_checkpoint = 0.0
        self._stop: Optional[str] = None      # "paused" | "blocked" once workers should stop
        self._no_site = sum(1 for l in store.leads if not l.get("has_website"))
        self._hot = sum(1 for l in store.leads if l.get("grade") == "Hot")
        self.cancelled = False

    @property
    def _fast(self) -> bool:
        return self.cfg.provider == "fast"

    @property
    def _workers(self) -> int:
        return max(1, self.cfg.concurrency) if self._fast else 1

    async def _emit(self, event: str, **data: Any) -> None:
        if self.on_progress:
            await self.on_progress(event, data)

    # ------------------------------------------------------------- browser
    async def _ensure_browser(self) -> Any:
        async with self._scraper_lock:
            if self._scraper is None:
                if self._fast:
                    from .fastmaps import FastMapsClient

                    self._scraper = FastMapsClient(rate=self.cfg.rate)
                else:
                    self._scraper = GoogleMapsScraper(on_progress=None)
                await self._scraper.__aenter__()
                self._since_recycle = 0
            return self._scraper

    async def _recycle_browser(self, reason: str = "scheduled") -> None:
        if self._scraper is not None:
            try:
                await self._scraper.__aexit__(None, None, None)
            except Exception:
                pass
            self._scraper = None
        await self._emit("status", message=f"Recycled the {'HTTP client' if self._fast else 'browser'} "
                                           f"({reason}).")
        await asyncio.sleep(random.uniform(2.0, 5.0))

    def _checkpoint(self, force: bool = False) -> None:
        """Manifest + counters. Every search is already fsync-ed to the JSONL
        files, so with many fast searches a second, re-counting 100k leads
        after each one is wasted work: at most every 5 seconds."""
        now = time.monotonic()
        if force or not self._fast or now - self._last_checkpoint >= 5.0:
            self.store.checkpoint()
            self._last_checkpoint = now

    # --------------------------------------------------------------- pacing
    async def _pace(self, index: int, total: int) -> None:
        if index >= total - 1:
            return
        if self.cfg.long_break_every and (index + 1) % self.cfg.long_break_every == 0:
            delay = self.cfg.long_break_seconds * random.uniform(0.85, 1.15)
            await self._emit(
                "status",
                message=f"Long break — pausing {delay / 60:.1f} min to stay under "
                        f"Google's radar.",
            )
            self._gate.clear()   # every worker sits this one out
            try:
                await asyncio.sleep(delay)
            finally:
                self._gate.set()
            return
        base = self.cfg.pace_seconds
        if base <= 0:
            return
        jitter = base * self.cfg.pace_jitter
        await asyncio.sleep(max(0.5, random.uniform(base - jitter, base + jitter)))

    def _eta_seconds(self, remaining: int) -> float:
        if not self._durations:
            return estimate_seconds(remaining, self.cfg)
        recent = self._durations[-20:]
        avg = sum(recent) / len(recent)
        breaks = ((remaining / self.cfg.long_break_every) * self.cfg.long_break_seconds
                  if self.cfg.long_break_every else 0)
        return remaining * (avg + self.cfg.pace_seconds) / self._workers + breaks

    # ------------------------------------------------------------ blocking
    async def _handle_block(self, note: str, since: float) -> bool:
        """Back off and recycle. Returns False when we should give up.

        With several workers, the first to see the block does the waiting
        and the rest just retry once it's over (``since`` is when their own
        request started)."""
        async with self._block_lock:
            if self._last_backoff_end > since:
                return True
            if self._block_hits >= len(self.cfg.block_backoff):
                await self._emit(
                    "status",
                    message=f"Still blocked after {self._block_hits} back-offs. Stopping "
                            f"— everything so far is saved, resume when your IP cools "
                            f"down or add SCRAPER_PROXY.",
                )
                return False
            wait = self.cfg.block_backoff[self._block_hits]
            self._block_hits += 1
            self._gate.clear()
            try:
                await self._emit(
                    "blocked",
                    message=f"{note} Backing off {wait / 60:.0f} min "
                            f"(attempt {self._block_hits}/{len(self.cfg.block_backoff)}).",
                )
                self.store.save_manifest(status="backing-off")
                if self._fast:
                    # Come back gentler: the rest of the run goes slower.
                    self.cfg.rate = max(0.2, self.cfg.rate / 1.5)
                await self._recycle_browser("blocked")
                await asyncio.sleep(wait)
            finally:
                self._consecutive_empty = 0
                self._last_backoff_end = time.monotonic()
                self._gate.set()
            return True

    # ------------------------------------------------------------------ run
    async def run(self, resume: bool = True) -> Dict[str, Any]:
        all_tasks = self.cfg.tasks()
        self.store.manifest.setdefault("counts", {})["tasks_total"] = len(all_tasks)

        pending = deque(
            t for t in all_tasks
            if not (resume and self.store.is_done(t["town"], t["business_type"]))
        )
        skipped = len(all_tasks) - len(pending)
        self._total, self._skipped, self._n_pending, self._started = (
            len(all_tasks), skipped, len(pending), 0)

        self.store.checkpoint(status="running", config=self.cfg.to_dict())
        await self._emit(
            "start",
            total=len(all_tasks),
            pending=len(pending),
            skipped=skipped,
            eta_seconds=round(estimate_seconds(len(pending), self.cfg)),
            message=(f"Resuming — {skipped} searches already done, {len(pending)} to go."
                     if skipped else f"Starting {len(pending)} searches.")
                    + (f" {self._workers} at a time, ≤{self.cfg.rate:g} requests/s."
                       if self._fast else ""),
        )

        status = "done"
        try:
            if self._workers == 1:
                # Awaited directly, not as a task, so a KeyboardInterrupt from
                # inside a search unwinds through here like it always has.
                await self._worker(pending)
            else:
                await asyncio.gather(*(self._worker(pending) for _ in range(self._workers)))
            status = self._stop or ("paused" if pending else "done")
        except asyncio.CancelledError:
            status = "paused"
            raise
        finally:
            await self._recycle_browser("finished")
            self.store.checkpoint(status=status)
            csv_path = self.store.export_csv(no_website_only=False)
            summary = self.store.summary()
            await self._emit(
                "finished",
                status=status,
                csv=str(csv_path),
                summary=summary,
                message=f"Batch {status}: {summary['counts']['leads_total']} unique leads, "
                        f"{summary['counts']['leads_no_website']} with no website.",
            )

        return self.store.summary()

    async def _worker(self, pending: deque) -> None:
        while pending and not self._stop:
            if self.cancelled:
                self._stop = "paused"
                break
            await self._gate.wait()
            if not pending or self._stop:
                break
            task = pending.popleft()
            index = self._started
            self._started += 1

            outcome = await self._run_task(task, index)
            if outcome == "retry":
                pending.appendleft(task)
                continue
            if outcome == "stop":
                break

            self._since_recycle += 1
            if (not self._fast and self.cfg.recycle_every
                    and self._since_recycle >= self.cfg.recycle_every):
                await self._recycle_browser()
            await self._pace(index, self._n_pending)

    async def _run_task(self, task: Dict[str, str], i: int) -> str:
        """One search, start to finish → "ok" | "retry" | "stop"."""
        town, btype = task["town"], task["business_type"]
        query = build_query(btype, town, self.cfg.state, self.cfg.country)
        started = time.monotonic()
        total, skipped = self._total, self._skipped

        await self._emit(
            "task_start",
            index=i, pending=self._n_pending, total=total,
            done=skipped + i, town=town, business_type=btype, query=query,
            eta_seconds=round(self._eta_seconds(self._n_pending - i)),
            message=f"[{skipped + i + 1}/{total}] {query}",
        )

        try:
            results = await self._search_one(query)
        except asyncio.CancelledError:
            self._stop = "paused"
            raise
        except BlockedError as exc:
            self.store.record_task(town, btype, query, "blocked", error=str(exc),
                                   seconds=time.monotonic() - started)
            self._checkpoint(force=True)
            if await self._handle_block(str(exc), started):
                # Retry this same task after the back-off.
                self.store.done_tasks.pop(task_key(town, btype), None)
                return "retry"
            self._stop = "blocked"
            return "stop"
        except Exception as exc:  # noqa: BLE001
            self.store.record_task(town, btype, query, "failed",
                                   error=f"{type(exc).__name__}: {exc}",
                                   seconds=time.monotonic() - started)
            self._checkpoint()
            await self._emit("task_error", query=query, message=f"{query} — {exc}")
            return "ok"

        elapsed = time.monotonic() - started
        self._durations.append(elapsed)

        found = [b.to_dict() for b in results]
        dicts = [d for d in found
                 if in_country(d, self.cfg.country)
                 and (self.cfg.country.lower() != "australia" or geo.in_australia(d.get("lat"), d.get("lng")))
                 and d.get("closed") != "permanently"]
        abroad = len(found) - len(dicts)
        new = self.store.add_leads(dicts, town, btype)
        added = self.store.leads[len(self.store.leads) - new:] if new else []
        self._no_site += sum(1 for l in added if not l.get("has_website"))
        self._hot += sum(1 for l in added if l.get("grade") == "Hot")
        self.store.record_task(town, btype, query, "done", found=len(dicts),
                               new_leads=new, seconds=elapsed)
        self._checkpoint()

        # Soft-block detection: real towns don't return nothing four times in
        # a row. The fast provider sees blocks directly (Google answers with a
        # page instead of data), and a small town genuinely can have no
        # concreters, so it only treats a long run of empties as a block.
        threshold = self.cfg.block_threshold if not self._fast else max(30, self.cfg.block_threshold)
        if not dicts:
            self._consecutive_empty += 1
            if self._consecutive_empty >= threshold:
                if await self._handle_block(
                    f"{self._consecutive_empty} empty searches in a row — likely throttled.",
                    started,
                ):
                    return "ok"
                self._stop = "blocked"
                return "stop"
        else:
            self._consecutive_empty = 0
            self._block_hits = 0

        counts = self.store.manifest.get("counts", {})
        await self._emit(
            "task_done",
            index=i, done=skipped + i + 1, total=total,
            town=town, business_type=btype, query=query,
            found=len(dicts), new_leads=new,
            leads_total=len(self.store.leads),
            leads_no_website=self._no_site,
            grades=dict(counts.get("grades", {}), Hot=self._hot),
            eta_seconds=round(self._eta_seconds(self._n_pending - i - 1)),
            message=f"{query} — {len(dicts)} found, {new} new"
                    + (f", {abroad} outside {self.cfg.country} or closed dropped" if abroad else ""),
        )
        return "ok"

    async def _search_one(self, query: str) -> List[Any]:
        if self.cfg.provider == "places_api":
            from .places_api import search_places

            return await search_places(query, self.cfg.max_results)
        scraper = await self._ensure_browser()
        if self._fast:
            scraper.limiter.interval = 1.0 / max(0.05, self.cfg.rate)
            need = self.cfg.more_if_no_site

            def keep_going(page: List[Any]) -> bool:
                return sum(1 for b in page if not b.has_website and b.phone) >= need

            return await scraper.search(query, self.cfg.max_results,
                                        keep_going=keep_going if need else None)
        return await scraper.search(query, self.cfg.max_results)

    def cancel(self) -> None:
        self.cancelled = True
