"""Render a finished RunResult as a cited PDF report.

    render_pdf(result, "runs/<run_id>/report.pdf")

Sections: title block, answer, evidence ledger (every claim with its sources), conflicts,
uncertainty and limits, bibliography, run details. Citations such as [c1] or [2] in the answer
are clickable and jump to the ledger or the bibliography. Malformed input never stops the render.

The PDF metadata author reads "Deep research agent".
"""
from __future__ import annotations

import datetime as dt
import math
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from typing import Any
from urllib.parse import urlparse

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

from research._md import (FONT, FONT_B, FONT_BI, FONT_I, clean, esc, esc_attr, inline, md_to_flowables,
                          register_fonts, safe_para, short_url)

INK, BRAND, MUTED = "#111827", "#0f172a", "#6b7280"
RULE, LINK, XLINK = "#d1d5db", "#1d4ed8", "#047857"
STATUS = {  # label, text color, background
    "supported": ("SUPPORTED", "#166534", "#dcfce7"),
    "contested": ("CONTESTED", "#92400e", "#fef3c7"),
    "unsupported": ("UNSUPPORTED", "#991b1b", "#fee2e2"),
}
MARGIN = 0.9 * inch
WIDTH = letter[0] - 2 * MARGIN
PAGE_CAP = 10
_TRACE_NAME, _REPORT_NAME = "trace.pdf", "report.pdf"  # set by render_pdf so header links carry the real file names
MAX_EV = 2  # passages quoted per claim in the ledger; the rest are listed by source number


def _g(obj: Any, name: str, default: Any = "") -> Any:
    """Read a field from a dataclass or a dict; None counts as missing."""
    v = obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)
    return default if v is None else v


def _norm(url: Any) -> str:
    u = re.sub(r"#.*$", "", str(url or "").strip())
    return re.sub(r"^(https?://)www\.", r"\1", u, flags=re.I).rstrip("/").lower()


def _anchor(prefix: str, key: Any) -> str:
    return f"{prefix}-{re.sub(r'[^A-Za-z0-9_-]', '_', str(key))}"


