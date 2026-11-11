"""Structural invariants any RunResult must satisfy. Cheap, offline, and strict about no-source claims."""
from __future__ import annotations

from urllib.parse import urlparse

KINDS = {"qual", "quant"}
STATUSES = {"supported", "contested", "unsupported"}
STANCES = {"supports", "refutes"}


def canon(url: str) -> str:
    u = (url or "").strip()
    p = urlparse(u)
    if p.scheme in ("http", "https"):
        return f"{p.scheme}://{p.netloc.lower()}{p.path.rstrip('/')}" + (f"?{p.query}" if p.query else "")
    return u


def check_invariants(result) -> list[str]:
    """Return findings, each starting with ERROR: or WARN:. An empty list means clean."""
    out: list[str] = []
    err = lambda m: out.append("ERROR: " + m)  # noqa: E731
    warn = lambda m: out.append("WARN: " + m)  # noqa: E731

    source_urls = {canon(s.url) for s in result.sources}
    if len(source_urls) != len(result.sources):
        warn("duplicate source urls in result.sources")
    for s in result.sources:
        if not (s.url or "").strip():
            err("source with empty url")
        if not s.fetched_at:
            warn(f"source {s.url[:60]} has no fetched_at")

    ids = [c.id for c in result.claims]
    if len(set(ids)) != len(ids):
        err("duplicate claim ids")
    by_id = {c.id: c for c in result.claims}

    for c in result.claims:
        tag = f"claim {c.id}"
        if not (c.text or "").strip():
            err(f"{tag}: empty text")
        if c.kind not in KINDS:
            err(f"{tag}: kind {c.kind!r} not in {sorted(KINDS)}")
        if c.status not in STATUSES:
            err(f"{tag}: status {c.status!r} not in {sorted(STATUSES)}")
        if not isinstance(c.confidence, (int, float)) or not 0.0 <= float(c.confidence) <= 1.0:
            err(f"{tag}: confidence {c.confidence!r} outside 0..1")
        for ev in c.evidence:
            if ev.stance not in STANCES:
                err(f"{tag}: stance {ev.stance!r} not in {sorted(STANCES)}")
            if canon(ev.source_url) not in source_urls:
                err(f"{tag}: evidence url not in result.sources ({ev.source_url[:80]})")
        supports = [e for e in c.evidence if e.stance == "supports"]
        if c.status == "supported" and not supports:
            err(f"{tag}: status supported but no supporting evidence (a no-source claim)")
        if c.status == "contested" and not c.evidence:
            err(f"{tag}: status contested but no evidence at all")
        if c.status == "unsupported" and float(c.confidence or 0) > 0.5:
            warn(f"{tag}: unsupported claim carries confidence {c.confidence}")
        if c.status == "supported" and c.kind == "quant" and float(c.confidence or 0) < 0.3:
            warn(f"{tag}: supported quant claim with confidence {c.confidence}")

    for i, cf in enumerate(result.conflicts):
        if not (cf.reason or "").strip():
            warn(f"conflict {i}: empty reason")
        if len(cf.claim_ids) < 1:
            err(f"conflict {i}: no claim_ids")
        for cid in cf.claim_ids:
            if cid not in by_id:
                err(f"conflict {i}: claim id {cid!r} does not exist")
    unresolved_claims = {cid for cf in result.conflicts if not cf.resolved for cid in cf.claim_ids}
    for cid in unresolved_claims:
        c = by_id.get(cid)
        if c is not None and c.status == "supported" and c.confidence > 0.85:
            warn(f"claim {cid}: high confidence {c.confidence} despite an unresolved conflict")

    if not (result.answer_md or "").strip():
        err("answer_md is empty")
    live = [c for c in result.claims if c.status in ("supported", "contested")]
    if live and "http" not in result.answer_md and "[" not in result.answer_md:
        warn("answer_md has claims but no links or [n] citation markers")
    for k in ("tokens", "seconds", "nodes"):
        if k not in (result.stats or {}):
            warn(f"stats missing {k!r}")
    if not result.run_id:
        err("run_id empty")
    return out


def errors(findings: list[str]) -> list[str]:
    return [f for f in findings if f.startswith("ERROR")]
