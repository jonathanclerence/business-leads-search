"""Booking-fit lead scoring.

The pitch is *"let me build you a website with an online booking system."*
That makes some leads worth far more than others, and a rep working a 4,000-row
CSV alphabetically will waste most of their day. This module ranks every lead
0-100 so the best calls sit at the top of the file.

The model
---------
Category fit **gates** the opportunity rather than just adding to it. That
distinction matters: a supermarket with no website is not a booking-system
lead at all, because the pitch doesn't apply to it. If "no website" were worth
a flat +40, that supermarket would outrank a hair salon — which is exactly the
wrong answer.

    score = opportunity x fit   (max 45)  — no website, AND the pitch applies
          + contactability      (max 20)  — is there a phone number to ring
          + credibility         (max 20)  — reviews + rating: real, busy, solvent
          + booking bonus x fit (max 15)  — appointment-driven verticals

    ...then x0.8 if there's no phone number, because a lead your rep cannot
    dial is barely a lead at all.

``fit`` runs from 1.0 (hair salon — the appointment book *is* the business)
down to 0.12 (supermarket — a booking system makes no sense). A business that
already has a website keeps only a fraction of the opportunity term: they
might still buy a booking system, but they're not who you call first.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Category taxonomy
#
# Matched against Google's own category string (e.g. "Hair salon", "Auto
# repair shop"). Longest-match-wins, so "pet grooming" beats a bare "pet".
# Add your own verticals here — it's just keyword → tier.
# ---------------------------------------------------------------------------

TIER_A = "A"        # the appointment book IS the business
TIER_B = "B"        # books jobs / classes; a booking system is a clear win
TIER_C = "C"        # takes reservations, but survives fine without
TIER_NONE = "none"  # walk-in retail — a booking system makes little sense
TIER_UNKNOWN = "?"  # Google returned no category; don't punish too hard

# How much of the "no website" opportunity actually applies to this vertical.
FIT: Dict[str, float] = {
    TIER_A: 1.00,
    TIER_B: 0.85,
    TIER_C: 0.45,
    TIER_UNKNOWN: 0.60,
    TIER_NONE: 0.12,
}

# Extra weight for verticals where online booking is the entire product.
BOOKING_BONUS_FIT: Dict[str, float] = {
    TIER_A: 1.00,
    TIER_B: 0.60,
    TIER_C: 0.15,
    TIER_UNKNOWN: 0.30,
    TIER_NONE: 0.00,
}

W_OPPORTUNITY = 45      # no website + the pitch applies
W_OPPORTUNITY_HAS_SITE = 6   # they already have one; small residual upsell
W_CONTACT = 20          # a phone number to ring
W_BOOKING = 15          # appointment-driven vertical
NO_PHONE_PENALTY = 0.8  # applied to the whole score

CATEGORY_TIERS: List[Tuple[str, str]] = [
    # ---- Tier A: pure appointment businesses --------------------------------
    *[(k, TIER_A) for k in (
        "hair salon", "hairdress", "barber", "beauty salon", "beautician",
        "nail salon", "nail spa", "manicure", "day spa", "spa", "massage",
        "waxing", "eyebrow", "eyelash", "lash", "tanning", "hair removal",
        "laser clinic", "skin clinic", "cosmetic", "dermatolog", "botox",
        "dentist", "dental", "orthodont", "endodont", "denture",
        "physiotherap", "physio", "chiroprac", "osteopath", "podiatr",
        "acupunctur", "naturopath", "myotherap", "remedial",
        "psycholog", "psychiatr", "counsell", "counselor", "therapist",
        "optometr", "optician", "audiolog", "hearing",
        "veterinar", "vet clinic", "animal hospital",
        "pet groom", "dog groom", "cat groom", "pet salon",
        "tattoo", "piercing",
        "driving school", "driving instructor", "driving lesson",
        "medical clinic", "general practitioner", "doctor", "medical centre",
        "medical center", "womens health", "fertility", "dietitian",
        "nutritionist", "speech patholog", "occupational therap",
    )],
    # ---- Tier B: books jobs, classes and services ---------------------------
    *[(k, TIER_B) for k in (
        "mechanic", "auto repair", "car repair", "car service", "auto service",
        "tyre", "tire shop", "smash repair", "panel beater", "auto electric",
        "car detailing", "car wash", "windscreen", "windshield", "muffler",
        "brake shop", "transmission", "roadworthy", "vehicle inspection",
        "motorcycle repair", "boat repair", "caravan",
        "personal trainer", "gym", "fitness", "yoga", "pilates", "crossfit",
        "martial arts", "boxing", "dance school", "dance studio",
        "swim school", "swimming lesson", "music school", "music lesson",
        "tutor", "tuition", "driving range", "golf lesson",
        "photograph", "videograph", "wedding planner", "celebrant",
        "event venue", "function centre", "caterer", "catering",
        "plumb", "electrician", "locksmith", "pest control", "exterminator",
        "carpet clean", "cleaning service", "house cleaning", "window clean",
        "lawn", "garden", "landscap", "arborist", "tree service",
        "handyman", "builder", "carpenter", "painter", "plasterer",
        "tiler", "roofing", "fencing", "concrete", "paving",
        "removalist", "moving company", "storage",
        "air conditioning", "hvac", "heating", "refrigeration",
        "appliance repair", "computer repair", "phone repair",
        "mobile repair", "it support", "solar",
        "accountant", "bookkeep", "tax", "mortgage broker", "insurance broker",
        "conveyanc", "lawyer", "solicitor", "legal",
        "funeral", "childcare", "day care", "kindergarten",
    )],
    # ---- Tier C: reservations, but the business survives without ------------
    *[(k, TIER_C) for k in (
        "restaurant", "cafe", "coffee", "bistro", "brasserie", "pub", "bar",
        "winery", "brewery", "distillery", "hotel", "motel", "bed and breakfast",
        "accommodation", "tour", "charter", "golf course", "bowling",
        "escape room", "cinema", "theatre",
    )],
    # ---- Tier none: walk-in retail ------------------------------------------
    *[(k, TIER_NONE) for k in (
        "supermarket", "grocery", "convenience store", "petrol", "gas station",
        "hardware store", "bunnings", "chemist", "pharmacy", "post office",
        "bank", "atm", "newsagent", "bottle shop", "liquor",
        "clothing store", "shoe store", "book store", "toy store",
        "furniture store", "electronics store", "department store",
        "shopping mall", "shopping centre", "car dealer", "real estate agency",
    )],
]

# Longest keyword first so specific beats generic.
CATEGORY_TIERS.sort(key=lambda kv: len(kv[0]), reverse=True)

TIER_LABELS = {
    TIER_A: "appointment-based",
    TIER_B: "books jobs/classes",
    TIER_C: "takes reservations",
    TIER_NONE: "walk-in retail",
    TIER_UNKNOWN: "category unknown",
}

GRADES = (
    (78, "Hot"),
    (58, "Warm"),
    (38, "Cool"),
    (0, "Cold"),
)

MAX_SCORE = 100


def category_tier(category: str) -> str:
    """Map a Google Maps category string onto a booking-value tier."""
    if not category or not category.strip():
        return TIER_UNKNOWN
    c = re.sub(r"[^a-z ]+", " ", category.lower())
    for keyword, tier in CATEGORY_TIERS:
        if keyword in c:
            return tier
    return TIER_UNKNOWN


def _review_points(reviews: Optional[int]) -> int:
    """0-13. A proxy for "real, busy, and can afford to pay you"."""
    n = reviews or 0
    if n >= 200:
        return 13
    if n >= 100:
        return 11
    if n >= 50:
        return 9
    if n >= 20:
        return 7
    if n >= 5:
        return 4
    if n >= 1:
        return 2
    return 0


def _rating_points(rating: Optional[float]) -> int:
    """0-7. Unknown scores neutrally rather than badly."""
    if rating is None:
        return 2
    if rating >= 4.5:
        return 7
    if rating >= 4.0:
        return 6
    if rating >= 3.5:
        return 4
    if rating >= 3.0:
        return 2
    return 1


def grade_for(score: int) -> str:
    for threshold, label in GRADES:
        if score >= threshold:
            return label
    return "Cold"


def score_lead(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Return ``{"score": int, "grade": str, "why": str}`` for one lead dict.

    Accepts either a ``Business.to_dict()`` or a raw dict with the same keys.
    """
    website = (lead.get("website") or "").strip()
    has_website = bool(lead.get("has_website", bool(website)))
    phone = (lead.get("phone") or "").strip()
    category = lead.get("category") or ""
    reviews = lead.get("reviews")
    rating = lead.get("rating")

    tier = category_tier(category)
    fit = FIT.get(tier, FIT[TIER_UNKNOWN])
    why: List[str] = []

    # 1. The opportunity — but only as far as the pitch actually applies.
    base = W_OPPORTUNITY if not has_website else W_OPPORTUNITY_HAS_SITE
    total = base * fit
    why.append("no website" if not has_website else "has a website")
    if tier in (TIER_A, TIER_B):
        why.append(TIER_LABELS[tier])
    elif tier == TIER_NONE:
        why.append("weak fit for bookings")
    elif tier == TIER_C:
        why.append("bookings not core")

    # 2. Can a rep actually pick up the phone?
    if phone:
        total += W_CONTACT
    else:
        why.append("no phone listed")

    # 3. Real, busy, solvent.
    total += _review_points(reviews) + _rating_points(rating)
    n_reviews = reviews or 0
    if n_reviews >= 50:
        why.append(f"{n_reviews} reviews")
    elif n_reviews == 0:
        why.append("no reviews yet")
    if rating is not None and rating >= 4.5:
        why.append(f"{rating}★")

    # 4. Verticals where online booking is the whole product.
    total += W_BOOKING * BOOKING_BONUS_FIT.get(tier, 0.3)

    # 5. Unreachable leads are barely leads.
    if not phone:
        total *= NO_PHONE_PENALTY

    score = max(0, min(MAX_SCORE, int(round(total))))
    return {"score": score, "grade": grade_for(score), "why": " · ".join(why)}


def apply_score(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Score a lead dict in place and return it."""
    lead.update(score_lead(lead))
    return lead


def summarise(leads: List[Dict[str, Any]]) -> Dict[str, int]:
    """Grade histogram for a set of leads."""
    out = {"Hot": 0, "Warm": 0, "Cool": 0, "Cold": 0}
    for lead in leads:
        g = lead.get("grade") or grade_for(lead.get("score", 0))
        out[g] = out.get(g, 0) + 1
    return out
