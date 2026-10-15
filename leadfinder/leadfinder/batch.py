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
    provider: str = "playwright"   # "playwright" | "places_api"
    order: str = "type"            # "type" | "town" | "as-listed"

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
_CALLING_CODES = {"australia": "61", "new zealand": "64", "united kingdom": "44",
                  "united states": "1", "canada": "1"}
_COUNTRIES = {"australia", "united states", "usa", "united kingdom", "uk", "canada",
              "new zealand", "ireland", "south africa", "italy", "india", "philippines",
              "singapore", "malaysia", "germany", "france", "spain", "netherlands"}


def in_country(lead: Dict[str, Any], country: str) -> bool:
    """False when a result is clearly outside ``country``.

    Google appends the country to addresses, so a different trailing country
    (or, for Australia, no "VIC 3220"-style state + postcode) means abroad.
    With no address, a foreign "+44…" phone number gives it away.
    """
    want = (country or "").strip().lower()
    if not want:
        return True
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
        self._scraper: Optional[GoogleMapsScraper] = None
        self._since_recycle = 0
        self._consecutive_empty = 0
        self._block_hits = 0
        self._durations: List[float] = []
        self.cancelled = False

    async def _emit(self, event: str, **data: Any) -> None:
        if self.on_progress:
            await self.on_progress(event, data)

    # ------------------------------------------------------------- browser
    async def _ensure_browser(self) -> GoogleMapsScraper:
        if self._scraper is None:
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
        await self._emit("status", message=f"Recycled the browser ({reason}).")
        await asyncio.sleep(random.uniform(2.0, 5.0))

    # --------------------------------------------------------------- pacing
    async def _pace(self, index: int, total: int) -> None:
        if index >= total - 1:
            return
        base = self.cfg.pace_seconds
        jitter = base * self.cfg.pace_jitter
        delay = max(0.5, random.uniform(base - jitter, base + jitter))

        if self.cfg.long_break_every and (index + 1) % self.cfg.long_break_every == 0:
            delay = self.cfg.long_break_seconds * random.uniform(0.85, 1.15)
            await self._emit(
                "status",
                message=f"Long break — pausing {delay / 60:.1f} min to stay under "
                        f"Google's radar.",
            )
        await asyncio.sleep(delay)

    def _eta_seconds(self, remaining: int) -> float:
        if not self._durations:
            return estimate_seconds(remaining, self.cfg)
        recent = self._durations[-20:]
        avg = sum(recent) / len(recent)
        breaks = (remaining / max(1, self.cfg.long_break_every)) * self.cfg.long_break_seconds
        return remaining * (avg + self.cfg.pace_seconds) + breaks

    # ------------------------------------------------------------ blocking
    async def _handle_block(self, note: str) -> bool:
        """Back off and recycle. Returns False when we should give up."""
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
        await self._emit(
            "blocked",
            message=f"{note} Backing off {wait / 60:.0f} min "
                    f"(attempt {self._block_hits}/{len(self.cfg.block_backoff)}).",
        )
        self.store.save_manifest(status="backing-off")
        await self._recycle_browser("blocked")
        await asyncio.sleep(wait)
        self._consecutive_empty = 0
        return True

    # ------------------------------------------------------------------ run
    async def run(self, resume: bool = True) -> Dict[str, Any]:
        all_tasks = self.cfg.tasks()
        self.store.manifest.setdefault("counts", {})["tasks_total"] = len(all_tasks)

        pending = [
            t for t in all_tasks
            if not (resume and self.store.is_done(t["town"], t["business_type"]))
        ]
        skipped = len(all_tasks) - len(pending)

        self.store.checkpoint(status="running", config=self.cfg.to_dict())
        await self._emit(
            "start",
            total=len(all_tasks),
            pending=len(pending),
            skipped=skipped,
            eta_seconds=round(estimate_seconds(len(pending), self.cfg)),
            message=(f"Resuming — {skipped} searches already done, {len(pending)} to go."
                     if skipped else f"Starting {len(pending)} searches."),
        )

        status = "done"
        try:
            for i, task in enumerate(pending):
                if self.cancelled:
                    status = "paused"
                    break

                town, btype = task["town"], task["business_type"]
                query = build_query(btype, town, self.cfg.state, self.cfg.country)
                started = time.monotonic()

                await self._emit(
                    "task_start",
                    index=i, pending=len(pending), total=len(all_tasks),
                    done=skipped + i, town=town, business_type=btype, query=query,
                    eta_seconds=round(self._eta_seconds(len(pending) - i)),
                    message=f"[{skipped + i + 1}/{len(all_tasks)}] {query}",
                )

                try:
                    results = await self._search_one(query)
                except asyncio.CancelledError:
                    status = "paused"
                    raise
                except BlockedError as exc:
                    self.store.record_task(town, btype, query, "blocked", error=str(exc),
                                           seconds=time.monotonic() - started)
                    self.store.checkpoint()
                    if await self._handle_block(str(exc)):
                        # Retry this same task after the back-off.
                        self.store.done_tasks.pop(task_key(town, btype), None)
                        pending.insert(i + 1, task)
                        continue
                    status = "blocked"
                    break
                except Exception as exc:  # noqa: BLE001
                    self.store.record_task(town, btype, query, "failed",
                                           error=f"{type(exc).__name__}: {exc}",
                                           seconds=time.monotonic() - started)
                    self.store.checkpoint()
                    await self._emit("task_error", query=query, message=f"{query} — {exc}")
                    await self._pace(i, len(pending))
                    continue

                elapsed = time.monotonic() - started
                self._durations.append(elapsed)

                found = [b.to_dict() for b in results]
                dicts = [d for d in found if in_country(d, self.cfg.country)]
                abroad = len(found) - len(dicts)
                new = self.store.add_leads(dicts, town, btype)
                self.store.record_task(town, btype, query, "done", found=len(dicts),
                                       new_leads=new, seconds=elapsed)
                self.store.checkpoint()

                # Soft-block detection: real towns don't return nothing four
                # times in a row.
                if not dicts:
                    self._consecutive_empty += 1
                    if self._consecutive_empty >= self.cfg.block_threshold:
                        if await self._handle_block(
                            f"{self._consecutive_empty} empty searches in a row — "
                            f"likely throttled."
                        ):
                            continue
                        status = "blocked"
                        break
                else:
                    self._consecutive_empty = 0
                    self._block_hits = 0

                counts = self.store.manifest.get("counts", {})
                await self._emit(
                    "task_done",
                    index=i, done=skipped + i + 1, total=len(all_tasks),
                    town=town, business_type=btype, query=query,
                    found=len(dicts), new_leads=new,
                    leads_total=counts.get("leads_total", 0),
                    leads_no_website=counts.get("leads_no_website", 0),
                    grades=counts.get("grades", {}),
                    eta_seconds=round(self._eta_seconds(len(pending) - i - 1)),
                    message=f"{query} — {len(dicts)} found, {new} new"
                            + (f", {abroad} outside {self.cfg.country} dropped" if abroad else ""),
                )

                self._since_recycle += 1
                if self.cfg.recycle_every and self._since_recycle >= self.cfg.recycle_every:
                    await self._recycle_browser()

                await self._pace(i, len(pending))

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

    async def _search_one(self, query: str) -> List[Any]:
        if self.cfg.provider == "places_api":
            from .places_api import search_places

            return await search_places(query, self.cfg.max_results)
        scraper = await self._ensure_browser()
        return await scraper.search(query, self.cfg.max_results)

    def cancel(self) -> None:
        self.cancelled = True
