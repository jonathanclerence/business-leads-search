"""What we sell, in one place: the website packages, hosting and rates.

The client documents (proposal, service agreement, onboarding form) are built
from these, so a price changed here changes in every PDF and in the tracker's
call script and email. The playbook (ui/playbook.html) and the marketing
site's /buy page (src/content/packages.ts) quote the same numbers — update
them too.
"""

from __future__ import annotations

CURRENCY = "AUD"

PACKAGES = [
    dict(id="foundation", name="Foundation", price=649,
         tagline="Your website as built, made yours.",
         best_for="You like the website as it is.",
         pages=1, revisions="1 round of text changes", launch_days=2, edit_days=0,
         features=[
             "The website we built, finished as one page",
             "Your logo, colours, photos and details",
             "Tap-to-call, map and enquiry button",
             "1 round of text changes",
         ]),
    dict(id="growth", name="Growth", price=799, recommended=True,
         tagline="A complete website that brings in bookings.",
         best_for="Most local businesses.",
         pages=3, revisions="2 rounds of design changes", launch_days=3, edit_days=14,
         features=[
             "Everything in Foundation",
             "Up to 3 pages",
             "Booking or quote form to your phone or email",
             "Basic SEO, Google profile and socials linked",
             "2 rounds of design changes",
             "14 days of free edits after launch",
         ]),
    dict(id="pro", name="Pro", price=999,
         tagline="Written for you, set up to grow.",
         best_for="Ready to advertise and track results.",
         pages=5, revisions="3 rounds of design changes", launch_days=5, edit_days=30,
         features=[
             "Everything in Growth",
             "Up to 5 pages, with a photo gallery",
             "Copywriting for up to 3 pages",
             "Google Analytics and Meta Pixel",
             "3 rounds of design changes",
             "30 days of free edits after launch",
         ]),
]

ENTERPRISE = dict(
    name="Enterprise", price_from=1500,
    tagline="Online shops, logins, integrations, multi-location sites or ongoing marketing. Fixed quote.",
)

# Work outside a package, quoted before we start. Billed in 30-minute blocks.
HOURLY_RATE = 60

# Managed hosting (option A). Billed yearly in advance by bank transfer.
HOSTING = dict(
    yearly=390,
    edit_minutes=30,     # small updates included each month
    notice_days=30,      # to cancel managed hosting
    handover_fee=149,    # export, move to their own hosting, domain transfer
)

PAYMENT_DUE_DAYS = 7
PROPOSAL_VALID_DAYS = 14
TERMS_URL = "https://www.dunous.com/terms"


def money(amount: int) -> str:
    """649 → "$649", 1500 → "$1,500"."""
    return f"${amount:,}"


def package(pkg_id: str):
    return next((p for p in PACKAGES if p["id"] == pkg_id), None)


def recommended():
    return next(p for p in PACKAGES if p.get("recommended"))
