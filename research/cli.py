"""Command line for the research agent.

    ./research-agent                      (no arguments) opens the interactive chat in research/chat.py
    python -m research run "<question>" [--pdf FILE ...] [--budget-mins 10] [--no-clarify]
    python -m research show [run_id]
    python -m research logs [run_id|latest] [--follow]
    python -m research eval run [flags for evals/run_eval.py]

Progress goes to stderr, results to stdout. Exit codes: 0 done, 1 run failed, 2 bad input, 130 interrupted.
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import select
import shutil
import sys
import textwrap
import time
import traceback
from pathlib import Path

ASK_TIMEOUT = 20.0


class _Usage(Exception):
    """Bad input from the user; reported without a traceback."""


def _err(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)


def _secs(v) -> str:
    try:
        t = int(round(float(v)))
    except (TypeError, ValueError):
        return str(v)
    return f"{t // 60}m {t % 60:02d}s" if t >= 60 else f"{t}s"


def terminal_ask(prompt: str, options=None, default=None, timeout: float = ASK_TIMEOUT) -> str:
    """Ask one question on the terminal, wait up to `timeout` seconds, and fall back to the default.

    Numbers pick from `options`. An empty line, EOF or silence returns the default."""
    if isinstance(options, str) and default is None:  # called as ask_fn(prompt, default)
        options, default = None, options
    options = list(options) if options else []
    if default is None:
        default = options[0] if options else ""
    print(prompt, file=sys.stderr)
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}", file=sys.stderr)
    shown = f" [{default}]" if default else ""
    print(f"Answer within {int(timeout)}s, or press Enter for the default{shown}: ", end="", file=sys.stderr, flush=True)
    try:
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        line = sys.stdin.readline().strip() if ready else ""
    except (OSError, ValueError):  # stdin is not selectable
        line = ""
    if not line:
        print(f"\nNo answer, using: {default or '(nothing)'}", file=sys.stderr)
        return default
    if line.isdigit() and 1 <= int(line) <= len(options):
        return options[int(line) - 1]
    return line


def _open_logs_window(run_id: str) -> None:
    """On a Mac, open a second Terminal window that follows this run's event log, unless one is already
    following (the ./research-agent launcher opens its own) or RESEARCH_NO_LOGS_WINDOW is set. Never raises."""
    try:
        if sys.platform != "darwin" or os.environ.get("RESEARCH_NO_LOGS_WINDOW") or not sys.stderr.isatty():
            return
        import subprocess

        busy = subprocess.run(["pgrep", "-f", "research-agent-logs|research logs"], capture_output=True, text=True).stdout.strip()
        if busy:
            return
        root = str(Path(__file__).resolve().parent.parent)
        script = ('on run argv\n'
                  'tell application "Terminal" to do script ("cd " & quoted form of (item 1 of argv) & " && " & '
                  'quoted form of (item 2 of argv) & " -m research logs " & quoted form of (item 3 of argv) & " --follow")\n'
                  'end run')
        subprocess.Popen(["osascript", "-e", script, root, sys.executable, run_id],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:  # noqa: BLE001 - a missing log window must never stop a run
        pass


def _make_emit(quiet: bool):
    """Progress callback. The first event carries the run id, so announce the run and its debug trail there."""
    from research.agent import console_emit

    state = {"announced": False}

    def emit(ev: dict) -> None:
        rid = ev.get("run_id")
        if rid and not state["announced"]:
            state["announced"] = True
            from research import store

            path = store.RUNS_DIR / str(rid) / "events.jsonl"
            try:
                shown = os.path.relpath(path)
                shown = str(path) if shown.startswith("..") else shown
            except ValueError:
                shown = str(path)
            print(f"Run {rid} started. Watch the full debug trail in another terminal with, tail -f {shown}"
                  f"  (or: python -m research logs {rid} --follow)", file=sys.stderr, flush=True)
            _open_logs_window(str(rid))
        if not quiet:
            console_emit(ev)

    return emit


def _check_pdfs(paths: list[str] | None) -> list[str]:
    ok = []
    for p in paths or []:
        f = Path(p).expanduser()
        if not f.is_file():
            raise _Usage(f"PDF not found: {p}")
        try:
            with f.open("rb") as fh:
                head = fh.read(1024)
        except OSError as e:
            raise _Usage(f"cannot read {p}: {e.strerror}")
        if b"%PDF-" not in head:
            print(f"warning: {p} does not look like a PDF; the agent skips it if it cannot read it", file=sys.stderr)
        ok.append(str(f))
    return ok


def _with_assumptions(result):
    """store.load_run may not restore `assumptions`; fall back to the saved result.json."""
    if getattr(result, "assumptions", None):
        return result
    try:
        from research import store

        saved = json.loads((store.RUNS_DIR / result.run_id / "result.json").read_text(encoding="utf-8"))
        result.assumptions = [str(a) for a in saved.get("assumptions", []) if str(a).strip()]
    except (OSError, ValueError, AttributeError):
        pass
    return result


def _render(result) -> tuple[Path | None, Path | None]:
    """Write runs/<run_id>/report.pdf (answer) and trace.pdf (audit trail). A failure is reported, never fatal to the run."""
    from research import store
    from research.report import render_pdf, trace_path_for

    out = store.run_dir(result.run_id) / "report.pdf"
    try:
        render_pdf(result, str(out))
    except Exception as e:  # the saved run is still good; `show --rebuild` can redo the PDFs
        _err(f"could not write the PDF report ({type(e).__name__}: {e}). Retry with: python -m research show {result.run_id} --rebuild")
        return None, None
    trace = Path(trace_path_for(str(out)))
    return out, (trace if trace.exists() else None)


def _summary(result, pdfs: tuple[Path | None, Path | None]) -> str:
    pdf, trace = pdfs
    n = {s: sum(1 for c in result.claims if c.status == s) for s in ("supported", "contested", "unsupported")}
    open_c = sum(1 for c in result.conflicts if not c.resolved)
    st = result.stats or {}
    took = f"{_secs(st['seconds'])}, " if "seconds" in st else ""
    tokens = f"{int(st['tokens']):,} tokens" if isinstance(st.get("tokens"), (int, float)) else ""
    lines = [f"Run {result.run_id} finished ({took}{tokens})".replace(", )", ")").replace("()", "").rstrip(),
             f"  {len(result.claims)} claims: {n['supported']} supported, {n['contested']} contested, {n['unsupported']} unsupported;"
             f" {open_c} open conflicts; {len(result.sources)} sources"]
    for a in getattr(result, "assumptions", None) or []:
        lines.append(f"  Assumed: {a}")
    lines.append(f"  Report: {file_url(pdf)}" if pdf else "  Report: not written (see the error above)")
    lines.append(f"  Trace:  {file_url(trace)}" if trace else "  Trace:  not written")
    lines.append(f"  Details: python -m research show {result.run_id}")
    return "\n".join(lines)


def file_url(p) -> str:
    """The full absolute path as a file:// link, which most terminals let you click."""
    from urllib.parse import quote

    return "file://" + quote(str(Path(p).expanduser().resolve()))