def _num(v: Any) -> float | None:
    """A finite number, or None. Keeps NaN, inf and text out of the layout."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _conf(c: Any) -> float:
    f = _num(_g(c, "confidence", 0.0))
    return 0.0 if f is None else max(0.0, min(1.0, f))


def _status(c: Any) -> str:
    s = str(_g(c, "status", "unsupported")).lower()
    return s if s in STATUS else "unsupported"


def _day(stamp: Any) -> str:
    """A YYYY-MM-DD date (or a bare year) pulled out of whatever the source gave, or "" when there is none."""
    t = str(stamp or "").strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return m.group(0)
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)  # day first, as in "Sun, 26/07/1981 - 12:00"
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", t)
    return m.group(1) if m else ""


def _who(src: Any) -> str:
    """Organisation and author, leaving the author out when the organisation already says it."""
    org, author = clean(_g(src, "org", "")).strip(), clean(_g(src, "author", "")).strip()
    if author and org and author.lower() in org.lower():
        author = ""
    return ", ".join(x for x in (org, author) if x)


def _is_redirect(url: str) -> bool:
    u = str(url).lower()
    return "vertexaisearch.cloud.google.com" in u or "grounding-api-redirect" in u


def _site(src: Any, url: str) -> str:
    """Short visible name for a link. A search-engine redirect shows as unresolved instead of its raw address."""
    if _is_redirect(url):
        return f"{_who(src) or 'source'} (link unresolved)"
    return _host(url)


def _secs(v: Any) -> str:
    f = _num(v)
    if f is None:
        return str(v)
    t = int(round(f))
    return f"{t // 3600}h {t % 3600 // 60}m {t % 60}s" if t >= 3600 else f"{t // 60}m {t % 60}s" if t >= 60 else f"{t}s"


def _styles(scale: float = 1.0) -> dict[str, ParagraphStyle]:
    def P(name: str, **kw: Any) -> ParagraphStyle:
        base: dict[str, Any] = dict(fontName=FONT, fontSize=10.5, leading=15, textColor=colors.HexColor(INK))
        base.update(kw)
        base["fontSize"] *= scale
        base["leading"] *= scale
        if "bulletFontSize" in base:
            base["bulletFontSize"] *= scale
        if isinstance(base["textColor"], str):
            base["textColor"] = colors.HexColor(base["textColor"])
        return ParagraphStyle(name, **base)

    return {
        "kicker": P("kicker", fontName=FONT_B, fontSize=8.5, leading=11, textColor=LINK, spaceAfter=6),
        "title": P("title", fontName=FONT_B, fontSize=21, leading=26, textColor=BRAND, spaceAfter=8),
        "meta": P("meta", fontSize=9, leading=13, textColor=MUTED, spaceAfter=10),
        "h1": P("h1", fontName=FONT_B, fontSize=15, leading=19, textColor=BRAND, spaceBefore=20, spaceAfter=6, keepWithNext=1),
        "h2": P("h2", fontName=FONT_B, fontSize=12.5, leading=16, textColor=BRAND, spaceBefore=12, spaceAfter=4, keepWithNext=1),
        "h3": P("h3", fontName=FONT_B, fontSize=11, leading=15, spaceBefore=9, spaceAfter=3, keepWithNext=1),
        "h4": P("h4", fontName=FONT_BI, fontSize=10.5, leading=14, spaceBefore=6, spaceAfter=2, keepWithNext=1),
        "body": P("body", spaceAfter=7),
        "bullet": P("bullet", leftIndent=16, bulletIndent=4, spaceAfter=3, bulletFontName=FONT, bulletFontSize=10.5),
        "quote": P("quote", fontName=FONT_I, fontSize=10, leading=14, leftIndent=14, textColor="#374151", spaceAfter=7),
        "code": P("code", fontName="Courier", fontSize=9, leading=12, backColor="#f3f4f6", borderPadding=4, spaceAfter=8, leftIndent=4),
        "cell": P("cell", fontSize=9.5, leading=13),
        "cellh": P("cellh", fontName=FONT_B, fontSize=9.5, leading=13),
        "small": P("small", fontSize=9, leading=12.5, textColor=MUTED, spaceAfter=4),
        "chead": P("chead", fontSize=9.5, leading=13, spaceBefore=11, spaceAfter=2, keepWithNext=1),
        "claim": P("claim", spaceAfter=3, keepWithNext=1),
        "ev": P("ev", fontSize=9.5, leading=13.5, leftIndent=24, firstLineIndent=-24, spaceAfter=3),
        "src": P("src", fontSize=10, leading=14, leftIndent=30, firstLineIndent=-30, spaceBefore=7, keepWithNext=1),
        "srcdet": P("srcdet", fontSize=9, leading=12.5, leftIndent=30, textColor=MUTED, spaceAfter=1),
        "note": P("note", fontSize=10, leading=14, leftIndent=16, firstLineIndent=-12, spaceAfter=4),
    }


class _Ctx:
    """Everything derived from the result that several sections share."""

    def __init__(self, r: Any) -> None:
        self.r = r
        self.sources: list[Any] = list(_g(r, "sources", []) or [])
        self.claims: list[Any] = list(_g(r, "claims", []) or [])
        self.conflicts: list[Any] = list(_g(r, "conflicts", []) or [])
        self.index: dict[str, int] = {}
        for i, s in enumerate(self.sources, 1):
            self.index.setdefault(_norm(_g(s, "url", "")), i)
        self.synthetic_srcs: set[int] = set()
        self.cited_by: dict[int, list[str]] = defaultdict(list)
        self.claim_by_id = {str(_g(c, "id", i)).lower(): c for i, c in enumerate(self.claims, 1)}
        self.claims_by_source: dict[int, list[Any]] = defaultdict(list)
        self.no_url_evidence = 0
        for c in self.claims:
            for ev in _g(c, "evidence", []) or []:
                n = self.number(_g(ev, "source_url", ""))
                if n is None:
                    self.no_url_evidence += 1
                elif str(_g(c, "id", "")) not in self.cited_by[n]:
                    self.cited_by[n].append(str(_g(c, "id", "")))
                    self.claims_by_source[n].append(c)
        self.is_sample = bool(_g(_g(r, "stats", {}), "synthetic", False)) or str(_g(r, "run_id", "")).startswith("sample")

    def number(self, url: Any) -> int | None:
        """Bibliography number for a url, adding a placeholder entry when the source list lacks it."""
        key = _norm(url)
        if not key:
            return None
        if key not in self.index:
            self.sources.append({"url": str(url).strip()})
            self.index[key] = len(self.sources)
            self.synthetic_srcs.add(len(self.sources))
        return self.index[key]

    def cite(self, token: str) -> str | None:
        tok = token.strip().lstrip("^")
        c = self.claim_by_id.get(tok.lower())
        if c is not None:
            return f'<a href="#{_anchor("claim", _g(c, "id", tok))}" color="{XLINK}">{esc(tok)}</a>'
        m = re.fullmatch(r"(?:s|src|source)?\s*(\d{1,3})", tok, flags=re.I)
        if m and 1 <= int(m.group(1)) <= len(self.sources):
            n = int(m.group(1))
            return f'<a href="#{_anchor("src", n)}" color="{XLINK}">{n}</a>'
        return None


def _host(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h or short_url(url, 40)


def _heading(text: str, level: int, st: dict, anchor: str = "") -> Paragraph:
    mark = f'<a name="{anchor}"/>' if anchor else ""
    p = safe_para(mark + esc(text), st[f"h{level}"])
    p._outline = (clean(text), level - 1)  # type: ignore[attr-defined]
    return p


def _chip(label: str, fg: str, bg: str) -> str:
    return f'<font face="{FONT_B}" size="8" color="{fg}" backColor="{bg}">&nbsp;{label}&nbsp;</font>'


def _glance(ctx: _Ctx, st: dict, cited: int | None = None) -> Table:
    n = Counter(_status(c) for c in ctx.claims)
    open_c = sum(1 for c in ctx.conflicts if not _g(c, "resolved", False))
    kept = n["supported"] + n["contested"]
    src = (f"{cited} of {len(ctx.sources)}", "sources cited") if cited is not None else (len(ctx.sources), "sources consulted")
    cells = [(kept, "claims kept", INK), (n["supported"], "supported", "#166534"), (n["contested"], "contested", "#92400e"),
             (n["unsupported"], "dropped, no source", "#991b1b"), (f"{open_c}/{len(ctx.conflicts)}", "conflicts open", INK),
             (src[0], src[1], INK)]
    row = [[Paragraph(f'<font face="{FONT_B}" size="17" color="{col}">{v}</font>', st["small"]),
            Paragraph(label, st["small"])] for v, label, col in cells]
    t = Table([row], colWidths=[WIDTH / len(cells)] * len(cells))
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f4f6")),
                           ("LINEAFTER", (0, 0), (-1, -2), 0.5, colors.white),
                           ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                           ("LEFTPADDING", (0, 0), (-1, -1), 9), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def _evidence_line(evs: list, ctx: _Ctx, st: dict, qmax: int = 240) -> Paragraph:
    """One line for evidence entries that share a quote: the sites, then the quote once."""
    quote = clean(_g(evs[0], "quote", "")).strip()
    quote = quote if len(quote) <= qmax else quote[: qmax - 3] + "..."
    refutes = str(_g(evs[0], "stance", "supports")).lower() == "refutes"
    sites = []
    for ev in evs[:6]:
        url = str(_g(ev, "source_url", ""))
        n = ctx.number(url)
        if not n:
            sites.append("[no source]")
            continue
        label = esc(_site(ctx.sources[n - 1], url))
        link = f'<a href="{esc_attr(url)}" color="{LINK}">{label}</a>' if url else label
        sites.append(f'<a href="#{_anchor("src", n)}" color="{XLINK}">[{n}]</a> {link}')
    head = ", ".join(sites) + (f" +{len(evs) - 6} more" if len(evs) > 6 else "")
    body = (f'<font face="{FONT_I}">Page quote &ldquo;{esc(quote)}&rdquo;</font>' if quote
            else f'<font color="{MUTED}"><i>page not opened or no matching passage</i></font>')
    chip = " &nbsp;" + _chip("REFUTES", "#991b1b", "#fee2e2") if refutes else ""
    return safe_para(f"{head} &nbsp;{body}{chip}", st["ev"])


def _claim_block(c: Any, ctx: _Ctx, st: dict, max_ev: int = MAX_EV, qmax: int = 240) -> list:
    cid = str(_g(c, "id", "?"))
    label, fg, bg = STATUS[_status(c)]
    kind = "QUANTITATIVE" if str(_g(c, "kind", "qual")).lower() == "quant" else "QUALITATIVE"
    evidence = list(_g(c, "evidence", []) or [])
    opened = sum(1 for e in evidence if clean(_g(e, "quote", "")).strip())
    conf = _conf(c)
    level = "High" if conf >= 0.75 else "Medium" if conf >= 0.5 else "Low"
    basis = f"{len(evidence)} source{'s' if len(evidence) != 1 else ''}, {opened} page{'s' if opened != 1 else ''} opened" if evidence else "no sources"
    head = (f'<a name="{_anchor("claim", cid)}"/><b>{esc(cid)}</b> &nbsp;{_chip(label, fg, bg)} &nbsp;'
            f'<font color="{MUTED}">{kind} · confidence {level} · {basis}</font>')
    text = clean(_g(c, "text", "")).strip() or "(empty claim)"
    out = [safe_para(head, st["chead"]), safe_para(inline(text, ctx.cite), st["claim"])]
    groups: dict[tuple, list] = {}
    for e in evidence:
        key = (re.sub(r"\s+", " ", clean(_g(e, "quote", "")).strip().lower()), str(_g(e, "stance", "supports")).lower())
        groups.setdefault(key, []).append(e)
    glist = list(groups.items())
    refs = [g for k, g in glist if k[1] == "refutes"]
    sups = [g for k, g in glist if k[1] != "refutes"]
    shown = (refs[: max_ev // 2 or 1] + sups[: max(1, max_ev - len(refs[: max_ev // 2 or 1]))]) if refs else sups[:max_ev]
    for grp in shown:
        out.append(_evidence_line(grp, ctx, st, qmax))
    rest = [e for g in (refs + sups) if g not in shown for e in g]
    if rest:
        nums = sorted({n for n in (ctx.number(_g(e, "source_url", "")) for e in rest) if n})
        links = ", ".join(f'<a href="#{_anchor("src", n)}" color="{XLINK}">[{n}]</a>' for n in nums) or "no source link"
        out.append(safe_para(f'<font color="{MUTED}">+{len(rest)} more source{"s" if len(rest) > 1 else ""}:</font> {links}', st["ev"]))
    if not evidence:
        out.append(safe_para('<font color="#991b1b">No source recorded for this claim. Treat it as unverified.</font>', st["ev"]))
    elif _status(c) == "supported" and not any(str(_g(e, "stance", "supports")).lower() == "supports" for e in evidence):
        out.append(safe_para('<font color="#991b1b">Marked supported, but no evidence line supports it.</font>', st["ev"]))
    return out


def _ledger(ctx: _Ctx, st: dict, max_ev: int = MAX_EV, qmax: int = 240) -> list:
    if not ctx.claims:
        return [safe_para("The agent recorded no claims for this run.", st["body"])]
    out = [safe_para("Every claim the agent kept, strongest first within each group. Sites that share a quote are listed together. "
                     "A source number jumps to the source list, a site name opens the page. A quote appears only where the page "
                     "was opened and a sentence on it matched the claim. Claims with no source are shown, not hidden.", st["small"])]
    groups: dict[str, list] = defaultdict(list)
    for c in ctx.claims:
        groups[_status(c)].append(c)
    for key in ("supported", "contested", "unsupported"):
        if groups[key]:
            out.append(_heading(f"{STATUS[key][0].capitalize()} ({len(groups[key])})", 2, st))
            for c in sorted(groups[key], key=lambda c: -_conf(c)):
                out += _claim_block(c, ctx, st, max_ev, qmax)
    return out


def _conflicts(ctx: _Ctx, st: dict) -> list:
    if not ctx.conflicts:
        return [safe_para("The agent recorded no conflicts between claims in this run.", st["body"])]
    out = []
    for i, cf in enumerate(ctx.conflicts, 1):
        resolved = bool(_g(cf, "resolved", False))
        chip = _chip("RESOLVED", "#166534", "#dcfce7") if resolved else _chip("OPEN", "#991b1b", "#fee2e2")
        ids = [str(x) for x in (_g(cf, "claim_ids", []) or [])]
        links = ", ".join(ctx.cite(x) or esc(x) for x in ids) or "no claim ids"
        out.append(safe_para(f"<b>Conflict {i}</b> &nbsp;{chip} &nbsp;<font color=\"{MUTED}\">claims</font> {links}", st["chead"]))
        out.append(safe_para(inline(clean(_g(cf, "reason", "")) or "(no reason recorded)", ctx.cite), st["claim"]))
        for x in ids:
            c = ctx.claim_by_id.get(x.lower())
            if c is not None:
                t = clean(_g(c, "text", "")).strip()
                out.append(safe_para(f"{esc(x)}: {esc(t[:160] + '...' if len(t) > 160 else t)}", st["ev"]))
    return out


def _checks(ctx: _Ctx) -> list[str]:
    """Plain-language caveats computed from the data itself, so they cannot drift from the ledger."""
    n = Counter(_status(c) for c in ctx.claims)
    notes = []
    if n["unsupported"]:
        notes.append(f"{n['unsupported']} of {len(ctx.claims)} claims have no supporting source and are listed as unverified.")
    if n["contested"]:
        notes.append(f"{n['contested']} claims are contested: sources disagree or the evidence points both ways.")
    no_ev = sum(1 for c in ctx.claims if _status(c) == "supported" and not (_g(c, "evidence", []) or []))
    if no_ev:
        notes.append(f"{no_ev} claims are marked supported but carry no evidence. Do not rely on them.")
    single = sum(1 for c in ctx.claims if _status(c) == "supported" and len({_norm(_g(e, 'source_url', '')) for e in (_g(c, 'evidence', []) or [])}) == 1)
    if single:
        notes.append(f"{single} supported claims rest on a single source.")
    low = sum(1 for c in ctx.claims if _conf(c) < 0.5 and _status(c) != "unsupported")
    if low:
        notes.append(f"{low} claims that are not marked unsupported still carry confidence below 50%.")
    open_c = sum(1 for c in ctx.conflicts if not _g(c, "resolved", False))
    if open_c:
        notes.append(f"{open_c} of {len(ctx.conflicts)} conflicts between claims were left unresolved.")
    undated = sum(1 for i, s in enumerate(ctx.sources, 1) if not _g(s, "date_written", "") and i not in ctx.synthetic_srcs)
    if undated:
        notes.append(f"{undated} of {len(ctx.sources)} sources carry no publication date, so their recency is unknown.")
    if ctx.synthetic_srcs:
        notes.append(f"{len(ctx.synthetic_srcs)} evidence links point at pages missing from the source list; they are added at the end of the bibliography.")
    if ctx.no_url_evidence:
        notes.append(f"{ctx.no_url_evidence} evidence entries have no source link.")
    return notes


def _assumptions(r: Any) -> list[str]:
    """The clarify step's assumptions (RunResult.assumptions, a list of short sentences)."""
    raw = _g(r, "assumptions", []) or []
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    out = []
    for x in items:
        t = re.sub(r"\s*Tell me if you meant something else\.?", "", clean(x), flags=re.I).strip()
        t = re.sub(r"^assuming\s+(that\s+)?", "", t, flags=re.I).strip()
        if t:
            t = t[0].upper() + t[1:]
            out.append("Scope assumed. " + (t if t.endswith((".", "!", "?")) else t + "."))
    return out


