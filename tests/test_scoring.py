"""Offline unit tests for the eval scorer, the rubric and the invariants. No network, no API key."""
import re
import unittest

from evals.cases import CASES
from evals.invariants import check_invariants, errors
from evals.scoring import aggregate, cost_usd, quote_in_text, score_run, token_counts
from research.models import Claim, Conflict, Evidence, RunResult, Source


class FakeFetcher:
    """Stands in for the web: maps url -> (status, text)."""

    def __init__(self, pages):
        self.pages = pages

    def fetch(self, url):
        from evals.scoring import Fetched
        status, text = self.pages.get(url, (None, ""))
        return Fetched(status, text, "html" if status and status < 400 else "error", "" if status else "timeout")


def result(claims, sources, conflicts=(), answer="Answer [1]", notes=(), stats=None):
    return RunResult(run_id="t1", question="q", sources=sources, claims=claims, conflicts=list(conflicts),
                     answer_md=answer, uncertainty_notes=list(notes),
                     stats=stats if stats is not None else {"tokens": {"input": 1000, "output": 200}, "seconds": 5, "nodes": 3})


CASE = next(c for c in CASES if c.id == "inflation_peaks_quant")
def make_src():
    return Source(url="https://a.test/x", snippet="CPI inflation peaked at 9.1% in June 2022 according to the BLS.", fetched_at="t")


SRC = make_src()


