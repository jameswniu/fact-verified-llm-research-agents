"""Every number the README and the figures print, computed from the one recorded eval run in evals/results/.

The recorded run is `evals/results/latest.json`, one live run of the research agent made on 2026-10-09: 8 cases,
3 runs each, 24 runs. `latest.md` is the same run as readable tables. This file reads the JSON, reuses the repo's own
code for percentiles, means and the markdown tables (`evals.suite.percentile`, `evals.scoring.mean`,
`evals.suite.render_tables`), and refuses to run if the tables rebuilt from the JSON no longer equal `latest.md`.

Terms used here:
- aggregate: the per-case summary row stored in latest.json (one row per eval case).
- rule: one of four source and quote checks scored on every run. "tier" means no supported claim rests only on a
  wiki, forum or social site. "independence" means unofficial claims have two independent domains. "quote_on_page"
  means the quoted words appear on the cited page. "quote_not_claim" means the quote is not just the claim text.
- p50 and p95 (the median and the 95th percentile) of seconds from question to report.pdf written.

    python3 tools/facts.py        print the headline numbers
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from evals import suite  # noqa: E402
from evals.scoring import mean  # noqa: E402
from research import agent  # noqa: E402

RESULTS = REPO / "evals" / "results"
RULE_KEYS = ("tier", "independence", "quote_on_page", "quote_not_claim")
RULE_WORDS = {
    "tier": "No claim rests on a wiki or social site alone",
    "independence": "Unofficial claims have two independent domains",
    "quote_on_page": "The quote is on the cited page",
    "quote_not_claim": "The quote is not the claim text",
}


def _verdicts(tables):
    """Case title -> stability word, read from the Reliability table that suite.render_tables printed."""
    out = {}
    block = tables.split("### Reliability across repeated runs", 1)[1].split("###", 1)[0]
    for line in block.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 6 and cells[0] not in ("Case", "---"):
            out[cells[0]] = cells[5]
    return out


def load():
    """Return (raw json, facts dict). Raises SystemExit if latest.md no longer matches the JSON."""
    d = json.loads((RESULTS / "latest.json").read_text())
    md = (RESULTS / "latest.md").read_text()
    aggs, runs = d["aggregate"], d["runs"]
    per_case_runs = max(a["runs"] for a in aggs)
    tables = suite.render_tables(aggs, runs, d["clarify"], per_case_runs, 2.0, True, False)
    if tables.split("\n", 1)[1] != md.split("\n", 1)[1]:
        raise SystemExit("facts: latest.md differs from the tables rebuilt from latest.json (after the date line)")
    ok = [a for a in aggs if a["runs_ok"]]
    times = [(r["pdf"]["report_s"] if r.get("pdf") and r["pdf"].get("report_s") is not None else r["seconds"])
             for r in runs if not r.get("error")]
    rules = {k: [sum(a["rules"][k][0] for a in aggs), sum(a["rules"][k][1] for a in aggs)] for k in RULE_KEYS}
    verdicts = _verdicts(tables)
    cit_valid = sum(a["cit_valid"] for a in ok)
    cit_checked = sum(a["cit_checked"] for a in ok)
    hits = [a["conflict_hit"] for a in aggs if a["conflict_hit"] is not None]
    p50, p95 = suite.percentile(times, 0.5), suite.percentile(times, 0.95)
    cost = mean([a["cost_usd"] for a in ok])
    f = {
        "cases": len(aggs),
        "runs": sum(a["runs"] for a in aggs),
        "runs_ok": sum(a["runs_ok"] for a in aggs),
        "cit_valid": cit_valid,
        "cit_checked": cit_checked,
        "cit_pct": round(100 * cit_valid / cit_checked),
        "p50_s": p50,
        "p95_s": p95,
        "p50": f"{p50:.0f}",
        "p95": f"{p95:.0f}",
        "cost_usd": cost,
        "cost": f"${cost:.3f}",
        "coverage_pct": round(100 * mean([a["coverage"] for a in ok])),
        "conflict_hit_pct": round(100 * mean(hits)),
        "rules": rules,
        "link_only": sum(a["link_only"] for a in aggs),
        "unfetchable": sum(a["unfetchable"] for a in aggs),
        "clarify_rules": len(d["clarify"]),
        "clarify_passed": all(c["passed"] == c["runs"] for c in d["clarify"]),
        "per_case": [{"title": a["title"], "coverage": round(100 * a["coverage"]),
                      "cit_valid": a["cit_valid"], "cit_checked": a["cit_checked"],
                      "verdict": verdicts.get(a["title"], "")} for a in aggs],
        "lenses": len(agent.LENSES),
        "rounds": agent.MAX_FOLLOWUP_ROUNDS,
        "workers": agent.WORKERS,
        "eval_date": re.search(r"\d{4}-\d{2}-\d{2}", md.split("\n", 1)[0]).group(0),
    }
    return d, f


def test_counts():
    """Run the unit tests with no API key and return {ran, skipped, passed}. Slow (about 30 s), so only the checker calls it."""
    env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
    r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                       cwd=REPO, capture_output=True, text=True, env=env)
    out = r.stdout + r.stderr
    ran = int(re.search(r"Ran (\d+) tests?", out).group(1))
    m = re.search(r"skipped=(\d+)", out)
    skipped = int(m.group(1)) if m else 0
    if r.returncode != 0:
        raise SystemExit("facts: unit tests failed\n" + out[-800:])
    return {"ran": ran, "skipped": skipped, "passed": ran - skipped}


def main():
    _, f = load()
    print(f"recorded {f['eval_date']}, one live run, not rerun")
    print(f"runs {f['runs_ok']}/{f['runs']} over {f['cases']} cases")
    print(f"citations {f['cit_valid']}/{f['cit_checked']} ({f['cit_pct']}%)")
    print(f"median {f['p50']} s, 95th percentile {f['p95']} s to report")
    print(f"cost {f['cost']} per run (estimated)")
    for k in RULE_KEYS:
        print(f"{RULE_WORDS[k]}: {f['rules'][k][0]}/{f['rules'][k][1]}")
    print(f"coverage {f['coverage_pct']}%, conflict found {f['conflict_hit_pct']}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
