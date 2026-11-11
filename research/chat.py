"""Interactive chat for the research agent: run `./research-agent` with no arguments.

Type a research question at `you> `. Progress is narrated live while the agent works, then a compact answer
(bottom line, claim and source counts, assumptions, report paths) comes back and the prompt returns.

    /help  /open  /show  /logs [n]  /budget <mins>  /quit

Ctrl+C during a run cancels that run and returns to the prompt, Ctrl+D or /quit leaves. When the clarity check
needs one question it is asked at the same prompt and the default reading is taken after 20 seconds (only on a
real terminal; a pipe never asks). Stdlib only.
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import re
import select
import subprocess
import sys
import textwrap
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

PROMPT = "you> "
ASK_TIMEOUT = 20.0
DEFAULT_BUDGET = 10.0
MAX_BUDGET = 60.0
BOTTOM_LINES = 6
WIDTH = 92
LOG_TAIL = 15

WELCOME = """\
Deep research agent. Ask a question about finance or the economy and I will plan the search, read and
cross-check sources, then write a cited PDF report. Budget {budget:g} min per question.
/help lists the commands, Ctrl+C cancels a run, Ctrl+D leaves."""

HELP = """\
Type a question and press Enter to research it. Commands:
  /help           this list
  /open           open the last report.pdf
  a PDF path     drop a PDF file into the prompt, or type its path, to use it as context
  /show           the full answer, notes and sources of the last run
  /logs [n]       the last n events (default {tail}) of the last run
  /budget <mins>  time budget per question, now {budget:g} min
  /quit           leave (Ctrl+D works too)
Ctrl+C during a run cancels it and returns to the prompt."""

_lock = threading.Lock()
_hard_exit = os._exit  # a cancelled run's worker threads can sit in a 100 s HTTP call; tests patch this


@dataclass
class Chat:
    budget: float = DEFAULT_BUDGET
    ask: bool = True
    run_id: str = ""            # the last run started, finished or not (for /logs)
    result: object = None       # the last run that finished (for /show and /open)
    report: Path | None = None
    trace: Path | None = None
    orphans: list = field(default_factory=list)  # worker threads of cancelled runs


# ---------------------------------------------------------------- output

def say(text: str = "", *, err: bool = False) -> None:
    with _lock:
        print(text, file=sys.stderr if err else sys.stdout, flush=True)


def _c(code: str, text: str) -> str:
    on = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    return f"\033[{code}m{text}\033[0m" if on else text


def _secs(v) -> str:
    try:
        t = int(round(float(v)))
    except (TypeError, ValueError):
        return ""
    return f"{t // 60}m {t % 60:02d}s" if t >= 60 else f"{t}s"


def _url(p) -> str:
    from research.cli import file_url

    return file_url(p)


def _short(p) -> str:
    p = Path(p)
    try:
        return str(p.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(p)


def _event_line(ev: dict) -> str:
    try:
        m, s = divmod(int(float(ev.get("t", 0) or 0)), 60)
    except (TypeError, ValueError):
        m, s = 0, 0
    return f"  [{m}:{s:02d}] {ev.get('msg', '')}"


_CITE = re.compile(r"\s*(?:\[c?\d+\])+")


def bottom_line(md: str, max_lines: int = BOTTOM_LINES, width: int = WIDTH) -> tuple[list[str], bool]:
    """The answer's Bottom line section as wrapped lines without citation marks, and whether it was cut."""
    text = str(md or "").strip()
    if not text:
        return ["(no answer was written)"], False
    m = re.search(r"^#{1,6}\s*bottom line\s*:?\s*$", text, re.I | re.M)
    if m:
        body = text[m.end():]
        nxt = re.search(r"^#{1,6}\s", body, re.M)
        body = body[:nxt.start()] if nxt else body
    else:
        body = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    body = _CITE.sub("", body).replace("**", "").replace("`", "")
    flat = " ".join(re.sub(r"^\s*[-*]\s+", "", l) for l in body.splitlines() if l.strip())
    lines = textwrap.wrap(" ".join(flat.split()), width) or ["(no answer was written)"]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .,;:") + " ..."
        return lines, True
    return lines, False


