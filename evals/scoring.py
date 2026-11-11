"""Score one run, and compare repeated runs. Standard library only."""
from __future__ import annotations

import html
import itertools
import logging
import os
import re
import statistics
import threading
import urllib.error
import urllib.request
import zlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlparse

from .invariants import canon, check_invariants, errors
from .rules import source_rules

logging.getLogger("pypdf").setLevel(logging.CRITICAL)

# Gemini Flash list prices in USD per 1M tokens. These are estimates: the "-latest" alias can move.
PRICE_IN = float(os.environ.get("EVAL_PRICE_IN_PER_M", "0.30"))
PRICE_OUT = float(os.environ.get("EVAL_PRICE_OUT_PER_M", "2.50"))
PRICE_BLENDED = float(os.environ.get("EVAL_PRICE_BLENDED_PER_M", "0.80"))  # when only a total is known


# ---------- text helpers ----------

def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def quote_in_text(quote: str, text: str) -> bool:
    q, t = norm(quote), norm(text)
    if not q or not t:
        return False
    if q in t:
        return True
    frags = [norm(f) for f in re.split(r"\.\.\.|…|\[\.\.\.\]", quote)]
    frags = [f for f in frags if len(f.split()) >= 4]
    if len(frags) >= 2 and all(f in t for f in frags):
        return True
    qw, tw = q.split(), t.split()
    if len(qw) >= 6:
        tri = {tuple(qw[i:i + 3]) for i in range(len(qw) - 2)}
        ttri = {tuple(tw[i:i + 3]) for i in range(len(tw) - 2)}
        return len(tri & ttri) / len(tri) >= 0.85
    return False


def pdf_text(data: bytes) -> str:
    """Best-effort text from a PDF: pypdf when installed, else string operators in (inflated) streams."""
    if len(data) > 1_500_000:  # parsing big PDFs starves every other thread, so they count as unreadable
        return ""
    try:
        import io

        from pypdf import PdfReader  # type: ignore

        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages[:12])
    except Exception:
        pass
    chunks = [data]
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        try:
            chunks.append(zlib.decompress(m.group(1)))
        except Exception:
            pass
    out: list[str] = []
    for ch in chunks:
        s = ch.decode("latin-1", "ignore")
        for m in re.finditer(r"\(((?:\\.|[^\\)])*)\)\s*Tj", s):
            out.append(re.sub(r"\\(.)", r"\1", m.group(1)))
        for m in re.finditer(r"\[(.*?)\]\s*TJ", s, re.S):
            out.append("".join(re.sub(r"\\(.)", r"\1", x) for x in re.findall(r"\(((?:\\.|[^\\)])*)\)", m.group(1))))
    return "\n".join(out)


# ---------- fetching ----------

@dataclass
class Fetched:
    status: int | None
    text: str
    kind: str  # html | pdf | other | error
    error: str = ""