def open_pdfs(*paths) -> None:
    """Open each existing file with the system's default app for PDFs. Skipped when RESEARCH_NO_OPEN is set or
    stdout is not a terminal (pipes, tests, evals). Never raises."""
    try:
        if os.environ.get("RESEARCH_NO_OPEN") or not sys.stdout.isatty():
            return
        import subprocess

        opener = "open" if sys.platform == "darwin" else "xdg-open"
        for p in paths:
            if p and Path(p).exists():
                subprocess.Popen([opener, str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:  # noqa: BLE001 - failing to open a viewer must never fail a finished run
        pass


def cmd_run(args: argparse.Namespace) -> int:
    from research.llm import MissingAPIKeyError, get_api_key

    question = " ".join(args.question).strip()
    if not question:
        raise _Usage("the question is empty")
    if args.budget_mins <= 0:
        raise _Usage("--budget-mins must be greater than 0")
    pdfs = _check_pdfs(args.pdf)
    try:
        get_api_key()  # also loads .env
    except MissingAPIKeyError as e:
        raise _Usage(str(e))

    from research.agent import run_research

    kwargs = {}
    can_ask = not args.no_clarify and sys.stdin.isatty()
    if can_ask and "ask_fn" in inspect.signature(run_research).parameters:
        kwargs["ask_fn"] = terminal_ask
    result = run_research(question, pdfs, args.budget_mins, emit=_make_emit(args.quiet), **kwargs)
    pdfs_out = _render(result)
    print(_summary(result, pdfs_out))
    open_pdfs(*pdfs_out)
    return 0


def _wrap(text: str, indent: str = "  ") -> str:
    return textwrap.fill(" ".join(str(text).split()), width=100, initial_indent=indent, subsequent_indent=indent)


def cmd_show(args: argparse.Namespace) -> int:
    from research import store

    if not args.run_id:
        runs = store.list_runs(10)
        if not runs:
            print("No saved runs yet. Start one with: python -m research run \"<question>\"")
            return 0
        for r in runs:
            print(f"{r['run_id']}  {str(r['question'])[:80]}")
        return 0
    try:
        result = _with_assumptions(store.load_run(args.run_id))
    except KeyError as e:
        raise _Usage(e.args[0] if e.args else f"no saved run matches '{args.run_id}'")
    print(f"Question\n{_wrap(result.question)}\n\nAnswer\n{result.answer_md.strip() or '  (none)'}\n")
    print("Claims")
    for c in sorted(result.claims, key=lambda c: -c.confidence):
        print(_wrap(f"{c.id} [{c.status}, {c.confidence:.0%}, {len(c.evidence)} sources] {c.text}"))
    for cf in result.conflicts:
        print(f"\nConflict ({'resolved' if cf.resolved else 'open'}): {', '.join(cf.claim_ids)}\n{_wrap(cf.reason)}")
    for title, items in (("Assumptions", getattr(result, "assumptions", [])), ("Uncertainty", result.uncertainty_notes)):
        if items:
            print(f"\n{title}")
            for it in items:
                print(_wrap(f"- {it}"))
    print(f"\nSources ({len(result.sources)})")
    for i, s in enumerate(result.sources, 1):
        print(f"  [{i}] {s.url}")
    pdf = store.run_dir(result.run_id) / "report.pdf"
    trace = pdf.with_name("trace.pdf")
    if args.rebuild or not pdf.exists() or not trace.exists():
        pdf, trace = _render(result)
    print(f"\nReport: {pdf}" if pdf else "\nReport: not written")
    print(f"Trace:  {trace}" if trace else "Trace:  not written")
    return 0


def _event_files() -> list[Path]:
    from research import store

    root = Path(store.RUNS_DIR)
    if not root.is_dir():
        return []
    return sorted((d / "events.jsonl" for d in root.iterdir() if (d / "events.jsonl").is_file()), key=lambda p: p.parent.name)


def _find_events(run_id: str, wait: float = 0.0) -> Path:
    """events.jsonl for a run id, a unique prefix, or 'latest'. Reads the folder, so a run still in progress works."""
    deadline = time.time() + wait
    while True:
        files = _event_files()
        if run_id in ("", "latest"):
            if files:
                return max(files, key=lambda p: p.stat().st_mtime)
        else:
            exact = [p for p in files if p.parent.name == run_id]
            near = [p for p in files if p.parent.name.startswith(run_id)]
            if exact or len(near) == 1:
                return (exact or near)[0]
            if len(near) > 1:
                raise _Usage(f"'{run_id}' is ambiguous: " + ", ".join(p.parent.name for p in near[:5]))
        if time.time() >= deadline:
            raise _Usage("no runs yet. Start one with: python -m research run \"<question>\"" if not files
                         else f"no run matches '{run_id}'. Recent: " + ", ".join(p.parent.name for p in files[-3:]))
        time.sleep(0.5)


def _fmt_event(raw: str, width: int) -> tuple[str, str]:
    """One readable line for one events.jsonl record, plus its type."""
    try:
        ev = json.loads(raw)
    except ValueError:
        ev = None
    if not isinstance(ev, dict):
        return raw.strip()[:width], ""
    try:
        t = float(ev.get("t"))
        stamp = f"{int(t) // 60}:{int(t) % 60:02d}"
    except (TypeError, ValueError):
        stamp = str(ev.get("ts", ""))[11:19]
    kind = str(ev.get("type", "event"))
    text = str(ev.get("msg") or "").strip()
    if not text:
        text = ", ".join(f"{k}={str(v)[:60]}" for k, v in ev.items() if k not in ("ts", "t", "type", "msg"))
    line = f"[{stamp:>5}] {kind:<11} {' '.join(text.split())}"
    return (line if len(line) <= width else line[: width - 3] + "..."), kind


def cmd_logs(args: argparse.Namespace) -> int:
    path = _find_events(args.run_id or "latest", wait=15.0 if args.follow else 0.0)
    width = shutil.get_terminal_size((140, 24)).columns if sys.stdout.isatty() else 200
    print(f"Run {path.parent.name}  ({path})", file=sys.stderr)
    pos, buf, finished = 0, b"", False
    while True:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if size < pos:  # file was replaced
            pos, buf = 0, b""
        if size > pos:
            with path.open("rb") as f:
                f.seek(pos)
                buf += f.read()
                pos = f.tell()
            *lines, buf = buf.split(b"\n")
            for raw in lines:
                if raw.strip():
                    line, kind = _fmt_event(raw.decode("utf-8", "replace"), width)
                    print(line, flush=True)
                    finished = finished or kind == "done"
        if not args.follow or finished:
            if buf.strip():
                print(_fmt_event(buf.decode("utf-8", "replace"), width)[0])
            return 0
        time.sleep(0.4)


def cmd_chat(rest: list[str]) -> int:
    try:
        from research.chat import main as chat_main
    except ModuleNotFoundError as e:
        if e.name != "research.chat":
            raise
        print("The interactive chat is not installed in this checkout; showing the commands instead.\n", file=sys.stderr)
        build_parser().print_help(sys.stderr)
        return 2
    return int(chat_main(rest) or 0)


def cmd_eval(rest: list[str]) -> int:
    if not rest or rest[0] != "run":
        raise _Usage("usage: python -m research eval run [--cases a,b] [--repeats 3] [--budget-mins 3] [--fake]")
    try:
        from evals.run_eval import main as eval_main
    except ModuleNotFoundError as e:
        if e.name in ("evals", "evals.run_eval"):
            raise _Usage("the evaluation suite is missing (evals/run_eval.py)")
        raise
    return int(eval_main(rest[1:]) or 0)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m research", description="Dynamic deep research agent for open-ended financial questions.")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="research a question and write a cited PDF report")
    r.add_argument("question", nargs="+", help="the question, in quotes")
    r.add_argument("--pdf", action="append", metavar="FILE", help="a PDF to use as context (repeatable)")
    r.add_argument("--budget-mins", type=float, default=10.0, help="time budget in minutes (default 10)")
    r.add_argument("--no-clarify", action="store_true", help="never ask a clarifying question (also off when stdin is not a terminal)")
    r.add_argument("--quiet", action="store_true", help="hide progress logs")
    r.add_argument("--debug", action="store_true", help="print the traceback on failure")
    s = sub.add_parser("show", help="print a saved run, or list recent runs when no id is given")
    s.add_argument("run_id", nargs="?", help="full run id or a unique prefix")
    s.add_argument("--rebuild", action="store_true", help="rewrite report.pdf from the saved run")
    s.add_argument("--debug", action="store_true", help="print the traceback on failure")
    g = sub.add_parser("logs", help="print a run's event log, one line per event; works on a run still in progress")
    g.add_argument("run_id", nargs="?", default="latest", help="run id, a unique prefix, or 'latest' (default)")
    g.add_argument("--follow", "-f", action="store_true", help="keep printing new events until the run is done")
    g.add_argument("--debug", action="store_true", help="print the traceback on failure")
    sub.add_parser("chat", help="open the interactive chat (also what running with no arguments does)")
    sub.add_parser("eval", help="run the evaluation suite: eval run [flags]")
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    debug = "--debug" in argv
    try:
        if not argv or argv[0] == "chat":  # ./research-agent with no arguments opens the chat
            return cmd_chat(argv[1:])
        if argv[0] == "eval":  # flags after `eval run` belong to evals/run_eval.py
            return cmd_eval(argv[1:])
        ap = build_parser()
        args = ap.parse_args(argv)
        if args.cmd == "run":
            return cmd_run(args)
        if args.cmd == "show":
            return cmd_show(args)
        if args.cmd == "logs":
            return cmd_logs(args)
        ap.print_help(sys.stderr)
        return 2
    except _Usage as e:
        _err(str(e))
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except Exception as e:
        _err(f"{type(e).__name__}: {e}" + ("" if debug else "  (rerun with --debug for the traceback)"))
        if debug:
            traceback.print_exc()
        return 1
