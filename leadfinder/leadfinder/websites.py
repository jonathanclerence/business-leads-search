"""What a business's "website" on Google Maps actually is.

Google shows whatever link the owner typed into the Website box. In the
2026 Victoria sweep, 2,165 "websites" were Facebook pages and 387 were
Instagram profiles: businesses that care about being found online but have
nowhere of their own to send people. Those are the best website leads there
are, and counting them as "has a website" threw them away.

    none       no link at all
    social     Facebook / Instagram / Linktree / TikTok … page only
    directory  a listing on someone else's site (Yellow Pages, hipages …)
    booking    a booking page only (Fresha, Timely, Setmore …)
    dead       a link that no longer works (Google's business.site, shut 2024)
    builder    a free-builder subdomain (Wix, Square, GoDaddy …): a weak site
    real       their own domain

The first five mean "no website of their own" and count as no website
everywhere (filters, exports, scoring). ``builder`` counts as a website but
scores a little upgrade opportunity.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

NO_SITE = ("none", "social", "directory", "booking", "dead")

LABELS = {
    "none": "no website",
    "social": "social page only",
    "directory": "directory listing only",
    "booking": "booking page only",
    "dead": "dead website link",
    "builder": "free-builder site",
    "real": "has a website",
}

# Matched against the host, so "m.facebook.com" and "business.facebook.com" count.
_SOCIAL = ("facebook.com", "fb.com", "fb.me", "instagram.com", "linktr.ee", "linktree.com",
           "tiktok.com", "youtube.com", "youtu.be", "linkedin.com", "twitter.com", "x.com",
           "pinterest.com", "pinterest.com.au", "snapchat.com", "threads.net", "wa.me",
           "whatsapp.com", "beacons.ai", "lnk.bio", "msha.ke", "taplink.cc", "bio.link")
_DIRECTORY = ("yellowpages.com.au", "localsearch.com.au", "truelocal.com.au", "hipages.com.au",
              "oneflare.com.au", "airtasker.com", "serviceseeking.com.au", "word-of-mouth.com.au",
              "startlocal.com.au", "hotfrog.com.au", "yelp.com", "yelp.com.au", "cylex-australia.com",
              "aussieweb.com.au", "whitepages.com.au", "gumtree.com.au", "tradiematch.com.au",
              "builderscrack.com", "productreview.com.au", "healthengine.com.au", "hotdoc.com.au",
              "treatwell.com.au", "bark.com", "ueni.com", "uenicdn.com", "google.com", "goo.gl",
              "g.page", "g.co", "maps.app.goo.gl", "business.google.com")
_BOOKING = ("fresha.com", "gettimely.com", "bookings.gettimely.com", "setmore.com", "booksy.com",
            "mindbodyonline.com", "mindbody.io", "shortcutssoftware.com", "bookwell.com.au",
            "simplybook.me", "simplybook.it", "square.com", "squareup.com", "calendly.com",
            "acuityscheduling.com", "as.me", "vagaro.com", "clinikoapp.com", "cliniko.com",
            "nookal.com", "halaxy.com", "kitomba.com", "phorest.com", "zenoti.com", "salonized.com")
_DEAD = ("business.site",)
_BUILDER = ("wixsite.com", "wix.com", "square.site", "weebly.com", "wordpress.com", "godaddysites.com",
            "carrd.co", "webnode.com", "webnode.com.au", "yolasite.com", "site123.me", "jimdosite.com",
            "jimdofree.com", "mystrikingly.com", "strikingly.com", "blogspot.com", "sites.google.com",
            "webflow.io", "squarespace.com", "shopify.com", "myshopify.com", "ueniweb.com",
            "durablesites.com", "durable.co", "hostinger.site", "framer.website", "notion.site",
            "canva.site", "my.canva.site", "ourwebsite.com.au", "websitebuilder.com")


def _host(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if "://" not in u:
        u = "http://" + u
    try:
        host = (urlparse(u).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


# domain → status. Earlier lists win, so google.com stays a directory while
# sites.google.com is a builder (exact host beats parent domain below).
_STATUS = {}
for _status, _domains in (("social", _SOCIAL), ("directory", _DIRECTORY), ("booking", _BOOKING),
                          ("dead", _DEAD), ("builder", _BUILDER)):
    for _d in _domains:
        _STATUS.setdefault(_d, _status)


def classify(url: str) -> str:
    """→ one of none / social / directory / booking / dead / builder / real."""
    host = _host(url)
    if not host:
        return "none"
    # "m.facebook.com" → try "m.facebook.com", then "facebook.com", then "com".
    labels = host.split(".")
    for i in range(len(labels)):
        status = _STATUS.get(".".join(labels[i:]))
        if status:
            return status
    if not re.search(r"\.[a-z]{2,}$", host):
        return "none"
    return "real"


def has_own_site(url: str) -> bool:
    return classify(url) not in NO_SITE
