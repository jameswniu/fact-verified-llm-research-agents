"""Text helpers for the PDF report: fonts, glyph-safe cleaning, and a small Markdown renderer.

Used only by research/report.py. Everything here degrades to plain text instead of raising,
so one odd character or unbalanced asterisk in a model answer never costs a run its PDF.
"""
from __future__ import annotations

import os
import re
import unicodedata
from typing import Callable

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, Paragraph, Spacer, Table, TableStyle

FONT, FONT_B, FONT_I, FONT_BI, FONT_MONO = "Vera", "VeraBd", "VeraIt", "VeraBI", "Courier"

_SUPPORTED: set[int] = set()
# Code points the bundled font lacks, mapped to plain text. Keys are ints on purpose.
_FALLBACK: dict[int, str] = {
    0x2192: "->", 0x2190: "<-", 0x2194: "<->", 0x21D2: "=>", 0x2713: "yes", 0x2714: "yes",
    0x2717: "no", 0x2718: "no", 0x00A0: " ", 0x2009: " ", 0x202F: " ", 0x200B: "", 0x200C: "",
    0x200D: "", 0xFEFF: "", 0x2011: "-",
}
# Greek is missing from the bundled font, and economics text is full of it
for _ch, _name in zip("\u03b1\u03b2\u03b3\u03b4\u03b5\u03b6\u03b7\u03b8\u03ba\u03bb\u03bc\u03bd\u03be\u03c0\u03c1\u03c3\u03c4\u03c6\u03c7\u03c8\u03c9",
                      "alpha beta gamma delta epsilon zeta eta theta kappa lambda mu nu xi pi rho sigma tau phi chi psi omega".split()):
    _FALLBACK[ord(_ch)] = _name
for _ch, _name in zip("\u0393\u0394\u0398\u039b\u039e\u03a0\u03a3\u03a6\u03a8\u03a9", "Gamma Delta Theta Lambda Xi Pi Sigma Phi Psi Omega".split()):
    _FALLBACK[ord(_ch)] = _name
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def register_fonts() -> None:
    """Register the Bitstream Vera family that ships inside reportlab (no system fonts needed)."""
    global _SUPPORTED
    if _SUPPORTED:
        return
    import reportlab

    folder = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    for name, fname in ((FONT, "Vera.ttf"), (FONT_B, "VeraBd.ttf"), (FONT_I, "VeraIt.ttf"), (FONT_BI, "VeraBI.ttf")):
        pdfmetrics.registerFont(TTFont(name, os.path.join(folder, fname)))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_B, italic=FONT_I, boldItalic=FONT_BI)
    _SUPPORTED = set(pdfmetrics.getFont(FONT).face.charToGlyph.keys())


def clean(text: object) -> str:
    """Make arbitrary text safe for the PDF font: map known symbols, drop the unrenderable."""
    register_fonts()
    s = "" if text is None else str(text)
    out = []
    for ch in s.replace("\r\n", "\n").replace("\r", "\n"):
        code = ord(ch)
        if ch in "\n\t":
            out.append(ch)
        elif _CTRL.match(ch):
            continue
        elif code in _FALLBACK:
            out.append(_FALLBACK[code])
        elif code in _SUPPORTED:
            out.append(ch)
        elif unicodedata.category(ch) == "Zs":
            out.append(" ")
        elif unicodedata.category(ch) in ("So", "Sk", "Cf", "Mn", "Cs", "Co"):
            continue  # emoji, joiners and stray marks are dropped rather than shown as "?"
        else:
            out.append("?")
    return "".join(out)


