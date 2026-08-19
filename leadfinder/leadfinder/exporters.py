"""CSV and Google Sheets export."""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from typing import Any, Sequence

from .config import settings
from .models import CSV_HEADERS, Business


def _as_business(item: Any) -> Business:
    if isinstance(item, Business):
        return item
    d = dict(item)
    d.pop("has_website", None)
    return Business(**{k: v for k, v in d.items() if k in Business.__annotations__})


def to_rows(items: Sequence[Any]) -> list[list[Any]]:
    return [_as_business(i).to_row() for i in items]


def to_csv_string(items: Sequence[Any]) -> str:
    buf = io.StringIO()
    # utf-8-sig BOM is added by the caller; Excel needs it to read UTF-8.
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(CSV_HEADERS)
    writer.writerows(to_rows(items))
    return buf.getvalue()


def to_csv_bytes(items: Sequence[Any]) -> bytes:
    """UTF-8 with BOM so Excel opens accented names correctly on double-click."""
    return to_csv_string(items).encode("utf-8-sig")


def suggest_filename(query: str, location: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", f"{query}-{location}".lower()).strip("-")[:60]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return f"leads-{slug or 'export'}-{stamp}.csv"


# ---------------------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------------------

class SheetsError(RuntimeError):
    pass


def export_to_google_sheet(
    items: Sequence[Any],
    title: str,
    share_with: str | None = None,
    spreadsheet_url: str | None = None,
) -> dict[str, str]:
    """Push rows into Google Sheets via a service account.

    Setup
    -----
    1. Google Cloud Console → enable **Google Sheets API** and **Google Drive API**.
    2. IAM & Admin → Service Accounts → create one → Keys → Add key → JSON.
    3. Save the JSON next to app.py as ``service_account.json`` and set
       ``GOOGLE_SERVICE_ACCOUNT_FILE=./service_account.json`` in ``.env``.
    4. Either set ``GSHEET_SHARE_WITH=you@example.com`` (a brand-new sheet is
       created and shared with you), or paste an existing sheet's URL into the
       dashboard after sharing that sheet with the service account's
       ``client_email`` as an Editor.
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as exc:  # pragma: no cover
        raise SheetsError(
            "gspread is not installed. Run: pip install gspread google-auth"
        ) from exc

    key_path = settings.service_account_path()
    if not key_path:
        raise SheetsError(
            "No service-account JSON found. Set GOOGLE_SERVICE_ACCOUNT_FILE in .env "
            "to the path of your key file."
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(str(key_path), scopes=scopes)
    client = gspread.authorize(creds)

    if spreadsheet_url:
        sh = client.open_by_url(spreadsheet_url)
        ws = sh.add_worksheet(
            title=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            rows=max(len(items) + 10, 100),
            cols=len(CSV_HEADERS) + 2,
        )
    else:
        sh = client.create(title)
        ws = sh.sheet1
        ws.update_title("Leads")
        recipient = share_with or settings.GSHEET_SHARE_WITH
        if recipient:
            sh.share(recipient, perm_type="user", role="writer", notify=False)

    ws.update(values=[CSV_HEADERS] + to_rows(items), range_name="A1")
    ws.freeze(rows=1)
    ws.format("A1:I1", {"textFormat": {"bold": True}})

    return {
        "url": sh.url,
        "title": sh.title,
        "worksheet": ws.title,
        "shared_with": share_with or settings.GSHEET_SHARE_WITH or "",
        "service_account": creds.service_account_email,
    }
