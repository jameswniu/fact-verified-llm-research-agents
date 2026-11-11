"""Stress the PDF renderer with hostile but realistic input. Offline, no API key."""
import contextlib
import io
import re
import tempfile
import time
import unittest
from pathlib import Path

from research.models import Claim, Conflict, Evidence, RunResult, Source

try:
    from research.report import render_pdf
except Exception as e:  # reportlab missing or report.py not landed
    render_pdf = None
    _WHY = f"{type(e).__name__}: {e}"

NASTY_TEXT = ("Fed’s “dual mandate” – inflation ≥ 2% → rates ≈ 5.25–5.50% "
              "€ ₹ \U0001F4C8 中文 العربية é zero​width nb sp")
MARKUP = ("<b>unclosed <font color=red>x</font> </para> &notanentity; <a href=\"javascript:alert(1)\">x</a> "
          "<img src=\"/etc/hosts\"/> <br/><seq/> [1][2][999] [c99] [c1]")


def make(n_claims=3, n_sources=3, text="A plain claim.", url="https://example.test/a", answer=None):
    sources = [Source(url=f"{url}?i={i}" if i else url, author="A. Author", org="Example", date_written="2024-05-01",
                      fetched_at="2026-10-09T14:00:00Z", snippet=text) for i in range(n_sources)]
    claims = []
    for i in range(n_claims):
        status = ["supported", "contested", "unsupported"][i % 3]
        ev = [] if status == "unsupported" else [Evidence(sources[i % n_sources].url, text, "supports" if i % 2 == 0 else "refutes")]
        claims.append(Claim(f"c{i + 1}", text, "quant" if i % 2 else "qual", status, 0.4 + (i % 5) / 10, ev))
    conflicts = [Conflict(["c1", "c2"], "Sources disagree about the size of the effect.", False)] if n_claims >= 2 else []
    return RunResult("r-test", "What happened? " + text, sources, claims, conflicts,
                     answer if answer is not None else f"# Answer\n\n- {text} [1]\n- Second point [c2]\n\n| a | b |\n|---|---|\n| 1 | 2 |\n",
                     ["Evidence is thin for c3."], {"tokens": {"input": 10, "output": 5}, "seconds": 12.5, "nodes": 4})


@unittest.skipIf(render_pdf is None, "research.report not importable")
class ReportStress(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def render(self, result, name="r.pdf", allow_fallback=False, max_seconds=90):
        out = self.dir / "nested dir é" / name
        err = io.StringIO()
        t0 = time.time()
        with contextlib.redirect_stderr(err):
            render_pdf(result, str(out))
        took = time.time() - t0
        data = out.read_bytes()
        self.assertTrue(data.startswith(b"%PDF"), "not a PDF")
        self.assertGreater(len(data), 1500, "suspiciously small PDF")
        self.assertGreaterEqual(len(re.findall(rb"/Type\s*/Page\b", data)), 1)
        self.assertLess(took, max_seconds, f"render took {took:.0f}s")
        if not allow_fallback:
            self.assertNotIn("full layout failed", err.getvalue(), "fell back to the plain layout: " + err.getvalue()[:300])
        return data

    def test_normal(self):
        self.render(make())

    def test_unicode_everywhere(self):
        r = make(text=NASTY_TEXT, answer=f"# {NASTY_TEXT}\n\n{NASTY_TEXT} [1]\n\n> {NASTY_TEXT}\n")
        r.question = NASTY_TEXT
        self.render(r, "unicode.pdf")

    def test_markup_is_inert(self):
        r = make(text=MARKUP, answer=f"{MARKUP}\n\n```\n{MARKUP}\n", url="https://example.test/<script>")
        self.render(r, "markup.pdf")

    def test_huge_inputs(self):
        long_url = "https://example.test/" + "a" * 6000
        r = make(n_claims=400, n_sources=300, text="word " * 40, url=long_url,
                 answer="# H\n\n" + ("Paragraph with a citation [1] and [c2]. " * 40 + "\n\n") * 120 + "x" * 20000)
        self.render(r, "huge.pdf", max_seconds=120)

    def test_unbreakable_words(self):
        r = make(text="W" * 3000, answer="Z" * 5000 + " https://example.test/" + "q" * 4000)
        self.render(r, "longword.pdf")

    def test_missing_and_malformed_fields(self):
        r = make()
        r.claims[0].text = None
        r.claims[1].confidence = float("nan")
        r.claims[2].confidence = "high"
        r.claims[2].status = "weird"
        r.claims[2].evidence = [Evidence(None, None, "sideways")]
        r.sources[0].url = None
        r.sources[1].snippet = None
        r.conflicts = [Conflict(["nope", None], None, None)]
        r.answer_md = None
        r.stats = None
        r.uncertainty_notes = [None, 3]
        self.render(r, "malformed.pdf", allow_fallback=True)

    def test_empty_result(self):
        self.render(RunResult("r-empty", "Q?"), "empty.pdf")

    def test_markdown_edge_cases(self):
        md = ("####### seven hashes\n\n" + ">" * 60 + " deep quote\n\n- a\n  - b\n    - c\n      - d\n        - e\n\n"
              "| a | b | c |\n|---|\n| 1 |\n| 1 | 2 | 3 | 4 | 5 |\n\n[x](javascript:alert(1)) ![img](/etc/hosts)\n\n"
              "```python\nunclosed fence\n\n1. one\n1. two\n10. ten\n\n---\n***\n")
        self.render(make(answer=md), "md.pdf")

    def test_no_source_claim_is_rendered_not_dropped(self):
        r = make(n_claims=3)
        data = self.render(r, "nosource.pdf")
        self.assertGreater(len(data), 3000)


if __name__ == "__main__":
    unittest.main()
