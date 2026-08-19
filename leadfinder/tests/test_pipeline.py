"""End-to-end pipeline test against a local fake Google Maps.

This exercises the whole scraper machine — infinite-scroll loading, link
harvesting, the concurrent detail-fetch worker pool, dedupe, ordering, the
job runner and the SSE stream — without touching Google. The fake server
reproduces Maps' lazy-loading behaviour (cards appear only as you scroll)
and its markup contract (role="feed", /maps/place/ links, data-item-id
attributes on the detail panel).

    python tests/test_pipeline.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import leadfinder.scraper as scraper_mod  # noqa: E402
from leadfinder.scraper import GoogleMapsScraper  # noqa: E402

TOTAL_PLACES = 23           # more than one "scroll page"
PAGE_SIZE = 7               # cards revealed per scroll, like Maps
PASS, FAIL = [], []


def check(label: str, got, want) -> None:
    if got == want:
        PASS.append(label)
        print(f"  \033[32m✓\033[0m {label}")
    else:
        FAIL.append(label)
        print(f"  \033[31m✗\033[0m {label}\n      got:  {got!r}\n      want: {want!r}")


# --------------------------------------------------------------------------
# Fake Google Maps
# --------------------------------------------------------------------------
FEED_PAGE = """<!DOCTYPE html><html><head><title>Fake Maps</title></head><body>
<div role="feed" id="feed" style="height:400px;overflow-y:auto"></div>
<script>
const TOTAL = %d, PAGE = %d;
let shown = 0;
const feed = document.getElementById('feed');
function load() {
  const upto = Math.min(TOTAL, shown + PAGE);
  for (let i = shown; i < upto; i++) {
    const d = document.createElement('div');
    d.setAttribute('jsaction', 'card');
    d.style.height = '120px';
    // Index 5 is deliberately a duplicate of index 4 — Maps does this.
    const target = (i === 5) ? 4 : i;
    d.innerHTML = `<a class="hfpxzc" aria-label="Business ${target}"
        href="/maps/place/Business+${target}/data=!4m5!3m4!1s0x1000${target}:0x2000${target}!8m2"></a>
        <div>Business ${target}</div>`;
    feed.appendChild(d);
  }
  shown = upto;
  if (shown >= TOTAL) {
    const end = document.createElement('p');
    end.textContent = "You've reached the end of the list.";
    feed.appendChild(end);
  }
}
load();
feed.addEventListener('scroll', () => {
  if (feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 40) setTimeout(load, 120);
});
</script></body></html>""" % (TOTAL_PLACES, PAGE_SIZE)


def place_page(n: int) -> str:
    has_site = n % 3 != 0    # 2 of every 3 have a website
    has_phone = n % 4 != 0   # 3 of every 4 have a phone
    site = (f'<a data-item-id="authority" href="https://business{n}.example.com/"></a>'
            if has_site else "")
    phone = (f'<button data-item-id="phone:tel:+61 2 9000 {1000 + n}" '
             f'aria-label="Phone: +61 2 9000 {1000 + n}"></button>' if has_phone else "")
    return f"""<!DOCTYPE html><html><body><div role="main">
      <h1 class="DUwDvf">Business {n}</h1>
      <div class="F7nice"><span aria-hidden="true">4.{n % 10}</span>
        <span aria-label="{n * 11} reviews"></span></div>
      <button class="DkEaL">Air conditioning repair service</button>
      <button data-item-id="address" aria-label="Address: {n} Test St, Sydney NSW 2000"></button>
      {site}{phone}
    </div></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/maps/search"):
            body = FEED_PAGE
        elif path.startswith("/maps/place/"):
            try:
                n = int(path.split("/maps/place/Business+")[1].split("/")[0])
            except (IndexError, ValueError):
                n = 0
            body = place_page(n)
        else:
            self.send_response(404)
            self.end_headers()
            return
        raw = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_):  # silence
        pass


def serve() -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


# --------------------------------------------------------------------------
async def run() -> None:
    srv, base = serve()
    # Redirect the scraper at the fake server. Only the search URL needs
    # patching — place URLs are followed from the feed's own hrefs.
    scraper_mod.build_search_url = lambda q: f"{base}/maps/search/{q}"

    events: list[tuple[str, dict]] = []

    async def on_progress(ev, data):
        events.append((ev, data))

    print("\nFull pipeline against fake Maps")

    async with GoogleMapsScraper(headless=True, concurrency=4, on_progress=on_progress) as s:
        results = await s.search("a/c repair in Sydney", 20)

    names = [b.name for b in results]
    check("respects max_results", len(results), 20)
    check("results are unique", len(set(names)), 20)
    check("duplicate card collapsed", names.count("Business 4"), 1)
    check("google ranking order preserved", names[:3], ["Business 0", "Business 1", "Business 2"])
    check("address extracted", results[1].address, "1 Test St, Sydney NSW 2000")
    check("website extracted", results[1].website, "https://business1.example.com/")
    check("website absent where expected", results[0].has_website, False)
    check("phone extracted", results[1].phone, "+61 2 9000 1001")
    check("phone blank where absent", results[0].phone, "")
    check("category extracted", results[1].category, "Air conditioning repair service")
    check("rating parsed", results[1].rating, 4.1)
    check("reviews parsed", results[1].reviews, 11)
    check("place id from url", results[1].place_id, "0x10001:0x20001")
    check("every result has a name", all(b.name for b in results), True)

    kinds = {e for e, _ in events}
    check("emitted scroll events", "scrolling" in kinds, True)
    check("emitted per-item progress", "progress" in kinds, True)
    prog = [d for e, d in events if e == "progress"]
    check("progress counts up to total", prog[-1]["processed"], 20)
    check("progress carries the item payload", isinstance(prog[0].get("item"), dict), True)

    # Scrolling past what one page holds must actually keep loading.
    print("\nScroll continues past the first lazy-load page")
    async with GoogleMapsScraper(headless=True, concurrency=4) as s:
        many = await s.search("a/c repair in Sydney", 100)
    check("loads all cards then stops at end-of-list", len(many), TOTAL_PLACES - 1)  # 1 dup

    srv.shutdown()


def main() -> int:
    asyncio.run(run())
    print(f"\n{'─' * 60}\n  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  failed: " + ", ".join(FAIL))
    print(f"{'─' * 60}\n")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