def _counts(result) -> str:
    claims = list(getattr(result, "claims", None) or [])
    n = {s: sum(1 for c in claims if getattr(c, "status", "") == s) for s in ("supported", "contested", "unsupported")}
    open_c = sum(1 for c in (getattr(result, "conflicts", None) or []) if not getattr(c, "resolved", False))
    parts = [f"{len(claims)} claims ({n['supported']} supported, {n['contested']} contested, {n['unsupported']} left out)",
             f"{len(getattr(result, 'sources', None) or [])} sources"]
    if open_c:
        parts.append(f"{open_c} open conflict{'s' if open_c != 1 else ''}")
    return ", ".join(parts)


def present(result, report: Path | None, trace: Path | None) -> None:
    st = dict(getattr(result, "stats", None) or {})
    took, tokens = _secs(st.get("seconds")), st.get("tokens")
    head = "Done" + (f" in {took}" if took else "")
    if isinstance(tokens, (int, float)) and not isinstance(tokens, bool):
        head += f", {int(tokens):,} tokens"
    lines, cut = bottom_line(getattr(result, "answer_md", ""))
    say()
    say(_c("1", "research> ") + head + ".")
    say(_c("1", "  Bottom line"))
    for l in lines:
        say("  " + l)
    say()
    say("  " + _counts(result))
    for a in getattr(result, "assumptions", None) or []:
        say(textwrap.fill(f"Assumed: {a}", WIDTH, initial_indent="  ", subsequent_indent="    "))
    if report:
        say(f"  Report: {_url(report)}")
    if trace:
        say(f"  Trace:  {_url(trace)}")
    try:
        from research.cli import open_pdfs

        open_pdfs(report, trace)
    except Exception:  # noqa: BLE001
        pass
    say("  /show for the full answer" + (", " if report else "") + ("/open for the report" if report else "")
        + (" (the bottom line above is shortened)" if cut else ""))
    say()


# ---------------------------------------------------------------- input

def _read(prompt: str) -> str:
    """One line from the user. EOFError on Ctrl+D, KeyboardInterrupt on Ctrl+C at the prompt."""
    if sys.stdin.isatty():
        return input(prompt)
    with _lock:
        sys.stdout.write(prompt)
        sys.stdout.flush()
    line = sys.stdin.readline()
    if line == "":
        raise EOFError
    with _lock:  # echo, so a piped session reads like a typed one
        sys.stdout.write(line if line.endswith("\n") else line + "\n")
        sys.stdout.flush()
    return line.rstrip("\n")


def _ask_fn(cancel: threading.Event):
    """The clarity check's ask_fn: show the one question, read the answer from the `you> ` prompt, give up after
    ASK_TIMEOUT seconds (None means take the default reading). Polls in short slices so a Ctrl+C cancel frees it."""
    def ask(line: str) -> "str | None":
        with _lock:
            print(f"\n{_c('1', 'research> ')}{line}", flush=True)
            print(f"      Answer A, B or in your own words; I take my pick in {int(ASK_TIMEOUT)}s.", flush=True)
            sys.stdout.write(PROMPT)
            sys.stdout.flush()
        end = time.time() + ASK_TIMEOUT
        while time.time() < end and not cancel.is_set():
            try:
                ready, _, _ = select.select([sys.stdin], [], [], 0.25)
            except (OSError, ValueError):
                return None
            if ready:
                return sys.stdin.readline().strip() or None
        if not cancel.is_set():
            say("\n  No answer, going with my pick.")
        return None
    return ask


# ---------------------------------------------------------------- runs

def _describe(err: BaseException) -> str:
    if type(err).__name__ in ("MissingAPIKeyError", "AuthError"):
        return str(err)
    return f"{type(err).__name__}: {err}"


def render(result) -> tuple[Path | None, Path | None]:
    """Write runs/<run_id>/report.pdf and trace.pdf. A failure is reported and never loses the run."""
    from research import store

    out = store.run_dir(result.run_id) / "report.pdf"
    trace = out.with_name("trace.pdf")
    try:
        import research.report as rep

        say("  Writing the PDF report...")
        rep.render_pdf(result, str(out))
        tp = getattr(rep, "trace_path_for", None)
        if tp:
            trace = Path(tp(str(out)))
    except Exception as e:  # noqa: BLE001 - the saved run is still good
        say(f"error: could not write the PDF report ({type(e).__name__}: {e})", err=True)
    return (out if out.is_file() else None), (trace if trace.is_file() else None)


_PDF_RE = re.compile(r"""(?:'([^']+\.pdf)'|"([^"]+\.pdf)"|((?:\\.|[^\s\\'"])+\.pdf))""", re.I)
DEFAULT_PDF_QUESTION = ("Assess this document: check its main claims and the evidence behind them against outside sources, "
                        "and say where it is supported, disputed or missing support.")