def _uncertainty(ctx: _Ctx, st: dict) -> list:
    out = []
    assumed = _assumptions(ctx.r)
    if assumed:
        out.append(safe_para("<b>Assumptions the agent made</b>", st["body"]))
        out += [safe_para(inline(a, ctx.cite), st["bullet"], bullet="•") for a in assumed]
        out.append(Spacer(1, 6))
    agent_notes = [clean(x).strip() for x in (_g(ctx.r, "uncertainty_notes", []) or []) if str(x).strip()]
    out.append(safe_para("<b>What the agent flagged</b>", st["body"]))
    for note in agent_notes or ["The agent recorded no uncertainty notes."]:
        out.append(safe_para(inline(note, ctx.cite), st["bullet"], bullet="•"))
    out.append(Spacer(1, 6))
    out.append(safe_para("<b>What the ledger shows</b>", st["body"]))
    for note in _checks(ctx) or ["No gaps found in the ledger checks."]:
        out.append(safe_para(esc(note), st["bullet"], bullet="•"))
    return out


def _sources(ctx: _Ctx, st: dict) -> list:
    if not ctx.sources:
        return [safe_para("No sources were recorded for this run.", st["body"])]
    out = []
    for n, s in enumerate(ctx.sources, 1):
        url = str(_g(s, "url", ""))
        who = _who(s) or _host(url) or "unknown source"
        written, fetched = _day(_g(s, "date_written", "")), _day(_g(s, "fetched_at", ""))
        bits = [f"written {esc(written)}" if written else "n.d."]
        if fetched:
            bits.append(f"retrieved {esc(fetched)}")
        redirect = _is_redirect(url)
        tier = _chip("UNRESOLVED", "#374151", "#e5e7eb") if redirect else (
            _chip("PRIMARY", "#166534", "#dcfce7") if _tier(url) == "primary" else _chip("SECONDARY", "#374151", "#e5e7eb"))
        head = f'<a name="{_anchor("src", n)}"/><b>[{n}]</b> &nbsp;{esc(who)} &nbsp;{tier} &nbsp;<font color="{MUTED}">{" · ".join(bits)}</font>'
        if n in ctx.synthetic_srcs:
            head += f' &nbsp;<font color="{MUTED}">(not in the agent source list)</font>'
        shown_url = _site(s, url) if redirect else short_url(url, 90)
        line2 = f'<a href="{esc_attr(url)}" color="{LINK}">{esc(shown_url)}</a>' if url else "no url"
        cites = ctx.cited_by.get(n, [])
        if cites:
            tail = f" +{len(cites) - 10} more" if len(cites) > 10 else ""
            line2 += f' &nbsp;<font color="{MUTED}">cited by</font> ' + ", ".join(ctx.cite(c) or esc(c) for c in cites[:10]) + tail
        out.append(KeepTogether([safe_para(head, st["src"]), safe_para(line2, st["srcdet"])]))
    return out


