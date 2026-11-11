#!/usr/bin/env python3
"""Emit media/pipeline.svg, a map of one research run from question to the two PDFs.

Labels use tools/facts.py: the number of lenses (angles the planner asks about), the parallel worker count and the
follow-up round limit.

    python3 tools/render_map.py --write | --check
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import facts  # noqa: E402
import palette as P  # noqa: E402

OUT = os.path.join(P.ROOT, "media", "pipeline.svg")
W = 1200
X0, BW, GAP, BH = 40, 250, 40, 130


def col_x(i):
    return X0 + i * (BW + GAP)


def arrow(x, y, direction, color=P.MUTED):
    """A small filled triangle whose tip is at (x, y), pointing right, left or down."""
    s = 9
    pts = {"r": [(x, y), (x - 2 * s, y - s), (x - 2 * s, y + s)],
           "l": [(x, y), (x + 2 * s, y - s), (x + 2 * s, y + s)],
           "d": [(x, y), (x - s, y - 2 * s), (x + s, y - 2 * s)],
           "u": [(x, y), (x - s, y + 2 * s), (x + s, y + 2 * s)]}[direction]
    return f'<polygon points="{" ".join(f"{a},{b}" for a, b in pts)}" fill="{color}"/>'


def box(out, x, y, title, l1, l2, stroke=P.EDGE, sw=2, foot=None):
    out.append(P.rect(x, y, BW, BH, P.PANEL, stroke, sw=sw))
    out.append(P.t(x + 16, y + 40, title, 24, P.INK, bold=True, inner=BW - 32))
    out.append(P.t(x + 16, y + 78, l1, 23, P.MUTED, inner=BW - 32))
    out.append(P.t(x + 16, y + 108, l2, 23, P.MUTED, inner=BW - 32))


def build():
    _, f = facts.load()
    out = [P.svg_open(W, 760, f"Pipeline of one run: question, clarity check, plan with {f['lenses']} lenses, parallel research "
                              f"{f['workers']} at a time, ledger, up to {f['rounds']} follow-up rounds that loop back to research, "
                              "verifier, writer, then report.pdf and trace.pdf.")]
    out.append(P.rect(0, 0, 8, 760, P.ACCENT))
    out.append(P.t(40, 56, "HOW ONE RUN WORKS", 23, P.MUTED, spacing=2, inner=400))
    out.append(P.t(40, 112, "Question in, two PDFs out", 44, P.INK, bold=True, inner=1100))
    out.append(P.t(40, 156, "Follow-up rounds loop back until the budget or new evidence runs out.", 24, P.MUTED, inner=1120))

    y1, y2, y3 = 190, 390, 590
    row1 = [("Question", "Plain text,", "optional PDF", P.EDGE),
            ("Clarity check", "Asks only when", "it is unclear", P.EDGE),
            ("Plan", f"{f['lenses']} lenses,", "sub-questions", P.ACCENT),
            ("Research", f"{f['workers']} at a time,", "Gemini search", P.ACCENT)]
    for i, (a, b, c, col) in enumerate(row1):
        box(out, col_x(i), y1, a, b, c, col, 3 if col == P.ACCENT else 2)
        if i < 3:
            out.append(P.line(col_x(i) + BW, y1 + BH // 2, col_x(i + 1) - 18, y1 + BH // 2))
            out.append(arrow(col_x(i + 1), y1 + BH // 2, "r"))
    # row 2 runs right to left, directly under research
    row2 = [(3, "Ledger", "Merges claims,", "flags conflicts", P.EDGE),
            (2, "Follow-up", f"Up to {f['rounds']} rounds,", "chases gaps", P.ACCENT),
            (1, "Verifier", "Source rules and", "a quote check", P.ACCENT),
            (0, "Writer", "Cited answer,", "passed claims", P.EDGE)]
    for k, (i, a, b, c, col) in enumerate(row2):
        box(out, col_x(i), y2, a, b, c, col, 3 if col == P.ACCENT else 2)
        if k < 3:
            out.append(P.line(col_x(i), y2 + BH // 2, col_x(i - 1) + BW + 18, y2 + BH // 2))
            out.append(arrow(col_x(i - 1) + BW, y2 + BH // 2, "l"))
    # research to ledger
    cx = col_x(3) + BW // 2
    out.append(P.line(cx, y1 + BH, cx, y2 - 18))
    out.append(arrow(cx, y2, "d"))
    # the loop from follow-up back up into research
    lx, tx, ym = col_x(2) + BW // 2, col_x(3) + 60, (y1 + BH + y2) // 2
    out.append(P.line(lx, y2, lx, ym, P.ACCENT, dash="8 6"))
    out.append(P.line(lx, ym, tx, ym, P.ACCENT, dash="8 6"))
    out.append(P.line(tx, ym, tx, y1 + BH + 18, P.ACCENT, dash="8 6"))
    out.append(arrow(tx, y1 + BH, "u", P.ACCENT))
    out.append(P.t(lx + 16, ym - 12, "new leads, gaps", 23, P.ACCENT, inner=tx - lx - 20))
    # outputs under the writer
    wx = col_x(0) + BW // 2
    out.append(P.line(wx, y2 + BH, wx, y3 - 18))
    out.append(arrow(wx, y3, "d", P.GOOD))
    for i, name in enumerate(("report.pdf", "trace.pdf")):
        out.append(P.rect(col_x(i), y3, BW, 70, P.PANEL, P.GOOD))
        out.append(P.t(col_x(i) + BW // 2, y3 + 44, name, 24, P.INK, mono=True, anchor="middle", inner=BW - 32))
    out.append(P.line(col_x(0) + BW, y3 + 35, col_x(1) - 18, y3 + 35, P.GOOD))
    out.append(arrow(col_x(1), y3 + 35, "r", P.GOOD))
    out.append(P.t(40, 726, "python3 tools/render_map.py --check", 23, P.MUTED, mono=True, inner=1100))
    out.append("</svg>\n")
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(P.run(sys.argv[1:], OUT, build))