def split_pdfs(line: str) -> "tuple[str, list[str]]":
    """Pull the paths of existing PDF files out of a typed line. Handles quoted paths, drag-and-drop paths with
    backslash-escaped spaces, and ~. Returns the line without them and the files found. A path that does not
    exist stays in the question."""
    found: list[str] = []

    def take(m: "re.Match[str]") -> str:
        raw = m.group(1) or m.group(2) or m.group(3) or ""
        path = Path(re.sub(r"\\(.)", r"\1", raw)).expanduser()
        if path.is_file():
            found.append(str(path))
            return " "
        return m.group(0)

    rest = " ".join(_PDF_RE.sub(take, line).split())
    return rest, found


def run_question(chat: Chat, question: str) -> None:
    import research.agent as agent

    run_fn = agent.run_research
    question, pdfs = split_pdfs(question)
    if pdfs:
        for f in pdfs:
            say(_c("2", f"  Using the document {Path(f).name}"))
        if len(question.split()) < 2:
            question = (question + " " + DEFAULT_PDF_QUESTION).strip()
    cancel = threading.Event()
    box: dict = {}
    kwargs = {}
    if chat.ask and "ask_fn" in inspect.signature(run_fn).parameters:
        kwargs["ask_fn"] = _ask_fn(cancel)

    def emit(ev) -> None:
        if cancel.is_set() or not isinstance(ev, dict):
            return
        if ev.get("run_id"):
            chat.run_id = str(ev["run_id"])
        say(_c("2", _event_line(ev)))

    def work() -> None:
        try:
            box["result"] = run_fn(question, pdfs, chat.budget, emit=emit, **kwargs)
        except BaseException as e:  # noqa: BLE001 - reported at the prompt, never a traceback
            box["error"] = e

    th = threading.Thread(target=work, name="research-run", daemon=True)
    say()
    say(_c("2", f"  Researching with a {chat.budget:g} minute budget. Ctrl+C cancels."))
    th.start()
    try:
        while th.is_alive():
            th.join(0.2)
    except KeyboardInterrupt:
        cancel.set()
        chat.orphans.append(th)
        say("\n  Cancelled. Back at the prompt; /logs shows what it did.\n")
        return
    err, result = box.get("error"), box.get("result")
    if err is not None or result is None:
        say(f"error: {_describe(err) if err is not None else 'the run returned nothing'}", err=True)
        if chat.run_id:
            say("  /logs shows what it did before it stopped.\n")
        return
    chat.result, chat.run_id = result, getattr(result, "run_id", chat.run_id) or chat.run_id
    try:
        chat.report, chat.trace = render(result)
    except KeyboardInterrupt:
        chat.report = chat.trace = None
        say("  Skipped the PDF.")
    present(result, chat.report, chat.trace)


# ---------------------------------------------------------------- commands

def _latest_run_id() -> str:
    try:
        from research import store

        rows = store.list_runs(1)
        return str(rows[0]["run_id"]) if rows else ""
    except Exception:  # noqa: BLE001
        return ""


def _last_result(chat: Chat):
    if chat.result is not None:
        return chat.result
    rid = _latest_run_id()
    if not rid:
        return None
    try:
        from research import store

        return store.load_run(rid)
    except Exception:  # noqa: BLE001
        return None


def cmd_open(chat: Chat) -> None:
    path = chat.report
    if path is None:
        res = _last_result(chat)
        if res is not None:
            from research import store

            cand = store.RUNS_DIR / res.run_id / "report.pdf"
            path = cand if cand.is_file() else None
    if path is None:
        say("  No report yet. Ask a question first.")
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        subprocess.run([opener, str(path)], check=True, timeout=15)
        say(f"  Opened {_short(path)}")
    except (OSError, subprocess.SubprocessError) as e:
        say(f"error: could not open {_short(path)} ({e}); it is at {path}", err=True)


def cmd_show(chat: Chat) -> None:
    res = _last_result(chat)
    if res is None:
        say("  Nothing to show yet. Ask a question first." if not chat.run_id else
            "  The last run has no saved answer (cancelled or failed). /logs shows its trace.")
        return
    say()
    say(textwrap.fill(f"Question: {res.question}", WIDTH))
    say()
    say((res.answer_md or "(no answer)").strip())
    for title, items in (("Assumptions", getattr(res, "assumptions", None)), ("Uncertainty", res.uncertainty_notes)):
        if items:
            say(f"\n{title}")
            for it in items:
                say(textwrap.fill(f"- {it}", WIDTH, subsequent_indent="  "))
    say(f"\nSources ({len(res.sources)})")
    for i, s in enumerate(res.sources, 1):
        say(f"  [{i}] {s.url}")
    say(f"\n{_counts(res)}\n")


