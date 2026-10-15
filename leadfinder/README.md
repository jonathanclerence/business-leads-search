# Lead Finder — Google Maps business scraper & lead exporter

Enter a **business type** and a **location**, get every matching business on
Google Maps with its **name, address, phone, website (or lack of one), rating
and review count** — in a live dashboard you can filter, sort and export to
CSV or straight into Google Sheets.

Built for finding businesses that *don't* have a website: those rows are
flagged, counted, scored for how well they'd suit a website-plus-booking
pitch, and one checkbox away from being your entire export.

Two ways to use it:

- **Single search** — one business type, one location, results in a live table.
- **[Bulk batch & tracker](#bulk-batch--lead-tracker)** — feed it a CSV of
  towns and a CSV of business types, and it runs every combination
  automatically, deduplicates across all of them, ranks the results, and hands
  you one CSV for your sales team.

```
┌─ Business type ──┐ ┌─ Location ─────────┐ ┌ Max ┐ ┌────────┐
│ a/c repair       │ │ Sydney, Australia  │ │ 50  │ │ Search │
└──────────────────┘ └────────────────────┘ └─────┘ └────────┘

  BUSINESSES FOUND    NO WEBSITE 🎯    WITH WEBSITE    HAS PHONE
        50                  17              33            44
```

---

## Table of contents

1. [Quick start](#quick-start)
2. [Bulk batch & lead tracker](#bulk-batch--lead-tracker) ← **the CSV-in/CSV-out workflow**
   - [Sales pipeline: previews, calls, stages](#sales-pipeline-previews-calls-stages)
3. [Lead scoring](#lead-scoring)
4. [How it works](#how-it-works)
5. [The two data engines](#the-two-data-engines)
6. [Exporting](#exporting)
7. [Configuration reference](#configuration-reference)
8. [Project layout](#project-layout)
9. [Tests](#tests)
10. [When Google changes their HTML](#when-google-changes-their-html)
11. [Troubleshooting](#troubleshooting)
12. [What changed from the old version](#what-changed-from-the-old-version)
13. [Legal & rate-limiting notes](#legal--rate-limiting-notes)

---

## Quick start

**Requirements:** Python 3.9 or newer. Nothing else — no API key, no billing
account, no Node.js.

### The one-liner

```bash
cd leadfinder
./run.sh
```

`run.sh` creates a virtualenv, installs the Python packages, downloads the
Chromium build Playwright drives (~150 MB, first run only), copies `.env`
from the template, and starts the server.

Then open **<http://localhost:5000>**.

### Or do it manually

```bash
cd leadfinder

python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

pip install -r requirements.txt
python -m playwright install chromium   # one-time browser download

cp .env.example .env                 # optional — defaults work as-is
python app.py
```

Open <http://localhost:5000>, type `a/c repair` + `Sydney, Australia`, pick
**50**, hit **Search**. Rows stream into the table as each listing is read.

> **First search is the slow one.** Chromium cold-starts in ~3 seconds.
> After that, budget roughly **1–2 seconds per listing** — 50 results in about
> a minute with the default concurrency of 4.

---

## Bulk batch & lead tracker

Searching one town at a time doesn't scale. To cover Victoria you'd be typing
"pet groomers in Geelong", "salons in Geelong", "pet groomers in Highton" by
hand for a week. The batch runner does the cross-referencing for you.

**Two CSVs in → one scored, deduplicated CSV out.**

```
towns.csv          business_types.csv            leads.csv
┌──────────┐       ┌──────────────┐              ┌───────────────────────────┐
│ Geelong  │       │ hair salon   │              │ Score Grade Business Phone│
│ Highton  │   ×   │ pet grooming │  ────────►   │  100   Hot  Snip &… 03 52…│
│ Belmont  │       │ cafe         │   9 searches │   98   Hot  Waggy … 03 52…│
└──────────┘       └──────────────┘              │   62  Warm  Bean T… 03 52…│
   3 towns            3 types                    └───────────────────────────┘
                                                  13 unique · 4 dupes collapsed
```

### Start here

A sanity check before you commit a night to it — 8 searches, about 5 minutes:

```bash
python batch_cli.py run --pairs data/starter_geelong.csv --name geelong-test
```

If that returns leads, you're in business.

### From the dashboard

Open the **Bulk batch & tracker** tab. Pick your towns CSV and business-types
CSV, hit **Preview plan** — it tells you how many searches that is and roughly
how long it'll take *before* you start — then **Start batch**. Progress streams
live, and the lead tracker below fills in as results arrive.

### From the terminal (better for long runs)

A 500-search sweep runs for hours and shouldn't depend on a browser tab
staying open. Use the CLI, ideally under `screen` or `tmux`:

```bash
# See the cost first — this scrapes nothing
python batch_cli.py run --towns data/towns_victoria.csv \
                        --types data/business_types.csv --dry-run

# The real run, trimmed to something sane
python batch_cli.py run --towns data/towns_victoria.csv \
                        --types data/business_types.csv \
                        --max-towns 40 --max-types 12 --name victoria-sweep

python batch_cli.py list              # all batches
python batch_cli.py status latest     # progress + best towns/types so far
python batch_cli.py resume latest     # pick up exactly where it stopped
python batch_cli.py export latest --no-website --min-score 78 -o hot-leads.csv
```

`Ctrl-C` once finishes the search in flight and saves cleanly; twice force-quits.

### The input files

Both shipped files are starting points — **delete rows freely**. The full
Victoria list is 156 towns × 73 types = **11,388 searches ≈ 100 hours**. That
is not a plan; it's a warning the tool will show you.

| File | What it is |
|---|---|
| `data/towns_victoria.csv` | 156 Victorian towns and suburbs — regional centres, their suburbs, coastal and rural towns. Has a `priority` column controlling run order and a `region` column for your own slicing. |
| `data/business_types.csv` | 73 business types ranked by how well they fit a website-plus-booking pitch. Priority 1 is where the money is. |
| `data/starter_geelong.csv` | 8 hand-picked pairs. Run this first. |

The parser is deliberately forgiving: header row or no header row, any of
`town` / `suburb` / `location` / `city` (or `business_type` / `type` /
`keyword` / `niche`), extra columns ignored, `#` comment lines skipped,
Excel BOMs handled, duplicates dropped. Or upload your own from the dashboard.

A CSV with **both** a town and a business_type column is treated as an explicit
pair list instead — use that when you want a hand-picked set rather than a full
cross product.

### Why it survives a 6-hour run

You asked for files rather than a database. Files can still be crash-safe, and
at this scale they have to be:

- **Every completed search is `fsync`-ed to disk immediately.** A crash at hour
  six costs you the one search that was in flight, not the night.
- **Resume is exact.** `tasks.jsonl` records which town/type pairs finished;
  resume skips them. Nothing is re-scraped, nothing is lost.
- **A half-written final line is skipped on load** rather than poisoning the
  file — that's the classic crash artifact, and it's tested for.
- **Type-major run order.** It finishes every town for business type #1 before
  starting type #2. So an interrupted run leaves you *complete* coverage of
  your best-converting verticals rather than a partial map of everywhere. Put
  your best types at the top of `business_types.csv`.
- **One browser for the whole run**, recycled every 50 searches. Launching
  Chromium per search would add 25 minutes of pure startup to a 500-search sweep.

Everything lives in `batches/<timestamp>-<name>/` as plain text you can `grep`,
`wc -l`, `tail -f`, or open in a text editor:

```
batches/20260820-1231-victoria-sweep/
  manifest.json    config + live counters
  tasks.jsonl      one line per finished search — the resume log
  leads.jsonl      one line per unique business — the data
  leads.csv        the sales hand-off, regenerated on export
```

### Deduplication (the thing that saves your reps' time)

Highton and Belmont are Geelong suburbs, so Google returns overlapping results
for all three. Without dedupe your reps ring the same salon three times and
sound like idiots.

Every lead is keyed on its Google place id (falling back to a normalised
name+address). The first sighting wins; later ones increment a **Times Seen**
counter and append to **Also Found In**. A business that keeps surfacing across
searches is usually a bigger, more prominent operator — that column is a signal,
not noise.

### Blocking

Google will throttle a single IP at this volume. The runner treats that as a
first-class outcome rather than grinding out hundreds of empty results:

- A CAPTCHA page raises immediately instead of returning "no results".
- Four consecutive empty searches is treated as a soft block.
- Either way it backs off 5 → 15 → 30 minutes, recycles the browser, and
  retries. If it still can't get through it stops cleanly, and everything is
  resumable once your IP cools down.

To go faster or further: raise `--pace`, lower `--max-results`, split across
nights, or set `SCRAPER_PROXY` in `.env`.

---

## Sales pipeline: previews, calls, stages

Turns the no-website leads into a call list with a ready-made website preview
for each one, hosted at `https://www.dunous.com/previewsite/<slug>`, and tracks
every lead from *New* to *Website live*.

```bash
.venv/bin/python -m pipeline import          # batches/*/leads.csv → clean list + tracker
.venv/bin/python -m pipeline publish --grade Hot --limit 100 --wait
.venv/bin/python -m pipeline coverage        # what's been searched, by region
./run.sh                                     # then open http://localhost:5000/pipeline
```

- **Clean list:** `batches/clean/au-no-website.csv` — Australian businesses with
  no website and a phone number, de-duplicated, best score first, with each
  lead's preview URL and stage. Rewritten by every `import`.
- **Tracker:** `http://localhost:5000/pipeline` — call queue, personalised call
  script and SMS, one-click call logging, stages, follow-ups, notes, prices,
  region coverage and the sales playbook. Data lives in `batches/pipeline.db`.
- **Publish:** renders a page per lead (`pipeline/templates/site.html.j2`, copy
  in `pipeline/content.py`) into the marketing-site repo's
  `public/previewsite-pages/`, commits from a separate worktree
  (`../.marketing-site-publish`) and pushes to `PUBLISH_BRANCH` (default
  `main`). Your own marketing-site checkout is never touched. Leads marked *Not
  interested*, *Do not contact* or *Website live* lose their preview on the
  next publish.
- **Stages:** New → Preview created → Preview live → Contacted → Follow up →
  Interested → Invoice sent → Payment received → Domain chosen → Site hosted →
  Website live (plus Not interested / Do not contact).
- **Handover:** `python -m pipeline export-site <slug>` writes the finished site
  (no preview bar) to `exports/sites/<slug>/`, ready to upload to the client's
  own Cloudflare Pages.

`python tests/test_sales_pipeline.py` runs the offline tests.

## Lead scoring

Every lead gets a **0-100 booking-fit score** and a grade — Hot, Warm, Cool,
Cold — so your reps start at the top of the file instead of working
alphabetically through 4,000 rows.

The key design decision: **category fit gates the opportunity rather than just
adding to it.** If "no website" were a flat +40, a supermarket with no website
would outrank a hair salon. That's exactly backwards — the pitch doesn't apply
to a supermarket at all.

```
score = opportunity × fit   (max 45)   no website, AND the pitch applies
      + contactability      (max 20)   is there a phone number to ring
      + credibility         (max 20)   reviews + rating: real, busy, solvent
      + booking bonus × fit (max 15)   appointment-driven verticals

      ...then ×0.8 with no phone, because a lead your rep can't dial
         is barely a lead
```

`fit` runs from **1.00** (hair salon — the appointment book *is* the business)
through **0.85** (mechanic, plumber — books jobs) and **0.45** (café —
reservations aren't core) down to **0.12** (supermarket, real estate).

How that plays out:

| Lead | Score | Grade |
|---|---|---|
| Pet groomer, no website, phone, 180 reviews, 4.9★ | 98 | Hot |
| Hair salon, no website, phone, 12 reviews | 90 | Hot |
| Auto repair, no website, phone, 90 reviews | 82 | Hot |
| Café, no website, phone, 300 reviews, 4.5★ | 62 | Warm |
| Hair salon that already **has** a website, 200 reviews | 61 | Warm |
| Hair salon, no website, **no phone** | 50 | Cool |
| Supermarket, no website, phone, 400 reviews | 44 | Cool |

Every lead also carries a **Why This Lead** string — *"no website ·
appointment-based · 180 reviews · 4.9★"* — so whoever picks up the phone knows
the angle before they dial.

**Tuning it for your own patch:** the taxonomy in `leadfinder/scoring.py` is
just a keyword → tier list. Add your verticals to `CATEGORY_TIERS`, adjust the
`FIT` numbers, and re-export — scores recompute on load.

### The sales CSV

20 columns, sorted best-first, with four blank ones your reps fill in:

```
Score · Grade · Business Name · Phone Number · Category · Full Address ·
Search Town · Search Business Type · Website Available? · Website URL ·
Rating · Review Count · Why This Lead · Google Maps URL · Times Seen ·
Also Found In · First Found · Status · Assigned To · Last Contacted · Notes
```

`Status` is pre-filled with `New`. Hand the file to your team, let them work it
in Google Sheets, and the columns are already there.

---

## How it works

A scrape takes 30 seconds to 3 minutes, which is far too long to hold an HTTP
request open. So the flow is asynchronous:

```
  Browser                    FastAPI                     Playwright
     │  POST /api/search        │                             │
     ├─────────────────────────►│  create job, return id      │
     │◄─────────────────────────┤  (instantly)                │
     │                          ├────────────────────────────►│ launch Chromium
     │  GET /api/stream/{id}    │                             │ open Maps search
     ├─────────────────────────►│                             │ dismiss consent
     │◄══ scrolling: 14 found ══┤◄────────────────────────────┤ scroll the feed
     │◄══ progress: 3/50 ═══════┤◄────────────────────────────┤ ┐ 4 tabs read
     │◄══ progress: 4/50 ═══════┤◄────────────────────────────┤ ┘ details at once
     │◄══ done: 50 results ═════┤◄────────────────────────────┤
     │                          │                             │
     │  POST /api/export/csv    │                             │
     ├─────────────────────────►│  → leads-....csv download   │
```

The scraper itself works in four steps:

1. **Open the search URL** `google.com/maps/search/<query>` and dismiss the EU
   cookie wall if it appears.
2. **Scroll the results panel** (`div[role="feed"]`) until it has enough cards
   or Google prints *"You've reached the end of the list."* Both a programmatic
   `scrollTop` jump and a real mouse-wheel event are used — some Maps builds
   only lazy-load in response to the latter.
3. **Harvest every `/maps/place/` link** out of the feed. Links are the most
   stable thing on the page; Google rewrites CSS class names constantly, but
   the URL scheme has held for years.
4. **Fan out.** Four worker tabs navigate straight to each place URL and read
   the detail panel. Navigating beats clicking-and-going-back — no lost scroll
   state, no stale element handles, and it parallelises cleanly.

Phone numbers and website URLs only exist on the detail panel, which is why
step 4 is unavoidable if you want those columns filled in.

### Anti-blocking measures

| Measure | Why |
|---|---|
| Real desktop Chrome user-agent | Playwright's default UA contains `HeadlessChrome` — the single easiest way to get flagged |
| `--disable-blink-features=AutomationControlled` | Removes the most-checked automation fingerprint |
| `navigator.webdriver` / `languages` / `plugins` patched pre-load | Standard headless tells |
| Realistic `Sec-Ch-Ua`, `Accept-Language`, viewport, timezone | Consistency across the fingerprint surface |
| Randomised 0.15–1.6 s pauses between actions | No metronome-regular request timing |
| Concurrency capped (default 4, max 10) | Sustained parallel hits are what actually triggers rate limits |
| Optional upstream proxy (`SCRAPER_PROXY`) | For high volume, rotate IPs |

If you still get a CAPTCHA: set `HEADLESS=false` in `.env`, solve it once by
hand, and Google will usually leave you alone for a while.

---

## The two data engines

Pick either one from the radio buttons under the search form.

|  | **Playwright scraper** (default) | **Google Places API (New)** |
|---|---|---|
| API key | none | required, billing account required |
| Cost | free | per-request, with a monthly free credit |
| Max results per query | unlimited (Maps typically caps a feed around 120) | **60** (3 pages × 20, Google's hard limit) |
| Speed | ~1–2 s per listing | ~1 s for all 60 |
| Reliability | depends on Google's HTML staying put | contractual, stable |
| Terms of Service | grey area — see [notes](#legal--rate-limiting-notes) | fully sanctioned |

Both engines emit the exact same record shape, so the dashboard, the CSV and
the Sheets export are identical either way.

### Setting up the Places API

1. <https://console.cloud.google.com> → create or select a project.
2. **APIs & Services → Library** → enable **"Places API (New)"**.
   ⚠️ The older product is just called *"Places API"* — that's a different
   thing and this app won't work with it.
3. **APIs & Services → Credentials → Create credentials → API key**.
4. Add it to `.env`:

   ```dotenv
   GOOGLE_MAPS_API_KEY=AIzaSy...
   ```

5. Restart the app. The **Google Places API** radio button becomes selectable.

**Restrict the key by IP address, not by HTTP referrer.** This key is used
server-side (from `leadfinder/places_api.py`), so a referrer restriction will
reject every request. This is also a real security improvement over the old
version of this project, where the key sat in client-side JavaScript and was
visible to anyone who opened DevTools.

The request uses a tight `X-Goog-FieldMask` so you only pay for the nine
fields the app actually displays — a wildcard field mask is the fastest way to
run up a Google bill.

**Need more than 60 results?** Split the search geographically — *"a/c repair
in Bondi"*, *"…in Parramatta"*, *"…in Chatswood"* — or use the scraper.

---

## Exporting

### Export CSV

Downloads whatever is currently visible in the table — **your filter and sort
are respected**, so tick *"Leads only (no website)"* first and you get a
leads-only file.

The file is UTF-8 **with a BOM** and CRLF line endings, which is what Excel
needs to open accented business names correctly on a double-click. It imports
into Google Sheets via **File → Import** without any fiddling.

If the backend is unreachable for any reason, the button falls back to
building the CSV in the browser, so the download always works.

### Copy (fastest route into a Google Sheet)

Puts tab-separated rows on your clipboard. Click an empty cell in a Google
Sheet and press ⌘V / Ctrl+V — the columns land in place. No API setup, no file
juggling. For most people this is the one to use.

### Push directly to Google Sheets

Creates a new spreadsheet (or appends a timestamped tab to an existing one)
via a service account.

1. In the same Google Cloud project, enable **Google Sheets API** *and*
   **Google Drive API**.
2. **IAM & Admin → Service Accounts → Create service account**.
3. Open it → **Keys → Add key → Create new key → JSON**. A file downloads.
4. Save it as `service_account.json` inside the `leadfinder/` folder, then set
   in `.env`:

   ```dotenv
   GOOGLE_SERVICE_ACCOUNT_FILE=./service_account.json
   GSHEET_SHARE_WITH=you@example.com
   ```

5. Restart the app and click **Google Sheets**.

Two modes:

- **Leave the URL field blank** → a new spreadsheet is created and shared with
  the address in `GSHEET_SHARE_WITH` (or whatever you type in the dialog).
- **Paste an existing spreadsheet URL** → a new timestamped worksheet tab is
  appended. You must first share that spreadsheet with the service account's
  `client_email` (it's in the JSON file) as an **Editor**, otherwise Google
  returns a permission error.

`service_account.json` is in `.gitignore`. Keep it that way — it's a private
key.

### Webhook alternative (Zapier / Make / Apps Script)

If you'd rather not deal with service accounts, POST the rows to a webhook.
The `/api/results/{job_id}` endpoint returns clean JSON:

```bash
curl -s localhost:5000/api/results/<job_id> \
  | jq '.items' \
  | curl -X POST -H 'Content-Type: application/json' -d @- \
      https://hooks.zapier.com/hooks/catch/XXXXXX/YYYYYY/
```

Point a Zapier/Make "Catch Hook" trigger at a *Create Spreadsheet Row* action
and you have the same result with zero credentials in this project.

---

## Configuration reference

Everything lives in `.env` (copy from `.env.example`). Every value is optional.

| Variable | Default | What it does |
|---|---|---|
| `HOST` | `127.0.0.1` | Bind address. Use `0.0.0.0` to reach it from another device on your LAN. |
| `PORT` | `5000` | Server port. |
| `HEADLESS` | `true` | `false` shows the Chromium window — essential for debugging and for solving a CAPTCHA by hand. |
| `SCRAPER_CONCURRENCY` | `4` | Detail tabs open at once. Higher is faster and more likely to get rate-limited. Capped at 10. |
| `SCRAPER_TIMEOUT_MS` | `30000` | Per-navigation timeout. |
| `SCRAPER_HL` / `SCRAPER_GL` | `en` / `us` | Maps language and region. Keep `en` — the end-of-list detection reads English text. |
| `SCRAPER_PROXY` | — | Upstream proxy, e.g. `http://user:pass@host:port`. |
| `PLAYWRIGHT_CHROMIUM_PATH` | — | Use a Chrome you already have instead of Playwright's download. |
| `GOOGLE_MAPS_API_KEY` | — | Enables the Places API engine. |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | — | Enables the Google Sheets button. |
| `GSHEET_SHARE_WITH` | — | Who new spreadsheets get shared with. |

### HTTP API

The dashboard is just a client for these — script against them if you like.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/search` | Start a single search → `{"job_id": "..."}` |
| `GET` | `/api/stream/{job_id}` | Server-Sent Events progress feed |
| `GET` | `/api/results/{job_id}` | Full JSON results |
| `POST` | `/api/cancel/{job_id}` | Stop a running job (partial results are kept) |
| `POST` | `/api/export/csv` | CSV download from posted rows or a job id |
| `POST` | `/api/export/sheets` | Push to Google Sheets |
| `GET` | `/api/batch/inputs` | CSVs available in `data/` |
| `POST` | `/api/batch/upload` | Upload a new input CSV |
| `POST` | `/api/batch/preview` | Search count + ETA, scrapes nothing |
| `POST` | `/api/batch/start` | Start a bulk batch |
| `GET` | `/api/batch/list` | All batches on disk |
| `GET` | `/api/batch/{id}` | One batch's summary + recent searches |
| `GET` | `/api/batch/stream/{id}` | Live batch progress (SSE) |
| `POST` | `/api/batch/{id}/resume` | Continue an interrupted batch |
| `POST` | `/api/batch/{id}/cancel` | Stop after the current search |
| `POST` | `/api/batch/{id}/leads` | Filtered, scored leads |
| `POST` | `/api/batch/{id}/export` | Sales CSV download |
| `GET` | `/api/config` | Which optional features are configured |
| `GET` | `/api/health` | Liveness check |

Only one batch runs at a time — two would compete for the same browser and get
you rate-limited faster.

Interactive docs are at **<http://localhost:5000/docs>** (FastAPI gives you
these for free).

```bash
# scriptable example
JOB=$(curl -s localhost:5000/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"dentists","location":"Leeds, UK","max_results":40}' | jq -r .job_id)

curl -N localhost:5000/api/stream/$JOB          # watch it work
curl -s localhost:5000/api/results/$JOB | jq .  # grab the data
```

---

## Project layout

```
leadfinder/
├── app.py                    FastAPI app: routes, job runner, exports
├── batch_cli.py              bulk runner for long/overnight sweeps
├── run.sh                    one-command setup + start
├── diagnose.py               selector health-check (see below)
├── requirements.txt
├── .env.example              every setting, documented
│
├── leadfinder/
│   ├── config.py             env-driven settings
│   ├── models.py             the Business record — the shared contract
│   ├── scraper.py            Playwright engine + in-page extraction JS
│   ├── places_api.py         Google Places API (New) engine
│   ├── jobs.py               in-memory job store + SSE stream
│   ├── batch.py              CSV cross-reference, pacing, block handling
│   ├── store.py              crash-safe append-only JSONL store
│   ├── scoring.py            booking-fit score + category taxonomy
│   └── exporters.py          CSV + gspread
│
├── data/                     batch inputs (edit these)
│   ├── towns_victoria.csv    156 Victorian towns and suburbs
│   ├── business_types.csv    73 types, ranked by booking-pitch fit
│   └── starter_geelong.csv   8 pairs — run this first
│
├── batches/                  one folder per run (created automatically)
├── templates/index.html      the entire dashboard (one file, two tabs)
├── static/tailwind.css       pre-compiled — no CDN, works offline
│
└── tests/
    ├── test_extraction.py    57 checks: parsing, CSV, HTTP
    ├── test_pipeline.py      19 checks: full scrape vs. a fake Maps server
    ├── test_batch.py         67 checks: crash/resume, dedupe, scoring, export
    └── fixtures/             HTML mirroring Google Maps' real markup
```

The UI is deliberately one file. Tailwind is **pre-compiled** into
`static/tailwind.css`, so there's no CDN request, no offline breakage, and no
*"cdn.tailwindcss.com should not be used in production"* console warning. If
you edit classes in `index.html`, run `./build_css.sh` (needs Node.js) to
regenerate it.

---

## Tests

```bash
source .venv/bin/activate
python tests/test_extraction.py    # parsing, CSV shape, HTTP contract
python tests/test_pipeline.py      # full scrape against a fake Maps server
python tests/test_batch.py         # crash/resume, dedupe, scoring, sales CSV
```

**143 checks, all offline, no Google quota.** `test_pipeline.py` and
`test_batch.py` spin up local servers that reproduce Maps' lazy-loading feed
and detail-panel markup, then run the real scraper against them — so scrolling,
link harvesting, the concurrent worker pool, dedupe, result ordering and the
SSE stream are all covered against real browser behaviour.

`test_batch.py` specifically covers the failure modes that would cost you a
night's work: it kills a batch mid-run, reopens it from disk, resumes, and
asserts that no search was repeated and no lead was lost. It also appends a
deliberately truncated JSON line to simulate a hard kill, and checks that the
store skips it instead of choking.

---

## When Google changes their HTML

They will, every few months. The symptom is always the same: rows come back
with **names but empty phone/address/website columns**.

Run the diagnostic:

```bash
python diagnose.py
python diagnose.py "dentists in Melbourne" --show   # watch it happen
```

It probes each selector against a live page and prints `LIVE` / `BROKEN` per
field, then saves screenshots and the raw HTML of a place page to `exports/`.
Fix whatever it flags in `JS_EXTRACT_PLACE` inside `leadfinder/scraper.py` —
it's one self-contained JS function with the selectors clearly labelled.

The selectors were chosen to be as durable as possible: they lean on
accessibility attributes (`data-item-id="address"`, `aria-label="Phone: …"`,
`role="feed"`) rather than CSS classes, because Google keeps those stable for
screen readers even when the visual markup is rewritten. Each field also has
at least one fallback selector.

---

## Troubleshooting

**`Executable doesn't exist at .../headless_shell`**
Playwright's browser wasn't downloaded. Run `python -m playwright install chromium`.

**Empty results, or a `sorry/index` URL**
Google served a CAPTCHA. Set `HEADLESS=false`, run the search, solve it once
by hand. Then lower `SCRAPER_CONCURRENCY` to 2 and take longer breaks between
big scrapes. For sustained volume, add a `SCRAPER_PROXY`.

**Names appear but phone/address are blank**
Google changed the DOM. Run `python diagnose.py` (above).

**"No businesses found"**
Try a broader keyword, or a location Google recognises unambiguously
("Sydney, Australia" beats "Sydney"). Some very specific queries make Maps
jump straight to a single place page instead of a list — the scraper handles
that case and returns the one result.

**Search hangs at "Launching browser…"**
First run downloads Chromium. If it's already downloaded, check whether a
corporate proxy is blocking it; try `HEADLESS=false` to see what the browser
is actually looking at.

**Port 5000 is busy** (macOS AirPlay Receiver uses it)
Set `PORT=5001` in `.env`, or turn off *System Settings → General → AirDrop &
Handoff → AirPlay Receiver*.

**Places API returns `REQUEST_DENIED` / 403**
You enabled the old *"Places API"* instead of *"Places API (New)"*, the key
has a referrer restriction (use IP restriction instead), or billing isn't
enabled on the project.

**Google Sheets: "permission denied"**
The service account can't see your spreadsheet. Open the sheet → Share → add
the `client_email` from `service_account.json` as an **Editor**.

**A batch stopped partway through**
Nothing is lost — every completed search was written to disk. Run
`python batch_cli.py resume latest`, or click **Resume** in the batch list. If
it stopped with status `blocked`, wait a few hours first (or add a proxy),
then resume with a higher `--pace`.

**The dashboard says a batch isn't running, but I know I started it**
Restarting the server clears the *live view*, not the data. The batch folder is
intact — reload the batch list and hit **Resume**. This is exactly why long runs
belong in the CLI.

**"Batch X is still running"**
Only one batch at a time by design. Stop the current one, or wait for it.

**A batch finished suspiciously fast with almost no leads**
Check the status output for `blocked` or a run of failed searches. Google
throttling mid-run is the usual cause. `python batch_cli.py status latest`
lists the failed searches and their errors; resuming retries them.

---

## What changed from the old version

The previous `BusinessLeadFinder.html` stopped working, and it's worth knowing
why so the same thing doesn't happen again:

| Old | New |
|---|---|
| `google.maps.places.PlacesService` — **deprecated** by Google and no longer provisioned for new keys | Playwright scraper (no key) + Places API **(New)** REST endpoint |
| API key in client-side JS, visible in DevTools to anyone | Key stays server-side in `.env`, never sent to the browser |
| Recursive `getAllPages` that re-entered `nextPage()` and resolved the same promise repeatedly — silently double-counted or hung | Explicit page loop with token handling, or the scraper's scroll loop |
| Hard 60-result ceiling | Unlimited with the scraper |
| No export at all | CSV (Excel-safe), clipboard TSV, direct Google Sheets |
| No phone/rating columns in the leads table | All nine fields, everywhere |
| No progress feedback — a spinner and hope | Live SSE stream: rows appear as they're read, with a cancel button |
| No tests | 76 automated checks, all offline |

The old files are untouched in the parent folder if you want to compare.

---

## Legal & rate-limiting notes

Business names, addresses and phone numbers on Google Maps are public
information, and scraping public data has repeatedly been held lawful in the
US (*hiQ v. LinkedIn*). That said:

- Automated access **does** conflict with Google's Terms of Service. For
  commercial or production use, run the **Places API** engine — that's what
  it's there for, and it's why this project ships both.
- Keep `SCRAPER_CONCURRENCY` low. The polite defaults here exist for a reason.
- If you contact the businesses you find, anti-spam law applies to you:
  GDPR/PECR in the EU and UK, the Spam Act in Australia, CAN-SPAM in the US.
  Phone numbers may also be on a do-not-call register.

This tool is provided as-is for lead research. How you use the output is on
you.