def _details(ctx: _Ctx, st: dict) -> list:
    stats = _g(ctx.r, "stats", {}) or {}
    rows = [("Run id", _g(ctx.r, "run_id", "")), ("Report generated", dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"))]
    for k, v in (stats.items() if isinstance(stats, dict) else []):
        if k == "synthetic":
            continue
        num = _num(v)
        if k == "tokens" and num is not None:
            shown = f"{int(num):,}"
        elif k == "seconds":
            shown = _secs(v)
        elif isinstance(v, dict):
            shown = ", ".join(f"{a}: {b}" for a, b in v.items())
        elif isinstance(v, (list, tuple)):
            shown = ", ".join(str(x) for x in v)
        else:
            shown = str(v)
        rows.append((str(k).replace("_", " ").capitalize(), shown))
    t = Table([[Paragraph(esc(k), st["cellh"]), Paragraph(esc(v), st["cell"])] for k, v in rows], colWidths=[1.6 * inch, WIDTH - 1.6 * inch])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor(RULE)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return [t]


def _canvas_class(header: str, run_id: str, footer_note: str, holder: dict | None = None):
    class Numbered(rl_canvas.Canvas):
        """Two-pass canvas so every page can say 'Page n of N'."""

        def __init__(self, *a: Any, **kw: Any) -> None:
            super().__init__(*a, **kw)
            self._saved: list[dict] = []
            self._marks: list[tuple] = []

        # Bookmarks and outline targets are recorded while the page is laid out and written when that page is
        # replayed in save(). Registered earlier they all point at page 1, because the real pages do not exist yet,
        # and every clickable citation number would jump to page 1.
        def bookmarkHorizontal(self, *args: Any, **kw: Any) -> None:
            self._marks.append(("bookmarkHorizontal", args, kw))

        def bookmarkPage(self, *args: Any, **kw: Any) -> None:
            self._marks.append(("bookmarkPage", args, kw))

        def showPage(self) -> None:
            self._saved.append(dict(self.__dict__))
            self._marks = []
            self._startPage()

        def save(self) -> None:
            total = len(self._saved)
            if holder is not None:
                holder["pages"] = total
            for state in self._saved:
                self.__dict__.update(state)
                self._chrome(self._pageNumber, total)
                for name, args, kw in state.get("_marks", []):
                    getattr(rl_canvas.Canvas, name)(self, *args, **kw)
                super().showPage()
            super().save()

        def _chrome(self, n: int, total: int) -> None:
            w, h = letter
            self.saveState()
            self.setFont(FONT, 8.5)
            self.setFillColor(colors.HexColor(MUTED))
            self.drawRightString(w - MARGIN, 0.5 * inch, f"Page {n} of {total}")
            if footer_note:
                self.setFillColor(colors.HexColor("#991b1b"))
                self.drawString(MARGIN, 0.5 * inch, footer_note)
            if n > 1:
                self.setFillColor(colors.HexColor(MUTED))
                self.drawString(MARGIN, h - 0.55 * inch, header)
                self.drawRightString(w - MARGIN, h - 0.55 * inch, f"run {run_id}")
                self.setStrokeColor(colors.HexColor(RULE))
                self.setLineWidth(0.5)
                self.line(MARGIN, h - 0.62 * inch, w - MARGIN, h - 0.62 * inch)
            self.restoreState()

    return Numbered


class _Doc(BaseDocTemplate):
    def afterFlowable(self, f: Any) -> None:
        o = getattr(f, "_outline", None)
        if o:
            self._outline_n = getattr(self, "_outline_n", 0) + 1
            key = f"outline{self._outline_n}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(o[0], key, o[1], 0)


def _tier(url: str) -> str:
    """primary (government, central bank, university, multilateral) or secondary (everything else)."""
    try:
        from research.agent import is_primary

        return "primary" if is_primary(url) else "secondary"
    except Exception:
        h = (urlparse(str(url)).hostname or "").lower()
        names = ("federalreserve", "nber.org", "imf.org", "bis.org", "bankofengland", "ecb.europa", "oecd.org",
                 "worldbank", "stlouisfed", "frbsf", "newyorkfed")
        return "primary" if h.endswith((".gov", ".edu", ".int", ".mil")) or any(n in h for n in names) else "secondary"


def _document(path: str, ctx: _Ctx, header: str, holder: dict, margin: float = MARGIN) -> _Doc:
    question = clean(_g(ctx.r, "question", "")).strip() or "(no question recorded)"
    run_id = clean(_g(ctx.r, "run_id", "")) or "unknown"
    doc = _Doc(path, pagesize=letter, leftMargin=margin, rightMargin=margin, topMargin=0.9 * inch, bottomMargin=0.85 * inch,
               title=question[:200], author="Deep research agent", subject=f"{header}, run {run_id}")
    frame = Frame(margin, 0.85 * inch, letter[0] - 2 * margin, letter[1] - 1.75 * inch, id="main",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="page", frames=[frame])])
    doc._holder = holder  # type: ignore[attr-defined]
    return doc


