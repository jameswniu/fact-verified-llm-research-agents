"""Re-score finished runs against live pages without re-running the agent.

    python -m evals.rescore <results dir or runs dir> [--no-url-check] [--workers 6]

A results dir holds raw_results.json and runs.json from evals.suite. A runs dir holds one folder per run with
result.json, events.jsonl and the PDFs, which is what the agent writes as it goes. Writes rescored.md and
rescored.json into the directory.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from research.models import Claim, Conflict, Evidence, RunResult, Source

from .cases import CASES
from .scoring import Fetcher, aggregate, score_run
from .suite import pdf_pages, render_tables

BY_QUESTION = {c.question.strip(): c for c in CASES}


def to_result(d: dict) -> RunResult:
    return RunResult(
        run_id=d.get("run_id", ""), question=d.get("question", ""),
        sources=[Source(**s) for s in d.get("sources", [])],
        claims=[Claim(**{**c, "evidence": [Evidence(**e) for e in c.get("evidence", [])]}) for c in d.get("claims", [])],
        conflicts=[Conflict(**x) for x in d.get("conflicts", [])],
        answer_md=d.get("answer_md", ""), uncertainty_notes=list(d.get("uncertainty_notes", [])),
        stats=d.get("stats", {}))


def pdf_info(run_dir: Path) -> dict:
    """Page counts and times for report.pdf and trace.pdf, measured from the first event of the run."""
    out = {"report_exists": False, "report_pages": None, "report_s": None, "trace_exists": False, "trace_s": None}
    try:
        first = json.loads((run_dir / "events.jsonl").read_text().splitlines()[0])
        t0 = datetime.fromisoformat(first["ts"]).timestamp() - float(first.get("t", 0))
    except Exception:  # noqa: BLE001
        t0 = None
    for key in ("report", "trace"):
        p = run_dir / f"{key}.pdf"
        if p.exists() and p.stat().st_size > 1000 and p.read_bytes()[:4] == b"%PDF":
            out[f"{key}_exists"] = True
            out[f"{key}_s"] = round(p.stat().st_mtime - t0, 1) if t0 else None
    if out["report_exists"]:
        out["report_pages"] = pdf_pages(run_dir / "report.pdf")
    return out


def load_runs(d: Path):
    """Yield (case, repeat, RunResult, seconds, pdf dict)."""
    if (d / "raw_results.json").exists():
        raw = json.loads((d / "raw_results.json").read_text())
        old = {(r["case"], r["repeat"]): r for r in json.loads((d / "runs.json").read_text())["runs"] if "case" in r}
        from .cases import BY_ID
        for key, rd in raw.items():
            cid, rep = key.rsplit("#", 1)
            prev = old.get((cid, int(rep)), {})
            yield BY_ID[cid], int(rep), to_result(rd), prev.get("seconds", 0.0) or 0.0, prev.get("pdf", {})
        return
    seen: dict = {}
    for sub in sorted(p for p in d.iterdir() if (p / "result.json").exists()):
        rd = json.loads((sub / "result.json").read_text())
        case = BY_QUESTION.get(str(rd.get("question", "")).strip())
        if case is None:
            continue
        rep = seen.get(case.id, 0)
        seen[case.id] = rep + 1
        pdf = pdf_info(sub)
        secs = pdf["report_s"] if pdf["report_s"] is not None else float((rd.get("stats") or {}).get("seconds", 0.0))
        yield case, rep, to_result(rd), secs, pdf


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--no-url-check", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args(argv)
    d = Path(args.dir)
    fetcher = Fetcher(timeout=6.0)
    jobs = list(load_runs(d))
    if not jobs:
        print("no runs found", file=sys.stderr)
        return 1

    def go(j):
        case, rep, res, secs, pdf = j
        sc = score_run(case, res, secs, fetcher, not args.no_url_check)
        sc.update(case=case.id, repeat=rep, pdf=pdf, run_id=res.run_id)
        print(f"{case.id} #{rep}: citations {sc['citations']} rules {sc['rules']['quote_on_page']}", flush=True)
        return sc

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        scored = list(pool.map(go, jobs))
    by_case: dict = {}
    for sc in scored:
        by_case.setdefault(sc["case"], []).append(sc)
    cases = [c for c in CASES if c.id in by_case]
    aggs = [aggregate(c, sorted(by_case[c.id], key=lambda r: r["repeat"])) for c in cases]
    reps = max(len(v) for v in by_case.values())
    clar = []
    if (d / "runs.json").exists():
        clar = json.loads((d / "runs.json").read_text()).get("clarify", [])
    md = render_tables(aggs, scored, clar, reps, 2.0, not args.no_url_check, False)
    (d / "rescored.md").write_text(md, encoding="utf-8")
    (d / "rescored.json").write_text(json.dumps({"aggregate": aggs, "runs": scored, "clarify": clar},
                                               indent=2, default=str), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
