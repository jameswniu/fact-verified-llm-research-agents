"""Offline tests for the PDF report, the trace and the CLI helpers. No network, no API key."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pypdf import PdfReader

from research import _md, cli, report
from research.models import Claim, Conflict, Evidence, RunResult, Source
from samples.fake_run import fake_result


def pages(path):
    return len(PdfReader(path).pages)


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_report_and_trace_are_both_written(self):
        out = self.dir / "run" / "report.pdf"
        report.render_pdf(fake_result(), str(out))
        self.assertTrue(out.exists())
        self.assertTrue((self.dir / "run" / "trace.pdf").exists())
        self.assertLessEqual(pages(str(out)), report.PAGE_CAP)

    def test_custom_name_gets_a_sibling_trace(self):
        out = self.dir / "latest.pdf"
        report.render_pdf(fake_result(), str(out))
        self.assertTrue((self.dir / "latest.trace.pdf").exists())

    def test_empty_and_none_fields_still_render(self):
        for r in (RunResult(run_id="", question=""), RunResult(run_id="x", question=None, answer_md=None, stats=None, sources=None,
                                                                claims=None, conflicts=None, uncertainty_notes=None)):
            out = self.dir / "e.pdf"
            report.render_pdf(r, str(out))
            self.assertGreaterEqual(pages(str(out)), 1)

    def test_report_respects_the_page_cap_on_a_huge_run(self):
        sources = [Source(f"https://example.com/p/{i}", f"A{i}", f"O{i}", "2020-01-01", "", "snippet " * 30) for i in range(300)]
        claims = [Claim(f"c{i}", "claim text " * 40, "qual", ["supported", "contested", "unsupported"][i % 3], (i % 10) / 10,
                        [Evidence(f"https://example.com/p/{(i * 7 + k) % 300}", "quote " * 40) for k in range(3 if i % 3 else 0)])
                  for i in range(400)]
        r = RunResult(run_id="huge", question="q", sources=sources, claims=claims, conflicts=[Conflict(["c1", "c2"], "r")],
                      answer_md="\n\n".join(f"Paragraph {i} says something [c{i}] and more [{i % 300 + 1}]." for i in range(300)))
        out = self.dir / "report.pdf"
        report.render_pdf(r, str(out))
        self.assertLessEqual(pages(str(out)), report.PAGE_CAP)
        self.assertGreater(pages(str(self.dir / "trace.pdf")), report.PAGE_CAP)

    def test_citations_are_renumbered_and_only_cited_sources_listed(self):
        ctx = report._Ctx(fake_result())
        text, order = report._renumber(ctx, "A [c5] then B [2] and C [c5, 2].")
        self.assertEqual(order, [4, 2])
        self.assertEqual(text, "A [1] then B [2] and C [1, 2].")


class TextTests(unittest.TestCase):
    def test_greek_and_odd_spaces_are_mapped(self):
        self.assertEqual(_md.clean("β and Δ and a b"), "beta and Delta and a b")

    def test_markup_in_text_is_escaped(self):
        self.assertNotIn("<b>", _md.inline("<b>x</b> & y"))

    def test_dates_are_normalised_or_blank(self):
        self.assertEqual(report._day("Sun, 26/07/1981 - 12:00"), "1981-07-26")
        self.assertEqual(report._day("2020-09-01T10:00:00"), "2020-09-01")
        self.assertEqual(report._day("sometime"), "")


class CliTests(unittest.TestCase):
    def test_terminal_ask_falls_back_to_default_on_eof(self):
        old = sys.stdin
        try:
            sys.stdin = open(os.devnull)
            self.assertEqual(cli.terminal_ask("Which?", ["a", "b"], "a", timeout=0.1), "a")
        finally:
            sys.stdin = old

    def test_run_rejects_a_missing_pdf(self):
        self.assertEqual(cli.main(["run", "q", "--pdf", "/no/such/file.pdf"]), 2)

    def test_event_line_formats(self):
        line, kind = cli._fmt_event('{"t": 65.2, "type": "plan", "msg": "Planner: 3 sub-questions"}', 100)
        self.assertEqual(kind, "plan")
        self.assertTrue(line.startswith("[ 1:05] plan"))


if __name__ == "__main__":
    unittest.main()
