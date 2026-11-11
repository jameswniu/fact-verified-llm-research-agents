#!/usr/bin/env python3
"""Emit media/results.svg, the data panel: four source-rule pass bars on the left and per-case coverage on the right.

Every value comes from tools/facts.py, which reads the one recorded live run of 2026-10-09 in evals/results/latest.json.
Coverage is the share of the points a case's answer key lists that the report states. The stability word is the
repo's own verdict on how alike three runs of one question were. A rule below 100% is drawn in rust.

    python3 tools/render_panel.py --write | --check
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import facts  # noqa: E402
import palette as P  # noqa: E402

OUT = os.path.join(P.ROOT, "media", "results.svg")
W, H = 1200, 740
TINT = ' fill-opacity="0.25"'
LABELS = {
    "tier": "Not on a wiki or social site alone",
    "independence": "Two independent domains, unofficial",
    "quote_on_page": "The quote is on the cited page",
    "quote_not_claim": "The quote is not the claim text",
}


def bar(out, x, y, w, frac, color):
    out.append(P.rect(x, y, w, 22, "none", P.EDGE))
    out.append(P.rect(x, y, round(w * frac, 1), 22, color, color, extra=TINT))


def build():
    _, f = facts.load()
    label = (f"Recorded from one live run on {f['eval_date']}. Source rules: tier {f['rules']['tier'][0]} of {f['rules']['tier'][1]}, "
             f"independence {f['rules']['independence'][0]} of {f['rules']['independence'][1]}, quote on page "
             f"{f['rules']['quote_on_page'][0]} of {f['rules']['quote_on_page'][1]}, quote not the claim "
             f"{f['rules']['quote_not_claim'][0]} of {f['rules']['quote_not_claim'][1]}. Coverage by case from "
             f"{min(c['coverage'] for c in f['per_case'])} to {max(c['coverage'] for c in f['per_case'])} percent.")
    o = [P.svg_open(W, H, label)]
    o.append(P.t(40, 60, "Source and quote rules", 26, P.INK, bold=True, inner=500))
    o.append(P.t(40, 94, "Passes out of items checked", 23, P.MUTED, inner=500))
    y = 150
    for k in facts.RULE_KEYS:
        ok, n = f["rules"][k]
        col = P.GOOD if ok == n else P.BAD
        o.append(P.t(40, y, LABELS[k], 23, P.INK, inner=520))
        bar(o, 40, y + 16, 330, ok / n, col)
        o.append(P.t(386, y + 36, f"{ok}/{n}", 24, col if ok != n else P.INK, bold=True, inner=160))
        y += 100
    o.append(P.line(580, 40, 580, H - 90))
    rx = 620
    o.append(P.t(rx, 60, "Coverage by case", 26, P.INK, bold=True, inner=540))
    o.append(P.t(rx, 94, "Share of answer-key points stated", 23, P.MUTED, inner=540))
    y = 150
    for c in f["per_case"]:
        o.append(P.t(rx, y, c["title"], 23, P.INK, inner=540))
        bar(o, rx, y + 14, 260, c["coverage"] / 100, P.ACCENT)
        o.append(P.t(rx + 276, y + 32, f"{c['coverage']}%", 23, P.INK, bold=True, inner=70))
        vcol = P.BAD if c["verdict"] == "Unstable" else P.MUTED
        o.append(P.t(rx + 340, y + 32, c["verdict"], 23, vcol, inner=200))
        y += 64
    o.append(P.t(40, H - 56, f"All cases: coverage {f['coverage_pct']}%, conflict found {f['conflict_hit_pct']}%.", 24, P.INK, inner=1100))
    o.append(P.t(40, H - 22, f"Recorded from one live run on {f['eval_date']}, not rerun.", 23, P.MUTED, inner=1100))
    o.append("</svg>\n")
    return "\n".join(o)


if __name__ == "__main__":
    sys.exit(P.run(sys.argv[1:], OUT, build))