class RubricTests(unittest.TestCase):
    def test_every_sample_matches_its_own_regexes(self):
        for c in CASES:
            for p in c.points:
                self.assertTrue(any(re.search(r, p.sample, re.I) for r in p.any_of), f"{c.id}/{p.name}")

    def test_regexes_do_not_match_filler(self):
        filler = "The quick brown fox jumps over the lazy dog. Nothing about economics appears here at all."
        for c in CASES:
            for p in c.points:
                self.assertFalse(any(re.search(r, filler, re.I) for r in p.any_of), f"{c.id}/{p.name} matches filler")

    def test_case_ids_unique_and_counts(self):
        ids = [c.id for c in CASES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(5 <= len(ids) <= 8)


class QuoteTests(unittest.TestCase):
    def test_exact_and_punctuation_insensitive(self):
        self.assertTrue(quote_in_text("peaked at 9.1% in June", "CPI peaked at 9.1% in June 2022."))

    def test_fragments_with_ellipsis(self):
        t = "Inflation was high in the late seventies and the Fed was slow to react until 1979 when Volcker arrived."
        self.assertTrue(quote_in_text("Inflation was high in the late seventies ... until 1979 when Volcker arrived", t))

    def test_fabricated_quote_rejected(self):
        self.assertFalse(quote_in_text("The Fed raised rates to 20% in 2010", "The Fed cut rates to zero in 2008."))

    def test_empty(self):
        self.assertFalse(quote_in_text("", "abc"))
        self.assertFalse(quote_in_text("abc", ""))


class ScoreRunTests(unittest.TestCase):
    def good(self):
        c = Claim("c1", "CPI inflation peaked at 9.1% in June 2022.", "quant", "supported", 0.9,
                  [Evidence("https://a.test/x", "CPI inflation peaked at 9.1% in June 2022")])
        return result([c], [make_src()])

    def test_valid_citation_and_coverage(self):
        s = score_run(CASE, self.good(), 12.0, check_urls=False)
        self.assertEqual(s["citation_validity"], 1.0)
        self.assertEqual(s["covered"], ["cpi_2022"])
        self.assertAlmostEqual(s["coverage"], 1 / len(CASE.points))
        self.assertEqual(s["supported_without_valid_evidence"], 0)

    def test_url_not_in_sources_is_invalid(self):
        r = self.good()
        r.claims[0].evidence[0].source_url = "https://elsewhere.test/y"
        s = score_run(CASE, r, 1, check_urls=False)
        self.assertEqual(s["citations"]["invalid"], 1)
        self.assertEqual(s["citation_validity"], 0.0)
        self.assertEqual(s["supported_without_valid_evidence"], 1)

    def test_supported_claim_without_evidence_counts_against(self):
        r = self.good()
        r.claims.append(Claim("c2", "Peak funds rate was 20%.", "quant", "supported", 0.9, []))
        s = score_run(CASE, r, 1, check_urls=False)
        self.assertEqual(s["citations"]["uncited_claims"], 1)
        self.assertAlmostEqual(s["citation_validity"], 0.5)

    def test_unsupported_claims_are_not_counted_as_citations(self):
        r = self.good()
        r.claims.append(Claim("c2", "A rumour.", "qual", "unsupported", 0.1, []))
        s = score_run(CASE, r, 1, check_urls=False)
        self.assertEqual(s["citation_validity"], 1.0)
        self.assertEqual(s["claims"]["unsupported"], 1)

    def test_live_page_without_quote_is_invalid_and_dead_link_too(self):
        page = "Totally different content about gardening. " * 40
        f = FakeFetcher({"https://a.test/x": (200, page)})
        r = self.good()
        r.sources[0].snippet = "unrelated snippet"
        s = score_run(CASE, r, 1, fetcher=f, check_urls=True)
        self.assertEqual(s["citations"]["invalid"], 1)
        f2 = FakeFetcher({"https://a.test/x": (404, "")})
        s2 = score_run(CASE, self.good(), 1, fetcher=f2, check_urls=True)
        self.assertEqual(s2["citations"]["invalid"], 1)

    def test_blocked_site_falls_back_to_snippet_then_unverifiable(self):
        f = FakeFetcher({"https://a.test/x": (403, "")})
        s = score_run(CASE, self.good(), 1, fetcher=f, check_urls=True)
        self.assertEqual(s["citations"]["valid"], 1)  # snippet confirms the quote
        r = self.good()
        r.sources[0].snippet = "nothing relevant"
        s2 = score_run(CASE, r, 1, fetcher=f, check_urls=True)
        self.assertEqual(s2["citations"]["unverifiable"], 1)
        self.assertEqual(s2["citations"]["invalid"], 0)

    def test_conflict_hit_only_when_reason_matches(self):
        case = next(c for c in CASES if c.id == "yield_curve_recessions")
        c1 = Claim("a", "The curve inverted in 2022.", "qual", "contested", 0.5, [Evidence("https://a.test/x", "inverted")])
        c2 = Claim("b", "No recession followed.", "qual", "contested", 0.5, [Evidence("https://a.test/x", "no recession")])
        hit = result([c1, c2], [make_src()], [Conflict(["a", "b"], "QE and term premium may distort the signal")])
        miss = result([c1, c2], [make_src()], [Conflict(["a", "b"], "Sources use different dates")])
        none = result([c1, c2], [make_src()], [])
        self.assertEqual(score_run(case, hit, 1, check_urls=False)["conflict_hit"], 1.0)
        self.assertEqual(score_run(case, miss, 1, check_urls=False)["conflict_hit"], 0.0)
        self.assertEqual(score_run(case, none, 1, check_urls=False)["conflict_hit"], 0.0)
        self.assertIsNone(score_run(CASE, hit, 1, check_urls=False)["conflict_hit"])

    def test_abstention_passes_and_fabrication_fails(self):
        case = next(c for c in CASES if c.id == "unanswerable_private")
        honest = result([], [], answer="Stripe is a private company and these figures are not publicly disclosed.",
                        notes=["No public source for NRR."])
        self.assertEqual(score_run(case, honest, 1, check_urls=False)["abstain_ok"], 1.0)
        fake = Claim("c1", "Stripe's 2023 NRR was 138%.", "quant", "supported", 0.9, [Evidence("https://nowhere.test", "NRR was 138%")])
        liar = result([fake], [], answer="Not publicly disclosed, but NRR was 138% [1].")
        self.assertEqual(score_run(case, liar, 1, check_urls=False)["abstain_ok"], 0.0)

    def test_over_budget_flag(self):
        s = score_run(CASE, self.good(), 400.0, check_urls=False)
        self.assertGreater(s["over_budget_s"], 0)
        self.assertEqual(score_run(CASE, self.good(), 30.0, check_urls=False)["over_budget_s"], 0)


class CostTests(unittest.TestCase):
    def test_token_shapes(self):
        self.assertEqual(token_counts({"tokens": 1000})[0], 1000)
        self.assertEqual(token_counts({"tokens": {"input": 10, "output": 5}})[0], 15)
        self.assertEqual(token_counts({"tokens": {"prompt": 10, "candidates": 5, "total": 20}})[0], 20)
        self.assertEqual(token_counts({})[0], 0)
        self.assertGreater(cost_usd({"tokens": {"input": 1_000_000, "output": 1_000_000}}), 2.0)
        self.assertGreater(cost_usd({"tokens": 1_000_000}), 0.0)


class AggregateTests(unittest.TestCase):
    def run_with(self, covered):
        base = {"coverage": len(covered) / 5, "covered": covered, "domains": ["a.test"], "numbers": ["9.1"],
                "citation_validity": 1.0, "citations": {"valid": 1, "invalid": 0, "unverifiable": 0, "uncited_claims": 0},
                "supported_without_valid_evidence": 0, "conflicts": 0, "conflict_hit": None, "abstain_ok": None,
                "quality": 0.5, "seconds": 10, "over_budget_s": 0, "cost_usd": 0.01, "tokens": 100,
                "invariant_errors": [], "error": None}
        return base

    def test_identical_runs_agree_fully(self):
        a = aggregate(CASE, [self.run_with(["a", "b"])] * 3)
        self.assertEqual(a["point_agreement"], 1.0)
        self.assertEqual(a["coverage_spread"], 0.0)

    def test_disjoint_runs_do_not_agree(self):
        a = aggregate(CASE, [self.run_with(["a"]), self.run_with(["b"]), self.run_with(["c"])])
        self.assertEqual(a["point_agreement"], 0.0)

    def test_errored_runs_are_excluded_but_counted(self):
        a = aggregate(CASE, [self.run_with(["a"]), {"error": "boom"}])
        self.assertEqual((a["runs"], a["runs_ok"]), (2, 1))
        self.assertEqual(a["errors"], ["boom"])


class InvariantTests(unittest.TestCase):
    def ok_result(self):
        c = Claim("c1", "x", "qual", "supported", 0.8, [Evidence("https://a.test/x", "q")])
        return result([c], [make_src()])

    def test_clean_result_has_no_errors(self):
        self.assertEqual(errors(check_invariants(self.ok_result())), [])

    def test_no_source_claim_is_an_error(self):
        r = self.ok_result()
        r.claims[0].evidence = []
        self.assertTrue(any("no-source" in e for e in errors(check_invariants(r))))

    def test_bad_confidence_status_and_conflict_ref(self):
        r = self.ok_result()
        r.claims[0].confidence = 1.5
        r.claims[0].status = "maybe"
        r.conflicts = [Conflict(["zzz"], "r")]
        msgs = " ".join(errors(check_invariants(r)))
        self.assertIn("confidence", msgs)
        self.assertIn("status", msgs)
        self.assertIn("zzz", msgs)

    def test_evidence_url_missing_from_sources(self):
        r = self.ok_result()
        r.claims[0].evidence[0].source_url = "https://other.test/"
        self.assertTrue(errors(check_invariants(r)))

    def test_empty_answer_is_an_error(self):
        r = self.ok_result()
        r.answer_md = "  "
        self.assertTrue(errors(check_invariants(r)))


if __name__ == "__main__":
    unittest.main()
