"""Central configuration. Everything is env-driven with sensible defaults,
so the app runs out of the box with zero setup."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


class Settings:
    # --- server ---
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = _int("PORT", 5000)

    # --- scraper ---
    HEADLESS: bool = _bool("HEADLESS", True)
    CONCURRENCY: int = max(1, min(_int("SCRAPER_CONCURRENCY", 4), 10))
    TIMEOUT_MS: int = _int("SCRAPER_TIMEOUT_MS", 30_000)
    HL: str = os.getenv("SCRAPER_HL", "en")
    GL: str = os.getenv("SCRAPER_GL", "us")
    PROXY: str | None = os.getenv("SCRAPER_PROXY") or None
    # Point at a Chrome/Chromium binary you already have instead of the one
    # `playwright install` downloads. Leave unset for the normal setup.
    CHROMIUM_PATH: str | None = os.getenv("PLAYWRIGHT_CHROMIUM_PATH") or None

    # --- Places API (New) ---
    GOOGLE_MAPS_API_KEY: str | None = os.getenv("GOOGLE_MAPS_API_KEY") or None

    # --- Google Sheets ---
    SERVICE_ACCOUNT_FILE: str | None = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE") or None
    GSHEET_SHARE_WITH: str | None = os.getenv("GSHEET_SHARE_WITH") or None

    # --- paths ---
    EXPORT_DIR: Path = BASE_DIR / "exports"

    @property
    def places_api_available(self) -> bool:
        return bool(self.GOOGLE_MAPS_API_KEY)

    @property
    def sheets_available(self) -> bool:
        if not self.SERVICE_ACCOUNT_FILE:
            return False
        return (BASE_DIR / self.SERVICE_ACCOUNT_FILE).exists() or Path(
            self.SERVICE_ACCOUNT_FILE
        ).exists()

    def service_account_path(self) -> Path | None:
        if not self.SERVICE_ACCOUNT_FILE:
            return None
        p = Path(self.SERVICE_ACCOUNT_FILE)
        if p.is_absolute() and p.exists():
            return p
        candidate = BASE_DIR / self.SERVICE_ACCOUNT_FILE
        return candidate if candidate.exists() else None


settings = Settings()
settings.EXPORT_DIR.mkdir(exist_ok=True)
