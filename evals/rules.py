"""Source-tier and quote rules, scored on every eval result.

1. tier          No supported claim may rest only on Wikipedia, Quora, YouTube, social or forum domains.
2. independence  A supported claim backed only by non-official sources needs two or more independent domains.
3. quote_on_page Every evidence quote shown is a substring of the fetched page text (normalised for case,
                 spacing and punctuation). A quote with ellipses passes when every fragment is a substring.
4. quote_not_claim  No quote equals the claim text unless it genuinely appears on the page.

Page text comes from <runs dir>/<run_id>/pages.json ({url: text}) when the agent saved it, else from a live fetch.
A page that cannot be read counts as not passing, because nobody can show the quote is on it.
"""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from .invariants import canon

LOW_TRUST_HOSTS = (
    "wikipedia.org", "wikimedia.org", "wikiwand.com", "wikihow.com", "quora.com", "youtube.com", "youtu.be",
    "reddit.com", "facebook.com", "fb.com", "instagram.com", "x.com", "twitter.com", "threads.net", "tiktok.com",
    "linkedin.com", "pinterest.com", "tumblr.com", "snapchat.com", "t.me", "discord.com", "stackexchange.com",
    "stackoverflow.com", "news.ycombinator.com", "bogleheads.org", "wallstreetoasis.com", "elitetrader.com",
    "city-data.com",
)
FORUM_LABELS = {"forum", "forums", "community", "discuss", "discussion", "boards"}
FORUM_PATHS = ("/forum/", "/forums/", "/community/", "/discussion/", "/discussions/", "/boards/")
OFFICIAL_SUFFIXES = (".gov", ".mil", ".int", ".edu", ".gov.uk", ".ac.uk", ".gov.sg", ".gov.au", ".gc.ca", ".europa.eu")
OFFICIAL_HOSTS = ("imf.org", "worldbank.org", "bis.org", "oecd.org", "nber.org", "ssrn.com", "arxiv.org", "jstor.org",
                  "bankofengland.co.uk", "boj.or.jp", "frbsf.org", "brookings.edu", "piie.com", "wto.org", "un.org")
TWO_LEVEL = {"co.uk", "org.uk", "gov.uk", "ac.uk", "com.au", "gov.au", "co.jp", "or.jp", "com.sg", "gov.sg",
             "edu.sg", "co.in", "com.br", "co.nz", "com.cn", "com.hk", "co.za", "europa.eu"}


def norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def host_of(url) -> str:
    h = (urlparse(str(url or "").strip()).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def registrable(host: str) -> str:
    parts = [p for p in host.split(".") if p]
    if len(parts) <= 2:
        return host
    last2 = ".".join(parts[-2:])
    return ".".join(parts[-3:]) if last2 in TWO_LEVEL else last2


def is_low_trust(url) -> bool:
    h = host_of(url)
    if any(h == d or h.endswith("." + d) for d in LOW_TRUST_HOSTS):
        return True
    path = urlparse(str(url or "").strip()).path.lower() + "/"
    return bool(set(h.split(".")[:-2]) & FORUM_LABELS) or any(p in path for p in FORUM_PATHS)


def is_official(url) -> bool:
    h = host_of(url)
    if not h or is_low_trust(url):
        return False
    return (h.endswith(OFFICIAL_SUFFIXES) or h.endswith("fed.org")
            or any(h == d or h.endswith("." + d) for d in OFFICIAL_HOSTS))


def strict_substring(quote, text) -> bool:
    q, t = norm(quote), norm(text)
    if not q or not t:
        return False
    if q in t:
        return True
    frags = [norm(f) for f in re.split(r"\.\.\.|…|\[\.\.\.\]", str(quote or ""))]
    frags = [f for f in frags if f]
    return len(frags) >= 2 and all(len(f.split()) >= 3 and f in t for f in frags)


def stored_pages(run_id) -> dict:
    """Page text the agent saved for this run, keyed by canonical url."""
    roots = []
    if os.environ.get("RESEARCH_RUNS_DIR"):
        roots.append(os.environ["RESEARCH_RUNS_DIR"])
    roots.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runs"))
    for r in roots:
        try:
            with open(os.path.join(r, str(run_id), "pages.json"), encoding="utf-8") as fh:
                d = json.load(fh)
            return {canon(k): v for k, v in d.items() if isinstance(v, str)}
        except Exception:
            continue
    return {}


def source_rules(result, fetcher=None, check_urls=True) -> dict:
    """Pass counts as [passed, total] for the four rules, plus the evidence items that failed the quote rule."""
    pages = stored_pages(result.run_id)
    tier = [0, 0]
    indep = [0, 0]
    for c in result.claims:
        sup = [e for e in c.evidence if e.stance == "supports"]
        if c.status != "supported" or not sup:
            continue
        tier[1] += 1
        tier[0] += 0 if all(is_low_trust(e.source_url) for e in sup) else 1
        indep[1] += 1
        if any(is_official(e.source_url) for e in sup):
            indep[0] += 1
        elif len({registrable(host_of(e.source_url)) for e in sup if host_of(e.source_url)}) >= 2:
            indep[0] += 1
    shown = [(c, e) for c in result.claims if c.status in ("supported", "contested") for e in c.evidence]
    items = [(c, e) for c, e in shown if norm(e.quote)]  # a link with no quote shows no quote, so it is not judged
    link_only = len(shown) - len(items)

    def page_for(url):
        k = canon(url)
        if k in pages:
            return pages[k]
        if check_urls and fetcher is not None:
            fr = fetcher.fetch(url)
            if fr.status is not None and fr.status < 400 and len(norm(fr.text)) >= 200:
                return fr.text
        return None

    uniq = sorted({e.source_url for _, e in items if e.source_url})
    with ThreadPoolExecutor(max_workers=8) as pool:
        got = dict(zip(uniq, pool.map(page_for, uniq)))
    on_page = not_claim = unfetchable = 0
    bad = []
    for c, e in items:
        text = got.get(e.source_url)
        same = bool(norm(e.quote)) and norm(e.quote) == norm(c.text)
        ok = text is not None and strict_substring(e.quote, text)
        unfetchable += text is None
        on_page += ok
        not_claim += (not same) or ok
        if not ok and len(bad) < 8:
            why = "page not readable" if text is None else (
                "quote equals the claim text and is not on the page" if same else "quote not on the page")
            bad.append({"claim": c.id, "url": str(e.source_url or "")[:90], "why": why})
    return {"tier": tier, "independence": indep, "quote_on_page": [on_page, len(items)],
            "quote_not_claim": [not_claim, len(items)], "unfetchable": unfetchable, "link_only": link_only,
            "bad_quotes": bad}