def cmd_logs(chat: Chat, arg: str) -> None:
    try:
        n = max(1, int(arg)) if arg else LOG_TAIL
    except ValueError:
        say("  Usage: /logs [n]")
        return
    rid = chat.run_id or _latest_run_id()
    if not rid:
        say("  No run yet. Ask a question first.")
        return
    from research import store

    path = store.RUNS_DIR / rid / "events.jsonl"
    if not path.is_file():
        say(f"  No trace for run {rid} yet ({_short(path)}).")
        return
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    say(f"  Run {rid}, last {min(n, len(lines))} of {len(lines)} events ({_short(path)})")
    for raw in lines[-n:]:
        try:
            ev = json.loads(raw)
            say(f"{_event_line(ev)}  ({ev.get('type', '')})" if isinstance(ev, dict) else raw)
        except json.JSONDecodeError:
            say(raw)


def cmd_budget(chat: Chat, arg: str) -> None:
    if not arg:
        say(f"  Budget is {chat.budget:g} min per question. Change it with /budget <mins>.")
        return
    try:
        v = float(arg)
    except ValueError:
        v = 0.0
    if not 0 < v <= MAX_BUDGET:
        say(f"  Give a number of minutes above 0 and up to {MAX_BUDGET:g}, for example /budget 5.")
        return
    chat.budget = v
    say(f"  Budget is now {v:g} min per question.")


def command(chat: Chat, line: str) -> bool:
    """Run a slash command. False means leave the chat."""
    name, _, arg = line[1:].partition(" ")
    name, arg = name.lower(), arg.strip()
    if name in ("quit", "exit", "q"):
        return False
    if name in ("help", "h", "?"):
        say(HELP.format(budget=chat.budget, tail=LOG_TAIL))
    elif name == "open":
        cmd_open(chat)
    elif name == "show":
        cmd_show(chat)
    elif name == "logs":
        cmd_logs(chat, arg)
    elif name == "budget":
        cmd_budget(chat, arg)
    else:
        say(f"  Unknown command /{name}. /help lists them.")
    return True


# ---------------------------------------------------------------- entry

def _key_warning() -> str:
    try:
        from research.llm import MissingAPIKeyError, get_api_key
    except Exception:  # noqa: BLE001
        return ""
    try:
        get_api_key()  # also loads .env
    except MissingAPIKeyError as e:
        return str(e)
    except Exception:  # noqa: BLE001
        return ""
    return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="research-agent", description="Interactive chat for the deep research agent.")
    ap.add_argument("--budget-mins", type=float, default=DEFAULT_BUDGET, help="time budget per question (default 10)")
    ap.add_argument("--no-clarify", action="store_true", help="never ask a clarifying question")
    args, _ = ap.parse_known_args([] if argv is None else argv)
    budget = args.budget_mins if 0 < args.budget_mins <= MAX_BUDGET else DEFAULT_BUDGET
    interactive = bool(sys.stdin and sys.stdin.isatty())
    chat = Chat(budget=budget, ask=interactive and not args.no_clarify)
    if interactive:
        try:
            import readline  # noqa: F401  line editing and history for input()
        except ImportError:
            pass
    say(WELCOME.format(budget=chat.budget))
    warn = _key_warning()
    if warn:
        say(f"warning: {warn}. Questions will fail until it is set.", err=True)
    say()
    while True:
        try:
            line = _read(PROMPT).strip()
        except EOFError:
            say()
            break
        except KeyboardInterrupt:
            say("\n  (Ctrl+D or /quit leaves)")
            continue
        if not line:
            continue
        if line.lower() in ("quit", "exit", "help"):
            line = "/" + line.lower()
        token = line.split(" ", 1)[0]
        looks_like_path = "/" in token[1:] or token.lower().endswith(".pdf")  # a dropped file, not a command
        if line.startswith("/") and not looks_like_path:
            if not command(chat, line):
                break
            continue
        run_question(chat, line)
    say("Bye.")
    if any(t.is_alive() for t in chat.orphans):
        sys.stdout.flush()
        sys.stderr.flush()
        _hard_exit(0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
