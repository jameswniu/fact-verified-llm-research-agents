"""Clarity check before planning.

One cheap Gemini call judges whether the question needs a clarifying question. It asks only when two plausible
readings would lead to different sources or a different answer AND confidence in the default reading is under
CONFIDENCE_FLOOR. Otherwise it picks the default reading and states the assumption. At most one question per
clarify() call. With no ask_fn (evals, pipes, tests) it never asks and proceeds on the default.
"""
from __future__ import annotations

import re
import select
import sys
import threading
from typing import Callable

from .llm import BudgetExceeded, Gemini, LLMError, MissingAPIKeyError

CONFIDENCE_FLOOR = 0.6

PROMPT = """You decide whether a research question needs ONE clarifying question before research starts.
Question: <<question>>
Ask only when BOTH hold: (1) two plausible readings would lead to different sources or a different answer, and (2) your confidence that the default reading is what the user meant is under 0.6. A question specific enough to search is clear even when it is broad, so never ask just to narrow scope or about format or length. Otherwise do not ask: pick the most likely reading as the default.
Return JSON with these keys. ask (boolean). default_confidence (0 to 1, how sure you are that the default reading is the intended one). default ("A" or "B"). interpretations (object with "A" and "B", each a short phrase naming a reading, "B" may be empty when the question is clear). assumption (one sentence that starts with "Assuming", names the scope and period you will research, and ends with "Tell me if you meant something else."). question_line (only when ask is true: one line with a short question, then (A) option (B) option, then "or I'll pick A").
Clear example: "In the 1970s economists said monetary policy was not working and fiscal policy was needed. Was that right?" gives ask false and assumption "Assuming US and UK, 1970 to 1982. Tell me if you meant something else."
Unclear example: "Is inflation bad?" gives ask true, default_confidence 0.4, question_line "Bad for whom, households or the economy as a whole? (A) households and savers (B) the macroeconomy, or I'll pick B"."""


def _call_with_timeout(fn: Callable[[str], "str | None"], arg: str, timeout: float) -> "str | None":
    """Run fn(arg) in a daemon thread; None if it does not answer within timeout seconds or raises."""
    box: list = []

    def run() -> None:
        try:
            box.append(fn(arg))
        except Exception:  # noqa: BLE001 - a broken prompt must not stop the run
            box.append(None)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    return box[0] if box else None


def terminal_ask(timeout: float = 20.0) -> "Callable[[str], str | None] | None":
    """An ask_fn for a real terminal, or None when stdin is not a TTY (pipes, CI, evals)."""
    try:
        if not (sys.stdin and sys.stdin.isatty()):
            return None
    except (AttributeError, ValueError):
        return None

    def ask(line: str) -> "str | None":
        print(f"\n{line}", file=sys.stderr, flush=True)
        print(f"(A, B or your own words; going with my pick in {int(timeout)}s) > ", end="", file=sys.stderr, flush=True)
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if not ready:
            print("", file=sys.stderr, flush=True)
            return None
        return sys.stdin.readline().strip()

    return ask


def _core(assumption: str) -> str:
    """The assumption without the leading 'Assuming' and the trailing invitation."""
    s = re.sub(r"\s*Tell me if you meant something else\.?\s*$", "", assumption.strip(), flags=re.I)
    return re.sub(r"^Assuming\s+", "", s, flags=re.I).strip().rstrip(".")


def clarify(question: str, ask_fn: "Callable[[str], str | None] | None" = None, *, llm: "Gemini | None" = None,
            emit: "Callable[[str], None] | None" = None, timeout: float = 20.0) -> tuple[str, list[str]]:
    """Return (working_question, assumptions).

    ask_fn receives the one-line question and returns the typed answer: 'A' or 'B' picks that reading, longer
    text is taken as the clarification, empty or None (or no answer within timeout seconds) takes the default.
    emit receives each narrated progress line as a plain string."""
    say = emit or (lambda _m: None)
    q = " ".join(str(question).split())
    if "[Reading chosen by the user" in q or "[Working assumption" in q:
        return q, []  # already clarified once, never ask twice
    llm = llm or Gemini()  # raises MissingAPIKeyError when the key is absent
    try:
        d = llm.json(PROMPT.replace("<<question>>", q), timeout=25, retries=1, label="clarify")
        if not isinstance(d, dict):
            raise ValueError("unexpected reply")
    except MissingAPIKeyError:
        raise
    except (LLMError, BudgetExceeded, ValueError) as e:
        say(f"Could not run the clarity check ({e}); using the question as written")
        return q, []
    interp = d.get("interpretations") if isinstance(d.get("interpretations"), dict) else {}
    a, b = str(interp.get("A") or "").strip(), str(interp.get("B") or "").strip()
    key = "B" if str(d.get("default", "A")).strip().upper() == "B" and b else "A"
    reading, other = (b, a) if key == "B" else (a, b)
    try:
        conf = float(d.get("default_confidence", 1.0))
    except (TypeError, ValueError):
        conf = 1.0
    must_ask = bool(d.get("ask")) and conf < CONFIDENCE_FLOOR and bool(a) and bool(b)
    core = _core(str(d.get("assumption") or "")) or reading
    default_note = f"Assuming {core}. Tell me if you meant something else." if core else ""
    if must_ask and other and core:
        default_note = f"Assuming {core} (the question could also mean {other}). Tell me if you meant something else."

    chosen: "str | None" = None  # a reading or clarification supplied by the user
    if must_ask and ask_fn is not None:
        line = " ".join(str(d.get("question_line") or "").split()) or \
            f"Do you mean (A) {a} or (B) {b}? Or I'll pick {key}."
        say(f"The question could mean two different things, asking once: {line}")
        answer = (_call_with_timeout(ask_fn, line, timeout + 2) or "").strip()  # ask_fn enforces its own wait first
        m = re.match(r"^\(?([ab])\)?(?:[\s.:,;)-]+(.*))?$", answer, re.I | re.S)
        if m:
            picked = a if m.group(1).upper() == "A" else b
            chosen = picked + (f" ({m.group(2).strip()})" if m.group(2) and m.group(2).strip() else "")
        elif answer:
            chosen = answer
        else:
            say(f"No answer, going with the default reading: {core}")
    if chosen:
        assumption = f"You told me to read the question as: {chosen}."
        say(assumption)
        return f"{q} [Reading chosen by the user: {chosen}]", [assumption]
    if default_note:
        say(default_note)
        return f"{q} [Working assumption: {core}]", [default_note]
    return q, []