def _title_block(ctx: _Ctx, st: dict, kicker: str, extra: str = "") -> list:
    r = ctx.r
    stats = _g(r, "stats", {})
    stats = stats if isinstance(stats, dict) else {}
    meta = [f"run {clean(_g(r, 'run_id', '')) or 'unknown'}"]
    for key, fmt in (("tokens", lambda n: f"{int(n):,} tokens"), ("seconds", _secs), ("nodes", lambda n: f"{int(n)} nodes")):
        num = _num(stats.get(key))
        if num is not None:
            meta.append(fmt(num))
    out = [safe_para(kicker, st["kicker"]), safe_para(esc(clean(_g(r, "question", "")).strip() or "(no question recorded)"), st["title"]),
           safe_para(esc(" · ".join(meta)) + extra, st["meta"])]
    if ctx.is_sample:
        out += [safe_para('<font color="#991b1b"><b>Synthetic sample.</b> The data below is made up to show the report '
                          'layout. It is not research output.</font>', st["small"])]
    return out


# ------------------------------------------------------------------ report.pdf (answer only, capped)

_CITE_GROUP = re.compile(r"\[([^\[\]\n]{1,80})\](?!\()")
_SRC_TOKEN = re.compile(r"(?:s|src|source)?\s*(\d{1,3})", re.I)
_LISTI = re.compile(r"^(\s*)([-*+•]|\d{1,3}[.)])\s+")
_PROTECT = re.compile(r"disagree|conflict|contest|uncertain|unverif|assum|limit|caveat|bottom|summary|conclusion", re.I)


def _split_blocks(md: str) -> list[dict]:
    """Cut the answer into paragraphs, list items, tables and headings so low-value ones can be dropped."""
    blocks: list[dict] = []
    para: list[str] = []
    section = ""

    def add(kind: str, text: str) -> None:
        protected = kind in ("h", "table", "code") or bool(_PROTECT.search(section))
        blocks.append({"kind": kind, "text": text, "section": section, "protected": protected})

    def flush() -> None:
        if para:
            add("p", " ".join(x.strip() for x in para))
            para.clear()

    lines = md.split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            flush(); i += 1; continue
        if ln.strip().startswith("```"):
            flush(); buf = [ln]; i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i]); i += 1
            if i < len(lines):
                buf.append(lines[i]); i += 1
            add("code", "\n".join(buf)); continue
        m = re.match(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$", ln)
        if m:
            flush(); section = m.group(2); add("h", ln); i += 1; continue
        if re.match(r"^\s*\|.*\|\s*$", ln):
            flush(); buf = []
            while i < len(lines) and re.match(r"^\s*\|.*\|\s*$", lines[i]):
                buf.append(lines[i]); i += 1
            add("table", "\n".join(buf)); continue
        if _LISTI.match(ln):
            flush(); buf = [ln]; i += 1
            while i < len(lines) and lines[i].strip() and lines[i].startswith((" ", "\t")) and not _LISTI.match(lines[i]):
                buf.append(lines[i]); i += 1
            add("li", "\n".join(buf)); continue
        para.append(ln); i += 1
    flush()
    first = next((b for b in blocks if b["kind"] == "p"), None)
    if first is not None:
        first["protected"] = True  # the opening paragraph is the bottom line when the answer has no heading
    return blocks


def _join(blocks: list[dict]) -> str:
    out, prev = [], ""
    for b in blocks:
        if out:
            out.append("\n" if prev == "li" and b["kind"] == "li" else "\n\n")
        out.append(b["text"])
        prev = b["kind"]
    return "".join(out)


def _claim_sources(ctx: _Ctx, c: Any) -> list[int]:
    seen: list[int] = []
    for ev in _g(c, "evidence", []) or []:
        n = ctx.number(_g(ev, "source_url", ""))
        if n and n not in seen:
            seen.append(n)
    return seen


def _tokens_to_sources(ctx: _Ctx, group: str) -> list[int] | None:
    """Source numbers named by one bracket group, or None when the group is not a citation."""
    olds: list[int] = []
    for tok in (t.strip().lstrip("^") for t in re.split(r"[,;]", group) if t.strip()):
        c = ctx.claim_by_id.get(tok.lower())
        if c is not None:
            olds += _claim_sources(ctx, c)
            continue
        m = _SRC_TOKEN.fullmatch(tok)
        if m and 1 <= int(m.group(1)) <= len(ctx.sources):
            olds.append(int(m.group(1)))
        else:
            return None
    return olds


def _renumber(ctx: _Ctx, md: str) -> tuple[str, list[int]]:
    """Rewrite citations so they count 1, 2, 3 by first appearance. Returns the text and the old source numbers in new order."""
    order: list[int] = []

    def sub(m: re.Match) -> str:
        olds = _tokens_to_sources(ctx, m.group(1))
        if olds is None:
            return m.group(0)
        news = []
        for o in olds:
            if o not in order:
                order.append(o)
            news.append(order.index(o) + 1)
        return "[" + ", ".join(str(n) for n in sorted(set(news))) + "]" if news else ""

    return _CITE_GROUP.sub(sub, md), order


def _block_score(ctx: _Ctx, text: str) -> float:
    """Mean confidence of the claims behind a block's citations; uncited blocks score 1.0 and are dropped last."""
    confs: list[float] = []
    for m in _CITE_GROUP.finditer(text):
        for tok in (t.strip().lstrip("^") for t in re.split(r"[,;]", m.group(1)) if t.strip()):
            c = ctx.claim_by_id.get(tok.lower())
            if c is not None:
                confs.append(_conf(c))
                continue
            mm = _SRC_TOKEN.fullmatch(tok)
            if mm:
                confs += [_conf(cl) for cl in ctx.claims_by_source.get(int(mm.group(1)), [])]
    return sum(confs) / len(confs) if confs else 1.0


def _strength(ctx: _Ctx, cited_old: list[int], st: dict) -> list:
    claims = ctx.claims
    n = len(claims)
    cnt = Counter(_status(c) for c in claims)
    sup, con, uns = cnt["supported"], cnt["contested"], cnt["unsupported"]

    def sites(c: Any) -> set[str]:
        return {_host(str(_g(e, "source_url", ""))) for e in (_g(c, "evidence", []) or [])
                if str(_g(e, "stance", "supports")).lower() != "refutes" and _g(e, "source_url", "")}

    multi = sum(1 for c in claims if _status(c) == "supported" and len(sites(c)) >= 2)
    open_c = sum(1 for cf in ctx.conflicts if not _g(cf, "resolved", False))
    confs = sorted(_conf(c) for c in claims if _status(c) != "unsupported")
    med = confs[len(confs) // 2] if confs else 0.0
    primary = sum(1 for o in cited_old if _tier(str(_g(ctx.sources[o - 1], "url", ""))) == "primary")
    if n == 0:
        rating = "Not rated"
    elif sup / n >= 0.8 and sup and multi / sup >= 0.5 and open_c == 0:
        rating = "Strong"
    elif sup / n >= 0.6:
        rating = "Moderate"
    else:
        rating = "Limited"
    out: list = [safe_para(f"<b>Overall: {rating}.</b> " + esc(
        f"{sup} of {n} checked claims are backed by a cited source, {con} are contested, and {uns} were dropped for lack of one. "
        f"{multi} of the supported claims rest on two or more independent sites, and {open_c} conflicts between sources are still open."),
        st["body"])]
    cit = _g(_g(ctx.r, "stats", {}), "citations", {}) if isinstance(_g(ctx.r, "stats", {}), dict) else {}
    if isinstance(cit, dict) and _num(cit.get("total")):
        tot = int(_num(cit.get("total")) or 0)
        out.append(safe_para(esc(
            f"Each citation was checked against its page where the page could be opened: {int(_num(cit.get('page_match')) or 0)} of {tot} "
            f"matched the page text, {int(_num(cit.get('page_mismatch')) or 0)} did not, and {int(_num(cit.get('unfetchable')) or 0)} "
            f"pages could not be fetched (paywall, block or timeout)."), st["body"]))
    rows = [("Claims checked", str(n)), ("Backed by a cited source", str(sup)), ("Contested", str(con)),
            ("Dropped, no source", str(uns)), ("Supported by two or more sites", str(multi)),
            ("Primary sources among those cited", f"{primary} of {len(cited_old)}"), ("Median confidence", f"{med:.0%}")]
    t = Table([[Paragraph(esc(a), st["cell"]), Paragraph(esc(b), st["cellh"])] for a, b in rows], colWidths=[3.2 * inch, 1.6 * inch], hAlign="LEFT")
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor(RULE)), ("TOPPADDING", (0, 0), (-1, -1), 2),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("LEFTPADDING", (0, 0), (-1, -1), 2)]))
    return out + [KeepTogether([t])]


