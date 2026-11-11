"""Hand-made RunResult with invented content, used to develop and test the PDF report.

Every source points at example.com and every organisation is fictional. It exercises each
report feature: all three claim statuses, both claim kinds, open and resolved conflicts,
tables, unicode, markup characters, a very long URL, and an evidence link missing from the source list.

    python samples/fake_run.py [out.pdf]   (default: a temp folder)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.models import Claim, Conflict, Evidence, RunResult, Source  # noqa: E402

ANSWER = """\
# Why did Freedonia's 1970s monetary policy fail?

Freedonia's central bank held rates **below inflation** for most of the decade [c1], and wage-price
indexation turned each supply shock into a lasting rise in prices [c2, c3]. Fiscal policy was not
neutral either: deficits widened while the bank financed them [4].

## What mattered most

- Real rates were negative from 1972 to 1979 [c1].
- Indexation clauses covered *roughly two thirds* of wage contracts [c3].
- A tighter budget would have cut the funding the bank was asked to provide [c5].

## Competing readings

| Reading | Main driver | Evidence |
|---|---|---|
| Monetary | Loose policy, R&D < 5% of budget | [c1], [c2] |
| Fiscal | Deficits ≥ 6% of output | [c4], [5] |
| Supply shock | Oil price ≈ 4x in 1973 | [c6] |

> Open question: how much of the 1979 turn was policy, and how much was a change in expectations? [c7]

Use `rate - inflation` as the real rate. Symbols like {ARROW}, ✓ and 漢 may not exist in the font.
""".replace("{ARROW}", chr(0x2192))

SOURCES = [
    Source("https://example.com/freedonia/central-bank-minutes-1974", "A. Marx", "Freedonia Archive", "1974-03-02", "2026-10-09T14:31:00-07:00",
           "Minutes record the rate held at 4% while consumer prices rose 9% over the prior year."),
    Source("https://example.com/research/indexation-and-wages", "G. Chico", "Example Labour Institute", "2011-06-15", "2026-10-09T14:33:10-07:00",
           "Survey of 1970s contracts finds about two thirds carried automatic cost-of-living clauses."),
    Source("https://www.example.com/long/path/" + "segment-" * 14 + "end?query=alpha&beta=gamma", "H. Marx", "Sylvania Statistics Office", "",
           "2026-10-09T14:35:44-07:00", "Deficit table, 1970 to 1980. Values are in billions of local currency."),
    Source("https://example.com/policy/fiscal-monetary-coordination", "Z. Marx", "Example Policy Review", "2019-01-20", "2026-10-09T14:36:02-07:00", ""),
    Source("https://example.com/blog/oil-shock-myths", "", "", "2020-09-01", "2026-10-09T14:37:30-07:00",
           "Argues the oil shock explains less of the period than commonly claimed."),
]

CLAIMS = [
    Claim("c1", "Freedonia's policy rate stayed below inflation from 1972 to 1979.", "quant", "supported", 0.86, [
        Evidence(SOURCES[0].url, "rate held at 4% while consumer prices rose 9%", "supports"),
        Evidence(SOURCES[3].url, "real rates were negative through most of the decade", "supports")]),
    Claim("c2", "Indexation amplified supply shocks into persistent inflation.", "qual", "supported", 0.74, [
        Evidence(SOURCES[1].url, "automatic cost-of-living clauses fed back into wage demands", "supports")]),
    Claim("c3", "About two thirds of wage contracts were indexed.", "quant", "supported", 0.81, [
        Evidence(SOURCES[1].url, "about two thirds carried automatic cost-of-living clauses", "supports")]),
    Claim("c4", "Budget deficits exceeded 6% of output in the late 1970s.", "quant", "contested", 0.52, [
        Evidence(SOURCES[2].url, "deficit reached 7.1% in 1978", "supports"),
        Evidence("https://example.com/not-in-the-source-list", "the deficit never passed 5% on the national definition", "refutes")]),
    Claim("c5", "A tighter budget would have reduced the funding the bank was asked to provide.", "qual", "supported", 0.63, [
        Evidence(SOURCES[3].url, "monetary financing of the deficit was the binding constraint", "supports")]),
    Claim("c6", "The 1973 oil shock explains most of the price rise.", "qual", "contested", 0.41, [
        Evidence(SOURCES[4].url, "explains less of the period than commonly claimed", "refutes")]),
    Claim("c7", "Expectations shifted decisively in 1979.", "qual", "unsupported", 0.2, []),
]

CONFLICTS = [
    Conflict(["c4"], "Two sources use different deficit definitions (national vs. central-bank accounts), so 5% and 7.1% can both be right.", False),
    Conflict(["c6", "c2"], "The oil-shock reading and the indexation reading both claim to explain most of the price rise; the agent kept both as partial causes.", True),
]


def fake_result() -> RunResult:
    return RunResult(
        run_id="sample-0001", question="Why did Freedonia's 1970s monetary policy fail, and what would fiscal policy have done?",
        sources=list(SOURCES), claims=list(CLAIMS), conflicts=list(CONFLICTS), answer_md=ANSWER,
        uncertainty_notes=["Deficit figures depend on the accounting definition; no source reconciles them.",
                           "Only one source covers wage indexation, so c2 and c3 share a single point of failure.",
                           "c7 has no source and is shown as unverified."],
        stats={"tokens": 48210, "seconds": 412.6, "nodes": 14, "synthetic": True},
        assumptions=["Read 'monetary policy' as the central bank's interest-rate and money-supply choices, not exchange-rate policy.",
                     "Took the 1970s to mean 1970 to 1979 and compared Freedonia only with itself."],
    )


if __name__ == "__main__":
    from research.report import render_pdf

    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(tempfile.mkdtemp(prefix="research-fake-"), "synthetic_report.pdf")
    render_pdf(fake_result(), out)
    print(out)