def esc(text: object) -> str:
    return clean(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def esc_attr(text: object) -> str:
    return esc(text).replace('"', "&quot;")


def latin1(text: str) -> str:
    return text.encode("latin-1", "replace").decode("latin-1")


def strip_tags(markup: str) -> str:
    plain = re.sub(r"<br\s*/?>", "\n", markup)
    plain = re.sub(r"<[^>]+>", "", plain)
    return plain.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")


def safe_para(markup: str, style, bullet: str | None = None) -> Paragraph:
    """Paragraph that falls back to tag-free text when the markup is malformed."""
    try:
        return Paragraph(markup, style, bulletText=bullet) if bullet else Paragraph(markup, style)
    except Exception:
        plain = esc(strip_tags(markup))
        return Paragraph(plain, style, bulletText=bullet) if bullet else Paragraph(plain, style)


def short_url(url: str, n: int = 70) -> str:
    u = re.sub(r"^https?://(www\.)?", "", str(url)).rstrip("/")
    return u if len(u) <= n else u[: n - 3] + "..."


# ---------------------------------------------------------------- inline markdown

_PH = "{}"
_PH_RE = re.compile("(\\d+)")
_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_CITE = re.compile(r"\[([^\[\]\n]{1,80})\]")
_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_ITAL_STAR = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
_ITAL_UNDER = re.compile(r"(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])")
_BARE_URL = re.compile(r"(?<![\"'>(\w])(https?://[^\s<>\]\)\"']+[^\s<>\]\)\"'.,;:!?])")


def inline(text: object, cite: Callable[[str], str | None] | None = None, link_color: str = "#1d4ed8") -> str:
    """Markdown inline to reportlab paragraph markup.

    `cite(token)` returns markup for a citation token such as "c3" or "2", or None if it is not one.
    """
    s = clean(text)
    held: list[str] = []

    def hold(markup: str) -> str:
        held.append(markup)
        return _PH.format(len(held) - 1)

    s = _CODE.sub(lambda m: hold(f'<font face="{FONT_MONO}" size="9">{esc(latin1(m.group(1)))}</font>'), s)
    s = _LINK.sub(lambda m: hold(f'<a href="{esc_attr(m.group(2))}" color="{link_color}">{_emph(_xml(m.group(1)))}</a>'), s)

    if cite:
        def cite_sub(m: re.Match) -> str:
            parts = [p.strip() for p in re.split(r"[,;]", m.group(1)) if p.strip()]
            pieces = [cite(p) for p in parts]
            if not parts or any(p is None for p in pieces):
                return m.group(0)
            return hold("[" + ", ".join(pieces) + "]")  # type: ignore[arg-type]

        s = _CITE.sub(cite_sub, s)

    s = _BARE_URL.sub(lambda m: hold(f'<a href="{esc_attr(m.group(1))}" color="{link_color}">{esc(short_url(m.group(1)))}</a>'), s)
    s = _emph(_xml(s))  # text is already cleaned; clean() again would turn the placeholders into "?"
    for _ in range(3):  # a held link label can itself contain placeholders
        s = _PH_RE.sub(lambda m: held[int(m.group(1))], s)
    return s


def _xml(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _emph(s: str) -> str:
    s = _BOLD.sub(lambda m: f"<b>{m.group(2)}</b>", s)
    s = _ITAL_STAR.sub(lambda m: f"<i>{m.group(1)}</i>", s)
    return _ITAL_UNDER.sub(lambda m: f"<i>{m.group(1)}</i>", s)


# ---------------------------------------------------------------- block markdown

_HEAD = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_HR = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_BUL = re.compile(r"^(\s*)([-*+•])\s+(.*)$")
_NUM = re.compile(r"^(\s*)(\d{1,3})[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
_TROW = re.compile(r"^\s*\|.*\|\s*$")
_TSEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def md_to_flowables(md: object, styles: dict, width: float, cite: Callable[[str], str | None] | None = None,
                    head_offset: int = 1) -> list:
    """Render Markdown to flowables. `styles` needs body, h2, h3, h4, bullet, quote, code, cell, cellh."""
    lines = clean(md).split("\n")
    out: list = []
    i, n = 0, len(lines)
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append(safe_para(inline(" ".join(p.strip() for p in para), cite), styles["body"]))
            para.clear()

    while i < n:
        line = lines[i]
        if not line.strip():
            flush(); i += 1; continue
        if line.strip().startswith("```"):
            flush(); i += 1; buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i]); i += 1
            i += 1
            code = "<br/>".join(esc(latin1(b)).replace(" ", "&nbsp;") for b in buf)
            out.append(safe_para(code, styles["code"])); continue
        m = _HEAD.match(line)
        if m:
            flush()
            lvl = min(len(m.group(1)) + head_offset, 4)
            out.append(safe_para(inline(m.group(2), cite), styles[f"h{max(lvl, 2)}"])); i += 1; continue
        if _HR.match(line):
            flush()
            out.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#d1d5db"), spaceBefore=4, spaceAfter=6))
            i += 1; continue
        if _TROW.match(line) and i + 1 < n and _TSEP.match(lines[i + 1]):
            flush(); rows = [line]; i += 2
            while i < n and _TROW.match(lines[i]):
                rows.append(lines[i]); i += 1
            out.append(_table(rows, styles, width, cite)); out.append(Spacer(1, 6)); continue
        if _QUOTE.match(line):
            flush(); buf = []
            while i < n and _QUOTE.match(lines[i]):
                buf.append(_QUOTE.match(lines[i]).group(1).strip()); i += 1  # type: ignore[union-attr]
            out.append(safe_para(inline(" ".join(buf), cite), styles["quote"])); continue
        if _BUL.match(line) or _NUM.match(line):
            flush()
            items: list[list] = []  # [indent, bullet, text]
            while i < n:
                mb, mn = _BUL.match(lines[i]), _NUM.match(lines[i])
                if mb:
                    items.append([len(mb.group(1).replace("\t", "    ")), "•", mb.group(3)])
                elif mn:
                    items.append([len(mn.group(1).replace("\t", "    ")), mn.group(2) + ".", mn.group(3)])
                elif lines[i].strip() and lines[i].startswith((" ", "\t")) and items and not _HEAD.match(lines[i]):
                    items[-1][2] += " " + lines[i].strip()
                else:
                    break
                i += 1
            base = min(it[0] for it in items)
            for indent, bullet, text in items:
                level = min((indent - base) // 2, 3)
                st = styles["bullet"] if level == 0 else _indented(styles["bullet"], level)
                out.append(safe_para(inline(text, cite), st, bullet=bullet))
            out.append(Spacer(1, 3)); continue
        para.append(line); i += 1
    flush()
    return out


def _indented(style, level: int):
    return ParagraphStyle(f"{style.name}-l{level}", parent=style, leftIndent=style.leftIndent + 14 * level,
                          bulletIndent=style.bulletIndent + 14 * level)


def _cells(row: str) -> list[str]:
    row = row.strip()
    row = row[1:] if row.startswith("|") else row
    row = row[:-1] if row.endswith("|") else row
    return [c.strip() for c in re.split(r"(?<!\\)\|", row)]


def _table(rows: list[str], styles: dict, width: float, cite) -> Table:
    grid = [_cells(r) for r in rows]
    ncol = max(len(r) for r in grid)
    grid = [r + [""] * (ncol - len(r)) for r in grid]
    weights = [max(6, min(40, max(len(r[c]) for r in grid))) for c in range(ncol)]
    scale = width / sum(weights)
    data = [[safe_para(inline(c, cite), styles["cellh" if ri == 0 else "cell"]) for c in r] for ri, r in enumerate(grid)]
    t = Table(data, colWidths=[w * scale for w in weights], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t
