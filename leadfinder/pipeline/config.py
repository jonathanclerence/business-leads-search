"""Pipeline settings, from leadfinder/.env with working defaults."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# The dunous.com Next.js repo. Previews are written into its public/ folder.
MARKETING_SITE_DIR = Path(os.getenv("MARKETING_SITE_DIR",
                                    str(ROOT.parent.parent / "marketing-site"))).expanduser()
# The branch Cloudflare Pages deploys to production. `publish` commits there.
PUBLISH_BRANCH = os.getenv("PUBLISH_BRANCH", "main")
PUBLISH_REMOTE = os.getenv("PUBLISH_REMOTE", "origin")
# A separate checkout used only for publishing, so your own working copy of
# the site (and whatever branch you have checked out) is never touched.
PUBLISH_WORKTREE = Path(os.getenv("PUBLISH_WORKTREE",
                                  str(ROOT.parent.parent / ".marketing-site-publish"))).expanduser()

SITE_URL = os.getenv("PREVIEW_SITE_URL", "https://www.dunous.com").rstrip("/")
PREVIEW_PATH = "/previewsite/"
BRAND = os.getenv("PREVIEW_BRAND", "DuNous")
WHATSAPP_DISPLAY = os.getenv("PREVIEW_WHATSAPP_DISPLAY", "(+61) 422 765 361")
WHATSAPP_HREF = os.getenv("PREVIEW_WHATSAPP_HREF", "https://wa.me/61422765361")

# Inside the marketing site
PAGES_DIR = "public/previewsite-pages"     # one file per lead (served by the route)
ASSETS_DIR = "public/previewsite-assets"   # shared css/js/photos

EXPORT_DIR = ROOT / "exports" / "sites"


def preview_url(slug: str) -> str:
    return f"{SITE_URL}{PREVIEW_PATH}{slug}"