class Fetcher:
    def __init__(self, timeout: float = 10.0, max_bytes: int = 1_500_000):
        self.timeout, self.max_bytes = timeout, max_bytes
        self._cache: dict[str, Fetched] = {}
        self._lock = threading.Lock()

    def fetch(self, url: str) -> Fetched:
        with self._lock:
            hit = self._cache.get(url)
        if hit is not None:
            return hit
        res = self._fetch(url)
        with self._lock:
            self._cache[url] = res
        return res

    def _fetch(self, url: str) -> Fetched:
        p = urlparse(url)
        if p.scheme in ("", "file"):
            path = p.path if p.scheme == "file" else url
            try:
                with open(path, "rb") as fh:
                    data = fh.read(self.max_bytes * 4)
            except OSError as e:
                return Fetched(None, "", "error", type(e).__name__)
            if data[:5] == b"%PDF-":
                return Fetched(200, pdf_text(data), "pdf")
            return Fetched(200, data.decode("utf-8", "ignore"), "other")
        if p.scheme not in ("http", "https"):
            return Fetched(None, "", "error", "unsupported scheme")
        req = urllib.request.Request(url, headers={
            "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
            "Accept-Encoding": "identity",
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                ctype = r.headers.get("Content-Type", "") or ""
                charset = r.headers.get_content_charset() or "utf-8"
                raw = r.read(self.max_bytes)
                status = r.status
        except urllib.error.HTTPError as e:
            return Fetched(e.code, "", "error", f"HTTP {e.code}")
        except Exception as e:  # URLError, timeout, ssl, connection reset
            return Fetched(None, "", "error", type(e).__name__)
        if "pdf" in ctype.lower() or raw[:5] == b"%PDF-":
            if len(raw) >= self.max_bytes:
                return Fetched(status, "", "error", "PDF too large to read")
            return Fetched(status, pdf_text(raw), "pdf")
        text = raw.decode(charset, "ignore")
        text = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        return Fetched(status, html.unescape(text), "html")


# ---------- citations ----------

def check_evidence(ev, sources: dict, fetcher: Fetcher | None, check_urls: bool) -> tuple[str, str]:
    """Return (state, why). state is valid, invalid or unverifiable."""
    url, quote = (ev.source_url or "").strip(), (ev.quote or "").strip()
    if not url:
        return "invalid", "no source_url"
    if not quote:
        return "linkonly", "link without a quote"
    src = sources.get(canon(url))
    if src is None:
        return "invalid", "source_url not in result.sources"
    snippet_ok = quote_in_text(quote, src.snippet or "")
    if not check_urls or fetcher is None:
        return ("valid", "quote in snippet") if snippet_ok else ("unverifiable", "page not fetched")
    fr = fetcher.fetch(url)
    if fr.status is not None and fr.status < 400:
        if len(norm(fr.text)) < 400:  # script shell or image-only page
            return ("valid", "quote in snippet") if snippet_ok else ("unverifiable", "page has no readable text")
        if quote_in_text(quote, fr.text):
            return "valid", "quote on page"
        if snippet_ok:
            return "valid", "quote in snippet"
        return "invalid", "quote not found on page"
    if fr.status in (404, 410):
        return "invalid", f"dead link HTTP {fr.status}"
    return ("valid", "quote in snippet") if snippet_ok else ("unverifiable", fr.error or f"HTTP {fr.status}")


# ---------- one run ----------

def token_counts(stats: dict) -> tuple[int, int | None, int | None]:
    t = (stats or {}).get("tokens")
    if isinstance(t, dict):
        def first(*keys):
            for k in keys:
                if isinstance(t.get(k), (int, float)):
                    return int(t[k])
            return None
        inp = first("input", "prompt", "in", "prompt_tokens", "input_tokens")
        out = first("output", "completion", "out", "candidates", "output_tokens", "completion_tokens")
        total = first("total", "total_tokens") or ((inp or 0) + (out or 0))
        return total, inp, out
    if isinstance(t, (int, float)):
        return int(t), None, None
    return 0, None, None


def cost_usd(stats: dict) -> float:
    total, inp, out = token_counts(stats)
    if inp is not None and out is not None:
        return inp / 1e6 * PRICE_IN + out / 1e6 * PRICE_OUT
    return total / 1e6 * PRICE_BLENDED


def numbers_in(text: str) -> set[str]:
    out = set()
    for m in re.findall(r"\d[\d,]*\.?\d*", text or ""):
        m = m.replace(",", "").rstrip(".")
        out.add(m.lstrip("0") or "0")
    return out


def score_run(case, result, wall_seconds: float, fetcher: Fetcher | None = None, check_urls: bool = True) -> dict:
    claims = list(result.claims)
    live = [c for c in claims if c.status in ("supported", "contested")]
    sources = {canon(s.url): s for s in result.sources}

    # citation validity
    jobs = [(c, ev) for c in live for ev in c.evidence]
    uncited = sum(1 for c in live if not c.evidence)
    if jobs:
        with ThreadPoolExecutor(max_workers=8) as pool:
            verdicts = list(pool.map(lambda j: check_evidence(j[1], sources, fetcher, check_urls), jobs))
    else:
        verdicts = []
    tally = Counter(v[0] for v in verdicts)
    bad = [{"claim": j[0].id, "url": j[1].source_url[:100], "why": v[1]}
           for j, v in zip(jobs, verdicts) if v[0] == "invalid"]
    denom = tally["valid"] + tally["invalid"] + uncited
    claim_has_valid = {j[0].id for j, v in zip(jobs, verdicts) if v[0] == "valid"}
    supported_no_valid = [c for c in claims if c.status == "supported" and c.id not in claim_has_valid]
    # a supported claim whose evidence could not be checked is not counted against the agent here
    unver_ids = {j[0].id for j, v in zip(jobs, verdicts) if v[0] in ("unverifiable", "linkonly")}
    hard_unsupported = [c for c in supported_no_valid if c.id not in unver_ids]

    # coverage
    text = "\n".join([result.answer_md or "", *[c.text for c in live], *(result.uncertainty_notes or [])])
    covered = [p.name for p in case.points if any(re.search(rx, text, re.I | re.S) for rx in p.any_of)]

    # conflicts
    by_id = {c.id: c for c in claims}
    def conflict_text(cf):
        return (cf.reason or "") + " " + " ".join(by_id[i].text for i in cf.claim_ids if i in by_id)
    conflict_hit = None
    if case.expect_conflict:
        conflict_hit = float(any(re.search(rx, conflict_text(cf), re.I)
                                 for cf in result.conflicts for rx in case.expect_conflict))

    # abstention
    abstain_ok = None
    if case.expect_abstain:
        hedged = "abstains" in covered or bool(result.uncertainty_notes)
        fabricated = [c for c in hard_unsupported if c.kind == "quant"]
        abstain_ok = float(hedged and not fabricated)

    rules = source_rules(result, fetcher, check_urls)
    findings = check_invariants(result)
    total_tok, tin, tout = token_counts(result.stats)
    parts = [x for x in (len(covered) / len(case.points), (tally["valid"] / denom) if denom else None,
                         conflict_hit, abstain_ok) if x is not None]
    return {
        "coverage": len(covered) / len(case.points),
        "covered": covered,
        "missed": [p.name for p in case.points if p.name not in covered],
        "citation_validity": (tally["valid"] / denom) if denom else None,
        "citations": {"valid": tally["valid"], "invalid": tally["invalid"],
                      "unverifiable": tally["unverifiable"], "link_only": tally["linkonly"],
                      "uncited_claims": uncited},
        "bad_citations": bad[:10],
        "supported_without_valid_evidence": len(hard_unsupported),
        "claims": {s: sum(1 for c in claims if c.status == s) for s in ("supported", "contested", "unsupported")},
        "conflicts": len(result.conflicts),
        "conflict_hit": conflict_hit,
        "abstain_ok": abstain_ok,
        "quality": sum(parts) / len(parts),
        "seconds": round(wall_seconds, 1),
        "over_budget_s": round(max(0.0, wall_seconds - case.budget_mins * 60), 1),
        "tokens": total_tok,
        "cost_usd": round(cost_usd(result.stats), 4),
        "sources": len(result.sources),
        "domains": sorted({(s.org or urlparse(s.url).netloc or s.url) for s in result.sources}),
        "numbers": sorted(numbers_in(" ".join(c.text for c in live if c.kind == "quant"))),
        "rules": rules,
        "invariant_errors": errors(findings),
        "invariant_warnings": [f for f in findings if f.startswith("WARN")],
        "error": None,
    }


# ---------- across runs ----------

def jaccard(a: set, b: set) -> float:
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def pairwise(sets: list[set]) -> float | None:
    pairs = list(itertools.combinations(sets, 2))
    return statistics.mean(jaccard(a, b) for a, b in pairs) if pairs else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def aggregate(case, runs: list[dict]) -> dict:
    ok = [r for r in runs if not r.get("error")]
    agg = {
        "case": case.id, "title": case.title, "runs": len(runs), "runs_ok": len(ok),
        "coverage": mean(r["coverage"] for r in ok),
        "citation_validity": mean(r["citation_validity"] for r in ok),
        "uncited_or_invalid": sum(r["citations"]["invalid"] + r["citations"]["uncited_claims"] for r in ok),
        "unverifiable": sum(r["citations"]["unverifiable"] for r in ok),
        "supported_without_valid_evidence": sum(r["supported_without_valid_evidence"] for r in ok),
        "conflicts": mean(r["conflicts"] for r in ok),
        "conflict_hit": mean(r["conflict_hit"] for r in ok),
        "abstain_ok": mean(r["abstain_ok"] for r in ok),
        "quality": mean(r["quality"] for r in ok),
        "seconds_mean": mean(r["seconds"] for r in ok),
        "seconds_max": max((r["seconds"] for r in ok), default=None),
        "over_budget_max_s": max((r["over_budget_s"] for r in ok), default=None),
        "cost_usd": mean(r["cost_usd"] for r in ok),
        "tokens": mean(r["tokens"] for r in ok),
        "invariant_errors": sum(len(r["invariant_errors"]) for r in ok),
        "errors": [r["error"] for r in runs if r.get("error")],
    }
    rt = {k: [0, 0] for k in ("tier", "independence", "quote_on_page", "quote_not_claim")}
    for r in ok:
        for k in rt:
            got = (r.get("rules") or {}).get(k, [0, 0])
            rt[k][0] += got[0]
            rt[k][1] += got[1]
    agg["rules"] = rt
    agg["cit_valid"] = sum(r["citations"]["valid"] for r in ok)
    agg["cit_checked"] = sum(r["citations"]["valid"] + r["citations"]["invalid"] + r["citations"]["uncited_claims"]
                             for r in ok)
    agg["unfetchable"] = sum((r.get("rules") or {}).get("unfetchable", 0) for r in ok)
    agg["link_only"] = sum((r.get("rules") or {}).get("link_only", 0) for r in ok)
    cov = [r["coverage"] for r in ok]
    agg["coverage_spread"] = (max(cov) - min(cov)) if cov else None
    agg["point_agreement"] = pairwise([set(r["covered"]) for r in ok])
    agg["source_overlap"] = pairwise([set(r["domains"]) for r in ok])
    agg["number_agreement"] = pairwise([set(r["numbers"]) for r in ok if r["numbers"]] or [])
    return agg
