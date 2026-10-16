"""Pull online orders from dunous.com and update the tracker.

Every order placed on dunous.com/buy is recorded on the site (Cloudflare KV)
and listed at /api/orders. sync() reads that list and, for orders that came
from a preview:
  - paid            → moves the lead to "Payment received" and fills in the
                      agreed price, email, contact name and wanted domain
  - awaiting payment → moves the lead to "Invoice sent" (they ordered, but
    / pending          you still need to confirm the money arrived)
Each order/status is logged once in the lead's history, so syncing again is
harmless. Orders without a preview (e.g. a custom /checkout payment) are
returned as `unmatched` so you can see them too.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List

from . import config, db

Log = Callable[[str], None]


class SyncError(RuntimeError):
    pass


def fetch_orders() -> List[Dict[str, Any]]:
    if not config.ORDERS_API_TOKEN:
        raise SyncError("Set ORDERS_API_TOKEN in leadfinder/.env (the same value as on Cloudflare).")
    req = urllib.request.Request(f"{config.SITE_URL}/api/orders", headers={
        "Authorization": f"Bearer {config.ORDERS_API_TOKEN}",
        "User-Agent": "DuNous-leadfinder/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            data = json.load(res)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise SyncError(f"dunous.com said {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise SyncError(f"Couldn't reach {config.SITE_URL}/api/orders: {exc}") from exc
    return data.get("orders") or []


def _money(o: Dict[str, Any]) -> str:
    prefix = {"AUD": "A$", "USD": "US$"}.get(o.get("currency"), f"{o.get('currency', '')} ")
    total = float(o.get("total") or 0)
    return f"{prefix}{total:,.2f}".replace(".00", "")


def _describe(o: Dict[str, Any]) -> str:
    bits = [_money(o)]
    if o.get("package"):
        bits.append(f"{o['package'].title()} package")
    if o.get("code"):
        bits.append(f"code {o['code']}")
    if o.get("domain"):
        bits.append(f"wants {o['domain']}")
    return ", ".join(bits)


def sync(log: Log = print) -> Dict[str, Any]:
    orders = fetch_orders()
    paid = awaiting = 0
    unmatched: List[Dict[str, Any]] = []
    with db.connect() as con:
        for o in orders:
            status, ref, slug = o.get("status"), o.get("ref", ""), o.get("slug") or ""
            if status == "started" or not ref:
                continue  # opened PayPal but never paid
            lead = db.get(con, slug) if slug else None
            if not lead:
                if status in ("paid", "payment_pending"):
                    unmatched.append({k: o.get(k) for k in ("ref", "status", "business", "name", "email", "total", "currency", "createdAt")})
                continue
            marker = f"{ref} {status}"
            if con.execute("SELECT 1 FROM events WHERE slug = ? AND kind = 'payment' AND detail LIKE ?",
                           (slug, marker + "%")).fetchone():
                continue

            label = {"paid": "Paid online", "payment_pending": "Paid online (PayPal reviewing it)",
                     "awaiting_payment": "Ordered online — check payment / send a link"}.get(status, status)
            note = f"{label}: {_describe(o)}"
            db.log(con, slug, "payment", f"{marker} — {note}")
            if status == "paid":
                db.advance(con, slug, "paid", f"{ref} {_describe(o)}")
                paid += 1
                fills = {"price_agreed": round(float(o.get("total") or 0)) or None, "email": o.get("email"),
                         "contact_name": o.get("name"), "domain": o.get("domain")}
            else:
                db.advance(con, slug, "invoice_sent", f"{ref} {label}")
                awaiting += 1
                fills = {"email": o.get("email"), "contact_name": o.get("name"), "domain": o.get("domain")}
            # Only fill blanks — never overwrite what you typed in the tracker.
            for col, val in fills.items():
                if val and not lead.get(col):
                    con.execute(f"UPDATE leads SET {col} = ?, updated_at = ? WHERE slug = ?", (val, db.now(), slug))
            if o.get("notes") and status == "paid":
                db.log(con, slug, "note", f"{ref} client notes: {o['notes'][:900]}")
            log(f"{lead['name']}: {note}")
    log(f"{len(orders)} orders on the site · {paid} newly paid · {awaiting} awaiting payment · {len(unmatched)} without a preview")
    return {"orders": len(orders), "paid": paid, "awaiting": awaiting, "unmatched": unmatched}