def _bibliography(ctx: _Ctx, order: list[int], st: dict, compact: bool, limit: int | None = None) -> list:
    out: list = []
    shown = order if limit is None else order[:limit]
    for i, o in enumerate(shown, 1):
        s = ctx.sources[o - 1]
        url = str(_g(s, "url", ""))
        who = _who(s)
        date = _day(_g(s, "date_written", "")) or "n.d."
        mark = f'<a name="rsrc-{i}"/><b>[{i}]</b> '
        shown_url = _site(s, url) if _is_redirect(url) else short_url(url, 78 if not compact else 64)
        link = f'<a href="{esc_attr(url)}" color="{LINK}">{esc(shown_url)}</a>' if url else "no url"
        if compact:
            label = esc(who) + " · " if who else ""
            out.append(safe_para(mark + label + link + f' <font color="{MUTED}">({esc(date)})</font>', st["bib"]))
        else:
            head = mark + (esc(who) if who else esc(_host(url))) + f' <font color="{MUTED}">({esc(date)})</font>'
            snip = " ".join(clean(_g(s, "snippet", "")).split())
            rows = [safe_para(head, st["bib"]), safe_para(link, st["bibdet"])]
            if snip:
                rows.append(safe_para(f'<font color="{MUTED}">{esc(snip[:100] + ("..." if len(snip) > 100 else ""))}</font>', st["bibdet"]))
            out.append(KeepTogether(rows))
    if limit is not None and len(order) > limit:
        out.append(safe_para(f'<font color="{MUTED}">{len(order) - limit} more cited sources are listed in trace.pdf.</font>', st["small"]))
    return out


def _report_story(ctx: _Ctx, st: dict, blocks: list[dict], compact: bool, bib_limit: int | None) -> tuple[list, int]:
    md, order = _renumber(ctx, _join(blocks))
    if not order:  # the answer carries no inline citations: fall back to the sources behind supported claims
        for c in sorted((c for c in ctx.claims if _status(c) == "supported"), key=lambda c: -_conf(c)):
            for n in _claim_sources(ctx, c):
                if n not in order:
                    order.append(n)
        order = order[:40]
        fallback = True
    else:
        fallback = False
    k = len(order)

    def cite(tok: str) -> str | None:
        m = re.fullmatch(r"\d{1,3}", tok.strip())
        if m and 1 <= int(m.group(0)) <= k:
            return f'<a href="#rsrc-{int(m.group(0))}" color="{XLINK}">{int(m.group(0))}</a>'
        return None

    story: list = _title_block(ctx, st, "DEEP RESEARCH REPORT",
                               ' · <a href="%s" color="%s">full audit trail in %s</a>' % (_TRACE_NAME, LINK, _TRACE_NAME))
    story += [_glance(ctx, st, k), _heading("Answer", 1, st, "sec-answer")]
    story += md_to_flowables(md, st, WIDTH, cite) if md.strip() else [safe_para("The agent produced no written answer.", st["body"])]
    assumed = _assumptions(ctx.r)
    if assumed:
        story += [_heading("Assumptions", 2, st)] + [safe_para(inline(a, cite), st["bullet"], bullet="•") for a in assumed]
    notes = [clean(x).strip() for x in (_g(ctx.r, "uncertainty_notes", []) or []) if str(x).strip()]
    if notes:
        story += [_heading("Limits of this run", 2, st)]
        for x in notes[:8]:
            story.append(safe_para(inline(x if len(x) <= 320 else x[:317] + "...", cite), st["bullet"], bullet="•"))
        if len(notes) > 8:
            story.append(safe_para(f'<font color="{MUTED}">{len(notes) - 8} more notes are in trace.pdf.</font>', st["small"]))
    story += [_heading("How strong the evidence is", 2, st)] + _strength(ctx, order, st)
    story += [_heading(f"Sources cited ({k})", 1, st, "sec-sources")]
    if fallback and k:
        story.append(safe_para("The answer text carries no inline citations, so these are the sources behind its supported claims.", st["small"]))
    story += _bibliography(ctx, order, st, compact, bib_limit) if k else [safe_para("No sources were cited.", st["body"])]
    return story, k


