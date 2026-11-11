#!/usr/bin/env python3
"""Emit media/hero.svg, the title banner with three headline numbers from the one recorded eval run.

Every number comes from tools/facts.py, which reads evals/results/latest.json (one live run on 2026-10-09, not rerun).

    python3 tools/render_hero.py --write    regenerate
    python3 tools/render_hero.py --check    exit 1 with a diff if the committed file drifted
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import facts  # noqa: E402
import palette as P  # noqa: E402

OUT = os.path.join(P.ROOT, "media", "hero.svg")
W, H = 1200, 496
M = 48


def build():
    _, f = facts.load()
    label = (f"Deep research agent. Recorded from one live run on {f['eval_date']}: {f['runs_ok']} of {f['runs']} runs "
             f"completed, {f['cit_valid']} of {f['cit_checked']} citations valid, median {f['p50']} seconds to a report, "
             f"estimated {f['cost']} per run.")
    out = [P.svg_open(W, H, label)]
    inner = W - 2 * M
    out.append(P.rect(0, 0, 8, H, P.ACCENT))
    out.append(P.t(M, 54, "DEEP RESEARCH AGENT", 23, P.MUTED, spacing=2, inner=inner))
    out.append(P.t(M, 112, "Every claim points at a source", 44, P.INK, bold=True, inner=inner))
    out.append(P.t(M, 160, "Plans, searches, verifies, then writes a cited PDF and a trace PDF.", 25, P.MUTED, inner=inner))
    top, ch, gap = 196, 172, 24
    w = (inner - 2 * gap) // 3
    cards = [
        (f"{f['runs_ok']} / {f['runs']}", f"runs done, {f['cases']} cases", P.GOOD),
        (f"{f['cit_valid']} / {f['cit_checked']}", f"citations valid, {f['cit_pct']}%", P.GOOD),
        (f"{f['p50']} s", "median to report", P.ACCENT),
    ]
    x = M
    for big, cap, col in cards:
        out.append(P.rect(x, top, w, ch, P.PANEL, P.EDGE))
        out.append(P.rect(x, top, w, 4, col))
        out.append(P.t(x + 22, top + 72, big, 52, P.INK, bold=True, inner=w - 44))
        out.append(P.t(x + 22, top + 116, cap, 24, P.MUTED, inner=w - 44))
        x += w + gap
    out.append(P.t(M + 2 * (w + gap) + 22, top + 150, f"95th percentile {f['p95']} s", 23, P.MUTED, inner=w - 44))
    out.append(P.t(M, 404, f"Recorded from one live run on {f['eval_date']}, not rerun.", 24, P.MUTED, inner=inner))
    out.append(P.t(M, 434, f"Cost is about {f['cost']} per run, estimated at list prices.", 24, P.MUTED, inner=inner))
    out.append(P.t(M, 470, "python3 tools/facts.py", 23, P.MUTED, mono=True, inner=inner))
    out.append("</svg>\n")
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(P.run(sys.argv[1:], OUT, build))
