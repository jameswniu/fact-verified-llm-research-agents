"""Run the whole evaluation and write the result tables (the same tables are explained in docs/evaluation.md).

    python -m research eval run [--cases a,b] [--repeats 3] [--budget-mins 3] [--workers 6]
                                [--no-url-check] [--no-clarify] [--clarify-only] [--fake] [--out evals/results]

Every research case runs N times and is scored on coverage, citation validity, conflicts found, the source and
quote rules, latency to report.pdf, and cost. The clarifying-question rules run N times as pass or fail.
Output goes to <out>/<stamp>/{runs.json,raw_results.json,results.md} and, for a real run, <out>/latest.md.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import queue
import re
import sys
import threading
import time
import traceback
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from .cases import BY_ID, CASES  # noqa: E402
from .scoring import Fetcher, aggregate, mean, score_run  # noqa: E402

MAX_REPORT_PAGES = 10


def percentile(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def pdf_pages(path: Path):
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not data.startswith(b"%PDF"):
        return None
    try:
        from pypdf import PdfReader  # type: ignore
        return len(PdfReader(io.BytesIO(data)).pages)
    except Exception:
        return len(re.findall(rb"/Type\s*/Page(?![s\w])", data))


def collect_pdfs(res, t0: float) -> dict:
    """Find report.pdf and trace.pdf for a finished run, writing report.pdf the way the CLI does if needed.
    Times come from file modification times, so they are question received to file written."""
    out = {"report_exists": False, "report_pages": None, "report_s": None, "trace_exists": False,
           "trace_s": None, "pdf_error": ""}
    try:
        from research import store
        d = store.run_dir(res.run_id)
        report, trace = d / "report.pdf", d / "trace.pdf"
        if not report.exists():
            try:
                from research import cli
                cli._render(res)
            except Exception as e:  # noqa: BLE001 - recorded as a failed check, not a crash
                out["pdf_error"] = f"{type(e).__name__}: {str(e)[:150]}"
        for key, p in (("report", report), ("trace", trace)):
            if p.exists() and p.stat().st_size > 1000 and p.read_bytes()[:4] == b"%PDF":
                out[f"{key}_exists"] = True
                out[f"{key}_s"] = round(p.stat().st_mtime - t0, 1)
        if out["report_exists"]:
            out["report_pages"] = pdf_pages(report)
    except Exception as e:  # noqa: BLE001
        out["pdf_error"] = f"{type(e).__name__}: {str(e)[:150]}"
    return out


def _pct(x):
    return "N/A" if x is None else f"{round(x * 100)}%"


def _num(x, nd=1):
    return "N/A" if x is None else f"{x:.{nd}f}"


def _frac(pair):
    a, b = pair
    return f"{a}/{b}" if b else "N/A"


def render_tables(aggs, runs, clar, repeats, budget_mins, check_urls, fake) -> str:
    """Markdown tables. Every header and body cell starts with a capital or a digit."""
    ok = [a for a in aggs if a["runs_ok"]]
    q = ["| Case | Runs ok | Coverage | Citation validity | Conflict found | Cost per run |", "|---|---|---|---|---|---|"]
    for a in aggs:
        if a["conflict_hit"] is not None:
            conf = f"{_pct(a['conflict_hit'])} (avg {_num(a['conflicts'])})"
        elif a["abstain_ok"] is not None:
            conf = f"Abstained {_pct(a['abstain_ok'])}"
        else:
            conf = f"None expected (avg {_num(a['conflicts'])})"
        cv, cn = a.get("cit_valid", 0), a.get("cit_checked", 0)
        cite = f"{_pct(cv / cn)} ({cv}/{cn})" if cn else "No quotes to check"
        q.append(f"| {a['title']} | {a['runs_ok']}/{a['runs']} | {_pct(a['coverage'])} | {cite}"
                 f" | {conf} | ${_num(a['cost_usd'], 3)} |")
    tv, tn = sum(a.get("cit_valid", 0) for a in ok), sum(a.get("cit_checked", 0) for a in ok)
    q.append(f"| **All cases** | {sum(a['runs_ok'] for a in aggs)}/{sum(a['runs'] for a in aggs)}"
             f" | {_pct(mean(a['coverage'] for a in ok))} | {_pct(tv / tn) if tn else 'N/A'} ({tv}/{tn})"
             f" | {_pct(mean(a['conflict_hit'] for a in ok))} | ${_num(mean(a['cost_usd'] for a in ok), 3)} |")

    by_case: dict = {}
    for r in runs:
        by_case.setdefault(r.get("case"), []).append(r)
    lat = ["| Case | Latency p50 (s) | Latency p95 (s) | Report pages (max) | Report within 10 pages | Trace PDF written | Trace written at (s) |",
           "|---|---|---|---|---|---|---|"]
    all_lat, all_trace = [], []
    n_pages_ok = n_trace = n_total = 0
    for a in aggs:
        rs = [r for r in by_case.get(a["case"], []) if not r.get("error")]
        ls = [r["pdf"]["report_s"] if r.get("pdf", {}).get("report_s") is not None else r.get("seconds") for r in rs]
        tr = [r["pdf"]["trace_s"] for r in rs if r.get("pdf", {}).get("trace_s") is not None]
        pages = [r["pdf"]["report_pages"] for r in rs if r.get("pdf", {}).get("report_pages") is not None]
        within = sum(1 for r in rs if (r.get("pdf", {}).get("report_pages") or 99) <= MAX_REPORT_PAGES)
        have_trace = sum(1 for r in rs if r.get("pdf", {}).get("trace_exists"))
        all_lat += ls
        all_trace += tr
        n_pages_ok += within
        n_trace += have_trace
        n_total += len(rs)
        lat.append(f"| {a['title']} | {_num(percentile(ls, 0.5), 0)} | {_num(percentile(ls, 0.95), 0)}"
                   f" | {max(pages) if pages else 'N/A'} | {within}/{len(rs)} | {have_trace}/{len(rs)}"
                   f" | {_num(percentile(tr, 0.5), 0) if tr else 'N/A'} |")
    lat.append(f"| **All cases** | {_num(percentile(all_lat, 0.5), 0)} | {_num(percentile(all_lat, 0.95), 0)} | |"
               f" {n_pages_ok}/{n_total} | {n_trace}/{n_total} | {_num(percentile(all_trace, 0.5), 0) if all_trace else 'N/A'} |")

    rl = ["| Case | No claim on wiki or social alone | Two domains when unofficial | Quote is on the page | Quote is not the claim text | Link without a quote | Pages not readable |",
          "|---|---|---|---|---|---|---|"]
    tot = {k: [0, 0] for k in ("tier", "independence", "quote_on_page", "quote_not_claim")}
    unread = linkonly = 0
    for a in aggs:
        rt = a.get("rules") or {}
        for k in tot:
            tot[k][0] += rt.get(k, [0, 0])[0]
            tot[k][1] += rt.get(k, [0, 0])[1]
        unread += a.get("unfetchable", 0)
        linkonly += a.get("link_only", 0)
        rl.append(f"| {a['title']} | {_frac(rt.get('tier', [0, 0]))} | {_frac(rt.get('independence', [0, 0]))}"
                  f" | {_frac(rt.get('quote_on_page', [0, 0]))} | {_frac(rt.get('quote_not_claim', [0, 0]))}"
                  f" | {a.get('link_only', 0)} | {a.get('unfetchable', 0)} |")
    rl.append(f"| **All cases** | {_frac(tot['tier'])} | {_frac(tot['independence'])} | {_frac(tot['quote_on_page'])}"
              f" | {_frac(tot['quote_not_claim'])} | {linkonly} | {unread} |")

    r = ["| Case | Coverage range across runs | Same points covered | Same source sites | Same numbers | Verdict |",
         "|---|---|---|---|---|---|"]
    for a in aggs:
        agree, spread = a["point_agreement"], a["coverage_spread"]
        if agree is None:
            verdict = "Too few runs"
        elif agree >= 0.8 and (spread or 0) <= 0.2:
            verdict = "Stable"
        elif agree >= 0.6:
            verdict = "Mostly stable"
        else:
            verdict = "Unstable"
        r.append(f"| {a['title']} | {_pct(spread)} wide | {_pct(agree)} | {_pct(a['source_overlap'])}"
                 f" | {_pct(a['number_agreement'])} | {verdict} |")

    parts = [f"Eval run {datetime.now():%Y-%m-%d %H:%M}, {repeats} runs per case, budget {budget_mins:g} min per run,"
             f" cited pages {'fetched live' if check_urls else 'not fetched (snippets only)'}"
             f"{', FAKE agent (offline smoke test, numbers are not real)' if fake else ''}.",
             "### Quality", "\n".join(q), "### Latency and output files", "\n".join(lat),
             "### Source and quote rules (passes out of items checked)", "\n".join(rl),
             "### Reliability across repeated runs", "\n".join(r)]
    if clar:
        c = ["| Rule | Runs passed | What it checks | First failure |", "|---|---|---|---|"]
        for row in clar:
            c.append(f"| {row['title']} | {row['passed']}/{row['runs']} | {row['rule']} | {row['first_failure'] or 'None'} |")
        parts += ["### Clarifying-question rules (pass or fail)", "\n".join(c)]
    parts.append(
        "Coverage is the share of rubric points the answer states. Citation validity is valid citations over "
        "(valid + invalid + supported claims with no citation), where valid means the quote appears on the cited "
        "page or its stored snippet. Latency is question received to report.pdf written. The trace column is when "
        "trace.pdf was written. A page that could not be read counts as not passing the quote rule. Cost is "
        "estimated from token counts at Gemini Flash list prices.")
    return "\n\n".join(parts) + "\n"


def run_suite(case_ids=None, repeats=3, budget_mins=3.0, workers=6, check_urls=True, fake=False, out_dir=None,
              clarify=True, clarify_only=False, log=print) -> dict:
    cases = [] if clarify_only else ([BY_ID[i] for i in case_ids] if case_ids else list(CASES))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(out_dir or ROOT / "evals" / "results")
    run_root = out / stamp
    run_root.mkdir(parents=True, exist_ok=True)
    if "research.store" not in sys.modules and not os.environ.get("RESEARCH_RUNS_DIR"):
        os.environ["RESEARCH_RUNS_DIR"] = str(run_root / "runs")  # keep eval traces apart from user runs
    run_research = None
    if cases:
        if fake:
            from .fakes import fake_run_research as run_research
        else:
            from research.agent import run_research
    fetcher = Fetcher()
    jobs: queue.Queue = queue.Queue()
    for case in cases:
        for i in range(repeats):
            jobs.put((case, i))
    results: dict = {}
    raw: dict = {}
    lock = threading.Lock()
    total = jobs.qsize()

    def worker():
        while True:
            try:
                case, i = jobs.get_nowait()
            except queue.Empty:
                return
            events: list = []
            t0 = time.time()
            err, res = None, None
            budget = min(case.budget_mins, budget_mins) if budget_mins else case.budget_mins
            try:
                res = run_research(case.question, [case.pdf] if case.pdf else [], budget,
                                   lambda *a, **k: events.append((a, k)), ask_fn=None)
            except BaseException as e:  # noqa: BLE001 - a crash is a result, not a reason to stop the suite
                err = f"{type(e).__name__}: {str(e)[:300]}"
                traceback.print_exc(file=sys.stderr)
            if res is not None:
                pdf = collect_pdfs(res, t0)
                wall = pdf["report_s"] if pdf["report_s"] is not None else time.time() - t0
                try:
                    sc = score_run(replace(case, budget_mins=budget), res, wall, fetcher, check_urls)
                except Exception as e:  # noqa: BLE001 - scorer bug or malformed RunResult
                    sc = {"error": f"scoring failed: {type(e).__name__}: {e}"}
                sc["pdf"] = pdf
                sc["research_seconds"] = round(time.time() - t0, 1) if pdf["report_s"] is None else None
            else:
                sc = {"error": err}
            sc.update(case=case.id, repeat=i, events=len(events), run_id=getattr(res, "run_id", None))
            with lock:
                results[(case.id, i)] = sc
                if res is not None:
                    raw[(case.id, i)] = asdict(res)
                log(f"[{len(results)}/{total}] {case.id} #{i + 1} " + (
                    f"ERROR {sc['error']}" if sc.get("error") else
                    f"cov {sc['coverage']:.0%} quotes valid {sc['citations']['valid']}/"
                    f"{sc['citations']['valid'] + sc['citations']['invalid']} {sc['seconds']}s ${sc['cost_usd']}"))

    clar_rows: list = []
    clar_thread = None
    if clarify and not fake:
        def do_clarify():
            from .clarify_cases import run_clarify_suite
            try:
                clar_rows.extend(run_clarify_suite(repeats=repeats, log=log))
            except Exception as e:  # noqa: BLE001
                log(f"clarify suite failed to run: {type(e).__name__}: {e}")
        clar_thread = threading.Thread(target=do_clarify, daemon=True)
        clar_thread.start()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, min(workers, total or 1)))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if clar_thread is not None:
        clar_thread.join()

    aggs = [aggregate(case, [results[(case.id, i)] for i in range(repeats) if (case.id, i) in results])
            for case in cases]
    runs = [results[k] for k in sorted(results)]
    md = render_tables(aggs, runs, clar_rows, repeats, budget_mins, check_urls, fake)
    payload = {"stamp": stamp, "repeats": repeats, "budget_mins": budget_mins, "fake": fake, "aggregate": aggs,
               "clarify": clar_rows, "runs": runs}
    (run_root / "runs.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (run_root / "raw_results.json").write_text(json.dumps({f"{k[0]}#{k[1]}": v for k, v in raw.items()}, default=str),
                                               encoding="utf-8")
    (run_root / "results.md").write_text(md, encoding="utf-8")
    if not fake:
        (out / "latest.md").write_text(md, encoding="utf-8")
        (out / "latest.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return {"markdown": md, "aggregate": aggs, "clarify": clar_rows, "dir": str(run_root), "payload": payload}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="research eval run", description="Run the evaluation suite.")
    ap.add_argument("--cases", help="comma-separated case ids (default all): " + ", ".join(BY_ID))
    ap.add_argument("--repeats", type=int, default=3, help="runs per case (default 3)")
    ap.add_argument("--budget-mins", type=float, default=3.0, help="cap per run in minutes (default 3)")
    ap.add_argument("--workers", type=int, default=6, help="runs in parallel (default 6)")
    ap.add_argument("--no-url-check", action="store_true", help="do not fetch cited URLs; trust stored snippets")
    ap.add_argument("--no-clarify", action="store_true", help="skip the clarifying-question rules")
    ap.add_argument("--clarify-only", action="store_true", help="run only the clarifying-question rules")
    ap.add_argument("--fake", action="store_true", help="offline smoke test with a fake agent")
    ap.add_argument("--out", help="results directory (default evals/results)")
    args = ap.parse_args(argv)
    ids = [x.strip() for x in args.cases.split(",")] if args.cases else None
    unknown = [i for i in ids or [] if i not in BY_ID]
    if unknown:
        print(f"unknown case id(s): {', '.join(unknown)}. Known: {', '.join(BY_ID)}", file=sys.stderr)
        return 2
    try:
        res = run_suite(ids, args.repeats, args.budget_mins, args.workers, not args.no_url_check, args.fake, args.out,
                        clarify=not args.no_clarify, clarify_only=args.clarify_only)
    except Exception as e:  # noqa: BLE001 - missing key, import failure
        print(f"eval failed to start: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print("\n" + res["markdown"])
    print(f"Details in {res['dir']}")
    failed = sum(a["runs"] - a["runs_ok"] for a in res["aggregate"]) + sum(
        r["runs"] - r["passed"] for r in res["clarify"])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