def _count_pages(path: str) -> int | None:
    try:
        from pypdf import PdfReader

        return len(PdfReader(path).pages)
    except Exception:
        return None


def _build_report(result: Any, path: str) -> int:
    """Write the answer-only report, trimming until it fits PAGE_CAP. Returns the final page count."""
    register_fonts()
    ctx = _Ctx(result)
    answer = clean(_g(result, "answer_md", "")).strip()
    blocks = _split_blocks(answer)
    scores = [_block_score(ctx, b["text"]) for b in blocks]
    note = "SYNTHETIC SAMPLE DATA" if ctx.is_sample else ""
    question = clean(_g(result, "question", "")).strip() or "(no question recorded)"
    short_q = question if len(question) <= 62 else question[:59] + "..."
    run_id = clean(_g(result, "run_id", "")) or "unknown"
    steps = [(1.0, False, MARGIN), (0.95, True, MARGIN), (0.9, True, 0.75 * inch)]  # type scale, compact bibliography, margin

    def attempt(kept: list[int], step: tuple, bib_limit: int | None = None) -> int:
        global WIDTH
        scale, compact, margin = step
        st = _styles(scale)
        st["bib"] = ParagraphStyle("bib", parent=st["small"], fontSize=8.5 * scale, leading=11.5 * scale, leftIndent=24,
                                   firstLineIndent=-24, textColor=colors.HexColor(INK), spaceAfter=1.5 if compact else 4)
        st["bibdet"] = ParagraphStyle("bibdet", parent=st["small"], fontSize=8.5 * scale, leading=11.5 * scale, leftIndent=24, spaceAfter=3)
        old_w = WIDTH
        WIDTH = letter[0] - 2 * margin
        try:
            story, _k = _report_story(ctx, st, [blocks[i] for i in kept], compact, bib_limit)
            holder: dict = {}
            doc = _document(path, ctx, "Research report", holder, margin)
            doc.build(story, canvasmaker=_canvas_class(short_q, run_id, note, holder))
        finally:
            WIDTH = old_w
        return int(holder.get("pages", 0))

    kept = list(range(len(blocks)))
    pages = 0
    for step in steps:
        pages = attempt(kept, step)
        if pages <= PAGE_CAP:
            return pages
    last = steps[-1]
    droppable = sorted((i for i in kept if not blocks[i]["protected"]), key=lambda i: (scores[i], -i))
    while pages > PAGE_CAP and droppable:
        batch, droppable = droppable[: max(1, len(droppable) // 6)], droppable[max(1, len(droppable) // 6):]
        kept = [i for i in kept if i not in batch]
        pages = attempt(kept, last)
    for limit in (60, 30, 15, 0):  # then shorten the bibliography
        if pages <= PAGE_CAP:
            break
        pages = attempt(kept, last, limit)
    tail = [i for i in reversed(kept) if blocks[i]["kind"] != "h"][:-1]  # last resort: trim protected text from the end
    while pages > PAGE_CAP and tail:
        kept.remove(tail.pop(0))
        pages = attempt(kept, last, 0)
    return pages


# ------------------------------------------------------------------ trace.pdf (everything, any length)

def _read_events(result: Any) -> list[dict]:
    try:
        from research import store

        return list(store.read_events(str(_g(result, "run_id", ""))))
    except Exception:
        return []


def _plan_tree(events: list[dict], st: dict) -> list:
    rounds: list[list] = [["Initial plan", []]]
    for ev in events:
        t, msg = ev.get("type"), clean(ev.get("msg", ""))
        if t == "round":
            rounds.append([msg, []])
        elif t == "plan":
            rounds[-1][1].append(("plan", msg))
        elif t == "search":
            if "started" in msg and ev.get("question"):
                rounds[-1][1].append(("ask", f"{ev.get('sub_question', '')} {clean(ev.get('question'))}".strip()))
            elif "finished" in msg:
                rounds[-1][1].append(("done", msg))
    out: list = []
    for title, items in rounds:
        if not items and title == "Initial plan":
            continue
        out.append(safe_para(f"<b>{esc(title)}</b>", st["chead"]))
        for kind, text in items:
            lead = {"plan": "Plan", "ask": "Ask", "done": "Result"}[kind]
            out.append(safe_para(f'<font color="{MUTED}">{lead}</font> &nbsp;{esc(text)}', st["ev"]))
    return out or [safe_para("No event log was recorded for this run, so the plan tree is unavailable.", st["body"])]


def _timeline(events: list[dict], st: dict) -> list:
    if not events:
        return [safe_para("No event log was recorded for this run.", st["body"])]
    rows = [[Paragraph("Time", st["cellh"]), Paragraph("Step", st["cellh"]), Paragraph("What happened", st["cellh"])]]
    for ev in events:
        secs = _num(ev.get("t"))
        when = f"{int(secs) // 60}:{int(secs) % 60:02d}" if secs is not None else ""
        msg = clean(ev.get("msg", ""))
        rows.append([Paragraph(esc(when), st["cell"]), Paragraph(esc(ev.get("type", "")), st["cell"]),
                     safe_para(esc(msg if len(msg) <= 400 else msg[:397] + "..."), st["cell"])])
    t = Table(rows, colWidths=[0.55 * inch, 0.85 * inch, WIDTH - 1.4 * inch], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor(RULE)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return [t]


def _verifier(ctx: _Ctx, events: list[dict], st: dict) -> list:
    cnt = Counter(_status(c) for c in ctx.claims)
    out: list = [safe_para(esc(
        f"{len(ctx.claims)} claims reached the verifier. {cnt['supported']} were kept as supported, {cnt['contested']} as contested, "
        f"and {cnt['unsupported']} were dropped because no cited page backed them."), st["body"])]
    cit = _g(_g(ctx.r, "stats", {}), "citations", {}) if isinstance(_g(ctx.r, "stats", {}), dict) else {}
    if isinstance(cit, dict) and cit:
        out.append(safe_para("Citation checks: " + esc(", ".join(f"{k.replace('_', ' ')} {v}" for k, v in cit.items())) + ".", st["body"]))
    warn = [clean(e.get("msg", "")) for e in events if e.get("type") == "warning"]
    for w in warn:
        out.append(safe_para(f'<font color="#92400e">Warning:</font> {esc(w)}', st["ev"]))
    dropped = [c for c in ctx.claims if _status(c) == "unsupported"]
    if dropped:
        out.append(safe_para("<b>Dropped claims</b>", st["chead"]))
        for c in dropped:
            out.append(safe_para(f"<b>{esc(_g(c, 'id', '?'))}</b> &nbsp;{esc(clean(_g(c, 'text', '')))}", st["ev"]))
    return out


def _trace_sources(ctx: _Ctx, st: dict) -> list:
    out = _sources(ctx, st)
    return out


def _build_trace(result: Any, path: str) -> int:
    register_fonts()
    st = _styles()
    ctx = _Ctx(result)
    events = _read_events(result)
    question = clean(_g(result, "question", "")).strip() or "(no question recorded)"
    short_q = question if len(question) <= 62 else question[:59] + "..."
    run_id = clean(_g(result, "run_id", "")) or "unknown"
    sources_part = _sources(ctx, st)
    ledger_part = _ledger(ctx, st, max_ev=99, qmax=700)
    story: list = _title_block(ctx, st, "RUN TRACE", ' · <a href="%s" color="%s">answer in %s</a>' % (_REPORT_NAME, LINK, _REPORT_NAME))
    story += [_glance(ctx, st)]
    from copy import copy

    loose = dict(st)
    loose["h1"] = copy(st["h1"])
    loose["h1"].keepWithNext = 0  # keep the stats heading on page 1 even when its table does not fit beside it
    story += [_heading("Budget, tokens and time", 1, loose)] + _details(ctx, st)
    stop = next((clean(e.get("msg", "")) for e in events if e.get("type") == "stop"), "")
    if stop:
        story.append(safe_para(f"<b>Stop decision.</b> {esc(stop)}", st["body"]))
    story += [_heading("Plan and sub-question tree", 1, st)] + _plan_tree(events, st)
    story += [_heading("Timeline of every step", 1, st)] + _timeline(events, st)
    story += [PageBreak(), _heading("Claim ledger", 1, st, "sec-ledger")] + ledger_part
    story += [_heading("Conflicts and how they resolved", 1, st)] + _conflicts(ctx, st)
    story += [_heading("Verifier results", 1, st)] + _verifier(ctx, events, st)
    story += [_heading("Assumptions and uncertainty", 1, st)] + _uncertainty(ctx, st)
    story += [PageBreak(), _heading(f"Sources and tiers ({len(ctx.sources)})", 1, st, "sec-sources")] + sources_part
    holder: dict = {}
    doc = _document(path, ctx, "Run trace", holder)
    doc.build(story, canvasmaker=_canvas_class(short_q, run_id, "SYNTHETIC SAMPLE DATA" if ctx.is_sample else "", holder))
    return int(holder.get("pages", 0))


# ------------------------------------------------------------------ entry points

def trace_path_for(out_path: str) -> str:
    out_path = os.fspath(out_path)
    folder, base = os.path.split(os.path.abspath(out_path))
    return os.path.join(folder, "trace.pdf" if base == "report.pdf" else os.path.splitext(base)[0] + ".trace.pdf")


def _write(builder: Any, plain: Any, result: Any, out_path: str, label: str) -> int | None:
    out_path = os.fspath(out_path)
    folder = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".pdf", prefix=f".{label}-", dir=folder)
    os.close(fd)
    pages: int | None = None
    try:
        try:
            pages = builder(result, tmp)
        except Exception as exc:  # last resort: a plain PDF beats no PDF
            print(f"report: {label} layout failed ({type(exc).__name__}: {exc}); writing plain version", file=sys.stderr)
            plain(result, tmp)
        os.replace(tmp, out_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return pages


def render_trace_pdf(result: Any, out_path: str) -> None:
    """Write the full audit trail: plan, rounds, claim ledger, conflicts, verifier results, sources with tiers, budgets."""
    global _TRACE_NAME
    _TRACE_NAME = os.path.basename(os.fspath(out_path))
    _write(_build_trace, _build_plain, result, out_path, "trace")


def render_pdf(result: Any, out_path: str) -> None:
    """Write the answer-only report (at most PAGE_CAP pages) to `out_path`, and the full trace next to it.

    The trace goes to trace.pdf beside report.pdf (or <name>.trace.pdf for any other file name).
    Raises only if no report can be made; a trace failure is reported on stderr."""
    global _TRACE_NAME, _REPORT_NAME
    _REPORT_NAME, _TRACE_NAME = os.path.basename(os.fspath(out_path)), os.path.basename(trace_path_for(out_path))
    _write(_build_report, _build_plain, result, out_path, "report")
    actual = _count_pages(os.fspath(out_path))
    if actual is not None and actual > PAGE_CAP:
        print(f"report: warning, {out_path} has {actual} pages, over the {PAGE_CAP} page cap", file=sys.stderr)
    try:
        render_trace_pdf(result, trace_path_for(out_path))
    except Exception as exc:
        print(f"report: could not write the trace ({type(exc).__name__}: {exc})", file=sys.stderr)


def _build_plain(result: Any, path: str) -> int:
    """Minimal text-only layout used only when a full builder fails."""
    register_fonts()
    st = _styles()
    flow: list = [Paragraph(esc(_g(result, "question", "")), st["title"]), Paragraph(esc(_g(result, "answer_md", "")).replace("\n", "<br/>"), st["body"])]
    for c in _g(result, "claims", []) or []:
        flow.append(Paragraph(esc(f"{_g(c, 'id', '?')} [{_status(c)}] {_g(c, 'text', '')}"), st["body"]))
        for e in _g(c, "evidence", []) or []:
            flow.append(Paragraph(esc(f"   {_g(e, 'source_url', '')}"), st["small"]))
    for i, s in enumerate(_g(result, "sources", []) or [], 1):
        flow.append(Paragraph(esc(f"[{i}] {_g(s, 'url', '')}"), st["small"]))
    BaseDocTemplate(path, pagesize=letter, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN,
                    pageTemplates=[PageTemplate(id="p", frames=[Frame(MARGIN, MARGIN, WIDTH, letter[1] - 2 * MARGIN)])]).build(flow)
    return 0
