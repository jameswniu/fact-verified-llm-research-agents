"""Pass/fail evals for the clarifying-question rule in research/clarify.py.

The rule: ask at most one short question, and only when two readings would change the research path and the
default reading is doubtful. Otherwise assume, and say so. Never ask again after the user has answered. With no
ask_fn (pipes, CI, evals) never ask, proceed on the default and record the assumption.

Cases that judge behaviour call the real model. Cases that test the fallback logic use a stub model so they are exact.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable

from .cases import BY_ID

CLEAR = [BY_ID[i].question for i in ("stagflation_1970s", "svb_collapse_2023", "yield_curve_recessions")]
AMBIGUOUS = ["Is inflation bad?", "Did the bailout work?", "What caused the crash?"]
MILD = ["What is the current US inflation rate?", "How large is the US national debt?",
        "What is Apple's market capitalization?"]


class Asker:
    """A scripted user. Records every question it is shown."""

    def __init__(self, reply="A", delay=0.0, raises=False):
        self.reply, self.delay, self.raises, self.calls = reply, delay, raises, []

    def __call__(self, line):
        self.calls.append(line)
        if self.delay:
            time.sleep(self.delay)
        if self.raises:
            raise RuntimeError("terminal closed")
        return self.reply


class StubLLM:
    """Always says the question is ambiguous, so the ask/answer plumbing can be tested exactly."""

    def json(self, prompt, **kw):
        return {"ask": True, "default_confidence": 0.3, "default": "A",
                "interpretations": {"A": "households and savers", "B": "the economy as a whole"},
                "assumption": "Assuming households and savers. Tell me if you meant something else.",
                "question_line": "Bad for whom? (A) households and savers (B) the economy as a whole, or I'll pick A"}


def _clarify(question, ask_fn, **kw):
    from research.clarify import clarify
    return clarify(question, ask_fn, **kw)


def _says_assuming(note: str) -> bool:
    return bool(re.search(r"assum", note, re.I))


def case_clear_no_ask():
    fails = []
    for q in CLEAR:
        a = Asker("A")
        wq, notes = _clarify(q, a)
        if a.calls:
            fails.append(f"asked about a clear question: {a.calls[0][:70]}")
        if not 1 <= len(notes) <= 2:
            fails.append(f"expected one scope assumption, got {len(notes)}")
        elif not _says_assuming(notes[0]):
            fails.append("scope line does not say it is an assumption")
        if q[:40] not in wq:
            fails.append("working question lost the original text")
    return not fails, "; ".join(fails) or "no ask on 3 clear questions, one assumption each"


def case_ambiguous_asks_once():
    fails = []
    for q in AMBIGUOUS:
        a = Asker("A")
        wq, notes = _clarify(q, a)
        if len(a.calls) != 1:
            fails.append(f"'{q}' asked {len(a.calls)} times")
            continue
        line = a.calls[0]
        if "\n" in line.strip() or len(line) > 400:
            fails.append("question is not one short line")
        if not (re.search(r"\(A\)", line) and re.search(r"\(B\)", line)):
            fails.append("question does not offer two labelled options")
        if not notes:
            fails.append("chosen reading not recorded")
    return not fails, "; ".join(fails) or "asked exactly once with two options on 3 ambiguous questions"


def case_never_asks_twice():
    fails = []
    for q in AMBIGUOUS[:2]:
        a = Asker("honestly both, or neither, I do not know")
        wq, notes = _clarify(q, a)
        if len(a.calls) != 1:
            fails.append(f"'{q}' asked {len(a.calls)} times on a vague reply")
        b = Asker("A")
        _clarify(wq, b)  # the conversation continues with the working question
        if b.calls:
            fails.append("asked again on the second turn")
    return not fails, "; ".join(fails) or "one question, then none on the second turn"


def case_noninteractive_default(budget_mins=1.0):
    fails, extra = [], {}
    wq, notes = _clarify("Is inflation bad?", None)
    if not notes:
        fails.append("no assumption recorded without ask_fn")
    elif not all(_says_assuming(n) and re.search(r"tell me if", n, re.I) for n in notes):
        fails.append("assumption does not say it is an assumption and invite a correction")
    if "Is inflation bad?" not in wq:
        fails.append("working question lost the original text")
    from research.agent import run_research
    q = "Is inflation bad?"
    t0 = time.time()
    res = run_research(q, [], budget_mins, lambda *a, **k: None, ask_fn=None)
    extra["seconds_e2e"] = round(time.time() - t0, 1)
    extra["result"] = res
    recorded = list(getattr(res, "assumptions", []) or []) or [n for n in res.uncertainty_notes if _says_assuming(n)]
    if res.question.strip() != q:
        fails.append(f"result.question was rewritten to {res.question[:60]!r}")
    if not recorded:
        fails.append("run finished but recorded no assumption (result.assumptions and uncertainty_notes both empty)")
    if not (res.answer_md or "").strip():
        fails.append("run produced no answer")
    return not fails, "; ".join(fails) or "ran on the default and recorded the assumption", extra


def case_empty_or_slow_answer_defaults():
    fails = []
    variants = {"empty": Asker(""), "none": Asker(None), "raises": Asker(raises=True), "slow": Asker("A", delay=30)}
    for name, a in variants.items():
        t0 = time.time()
        wq, notes = _clarify("Is inflation bad?", a, llm=StubLLM(), timeout=1.5)
        dt = time.time() - t0
        if len(a.calls) != 1:
            fails.append(f"{name}: ask_fn called {len(a.calls)} times")
        if not notes or not _says_assuming(notes[0]):
            fails.append(f"{name}: default reading not recorded")
        if "Working assumption" not in wq:
            fails.append(f"{name}: working question does not carry the default")
        if dt > 6:
            fails.append(f"{name}: waited {dt:.0f}s for a 1.5s timeout")
    return not fails, "; ".join(fails) or "empty, None, error and no answer all fall back to the default"


def case_mild_ambiguity_assumes():
    fails = []
    for q in MILD:
        a = Asker("A")
        wq, notes = _clarify(q, a)
        if a.calls:
            fails.append(f"asked about a question with an obvious default: {q}")
        if not notes or not _says_assuming(notes[0]) or not re.search(r"tell me if", notes[0], re.I):
            fails.append(f"'{q}': no stated assumption with an invitation to correct it")
    return not fails, "; ".join(fails) or "assumed and said so on 3 mildly ambiguous questions, never asked"


@dataclass
class ClarifyCase:
    id: str
    title: str
    rule: str
    fn: Callable
    uses_agent: bool = False


CLARIFY_CASES = [
    ClarifyCase("clarify_clear_no_ask", "Clarify: clear question, no ask",
                "A clear question is never answered with a question.", case_clear_no_ask),
    ClarifyCase("clarify_ambiguous_asks_once", "Clarify: ambiguous question asks once",
                "Two doubtful readings get exactly one one-line question with two options.", case_ambiguous_asks_once),
    ClarifyCase("clarify_never_asks_twice", "Clarify: never asks twice",
                "After the user answers, even vaguely, the system does not ask again.", case_never_asks_twice),
    ClarifyCase("clarify_noninteractive_default", "Clarify: non-interactive run proceeds",
                "With no one to ask, the run goes on with the default and records the assumption.",
                case_noninteractive_default, uses_agent=True),
    ClarifyCase("clarify_empty_or_slow_answer", "Clarify: empty or slow answer",
                "An empty answer, None, an error or silence takes the default and does not hang.",
                case_empty_or_slow_answer_defaults),
    ClarifyCase("clarify_mild_ambiguity_assumes", "Clarify: mild ambiguity assumes",
                "When one reading is the obvious one, assume it, say so and invite a correction.", case_mild_ambiguity_assumes),
]
CLARIFY_BY_ID = {c.id: c for c in CLARIFY_CASES}


def run_clarify_suite(repeats: int = 3, log=print, budget_mins: float = 1.0) -> list[dict]:
    """Run every clarifying-question case `repeats` times in parallel. Returns one row per case."""
    from concurrent.futures import ThreadPoolExecutor

    def go(job):
        case, i = job
        try:
            r = case.fn(budget_mins) if case.uses_agent else case.fn()
            ok, detail = bool(r[0]), str(r[1])
        except Exception as e:  # noqa: BLE001 - a crash is a failed run
            ok, detail = False, f"crashed {type(e).__name__}: {str(e)[:150]}"
        log(f"[clarify] {case.id} #{i + 1} {'PASS' if ok else 'FAIL'} {'' if ok else detail[:120]}")
        return case, ok, detail

    jobs = [(c, i) for c in CLARIFY_CASES for i in range(repeats)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        done = list(pool.map(go, jobs))
    rows = []
    for c in CLARIFY_CASES:
        mine = [(ok, d) for cc, ok, d in done if cc.id == c.id]
        fails = [d for ok, d in mine if not ok]
        rows.append({"id": c.id, "title": c.title, "rule": c.rule, "runs": len(mine),
                     "passed": sum(ok for ok, _ in mine), "first_failure": fails[0] if fails else ""})
    return rows
