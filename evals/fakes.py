"""Offline stand-in for run_research, so the scorer, runner and report can be exercised without the API."""
from __future__ import annotations

import hashlib
import time

from research.models import Claim, Conflict, Evidence, RunResult, Source

from .cases import BY_ID


def _case_for(question: str):
    for c in BY_ID.values():
        if c.question == question:
            return c
    return None


def fake_run_research(question, pdf_paths, budget_mins, emit, ask_fn=None):
    """Covers most rubric points; which ones it drops depends on a hash of the question and a call counter."""
    fake_run_research.calls = getattr(fake_run_research, "calls", 0) + 1
    case = _case_for(question)
    seed = int(hashlib.sha256(f"{question}{fake_run_research.calls}".encode()).hexdigest(), 16)
    points = case.points if case else []
    keep = [p for i, p in enumerate(points) if (seed >> i) % 5 != 0] or points[:1]
    sources, claims = [], []
    for i, p in enumerate(keep):
        url = f"https://example.test/{case.id}/{i}"
        sources.append(Source(url=url, org="example.test", snippet=p.sample, fetched_at="2026-10-09T14:00:00Z"))
        claims.append(Claim(id=f"c{i}", text=p.sample, kind="quant" if any(ch.isdigit() for ch in p.sample) else "qual",
                            status="supported", confidence=0.8,
                            evidence=[Evidence(source_url=url, quote=p.sample)]))
    conflicts = []
    if case and case.expect_conflict and len(claims) >= 2:
        conflicts.append(Conflict(claim_ids=["c0", "c1"], reason="Sources disagree: " + claims[0].text))
    emit({"event": "fake", "claims": len(claims)})
    time.sleep(0.05)
    answer = " ".join(f"{c.text} [{i + 1}]" for i, c in enumerate(claims))
    return RunResult(run_id=f"fake-{fake_run_research.calls}", question=question, sources=sources, claims=claims,
                     conflicts=conflicts, answer_md=answer,
                     uncertainty_notes=["Fake run, not real research."],
                     stats={"tokens": {"input": 20000, "output": 3000}, "seconds": 0.05, "nodes": len(claims)})
