"""Run persistence: SQLite for results, runs/<run_id>/events.jsonl for the execution trace."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import asdict
from pathlib import Path

from .models import Claim, Conflict, Evidence, RunResult, Source

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = Path(os.environ.get("RESEARCH_RUNS_DIR") or ROOT / "runs")
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, question TEXT, answer_md TEXT,
  uncertainty_json TEXT, stats_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, assumptions_json TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS sources (run_id TEXT, idx INTEGER, url TEXT, author TEXT, org TEXT,
  date_written TEXT, fetched_at TEXT, snippet TEXT, PRIMARY KEY (run_id, idx));
CREATE TABLE IF NOT EXISTS claims (run_id TEXT, idx INTEGER, id TEXT, text TEXT, kind TEXT, status TEXT,
  confidence REAL, evidence_json TEXT, PRIMARY KEY (run_id, idx));
CREATE TABLE IF NOT EXISTS conflicts (run_id TEXT, idx INTEGER, claim_ids_json TEXT, reason TEXT,
  resolved INTEGER, PRIMARY KEY (run_id, idx));
"""


def run_dir(run_id: str) -> Path:
    d = RUNS_DIR / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _db() -> sqlite3.Connection:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(RUNS_DIR / "research.db", timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    if "assumptions_json" not in {r["name"] for r in con.execute("PRAGMA table_info(runs)")}:
        con.execute("ALTER TABLE runs ADD COLUMN assumptions_json TEXT DEFAULT '[]'")  # older database file
        con.commit()
    return con


def append_event(run_id: str, event: dict) -> None:
    """Append one JSON line to runs/<run_id>/events.jsonl."""
    line = json.dumps(event, ensure_ascii=False, default=str)
    with _lock, open(run_dir(run_id) / "events.jsonl", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_events(run_id: str) -> list[dict]:
    """The event trace of a run. Works for runs that crashed before save_run, via the run directory."""
    path = RUNS_DIR / resolve_run_id(run_id) / "events.jsonl"
    if not path.exists():
        return []
    out = []
    for x in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(x))
        except json.JSONDecodeError:
            continue  # a line cut short by a crash
    return out


def save_run(result: RunResult) -> Path:
    """Persist a RunResult (idempotent per run_id). Also writes runs/<run_id>/result.json."""
    rid = result.run_id
    with _lock:
        con = _db()
        try:
            with con:
                for t in ("runs", "sources", "claims", "conflicts"):
                    con.execute(f"DELETE FROM {t} WHERE run_id = ?", (rid,))
                con.execute("INSERT INTO runs (run_id, question, answer_md, uncertainty_json, stats_json, assumptions_json) "
                            "VALUES (?,?,?,?,?,?)",
                            (rid, result.question, result.answer_md, json.dumps(result.uncertainty_notes),
                             json.dumps(result.stats), json.dumps(result.assumptions)))
                con.executemany("INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)",
                                [(rid, i, s.url, s.author, s.org, s.date_written, s.fetched_at, s.snippet)
                                 for i, s in enumerate(result.sources)])
                con.executemany("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?)",
                                [(rid, i, c.id, c.text, c.kind, c.status, c.confidence,
                                  json.dumps([asdict(e) for e in c.evidence])) for i, c in enumerate(result.claims)])
                con.executemany("INSERT INTO conflicts VALUES (?,?,?,?,?)",
                                [(rid, i, json.dumps(c.claim_ids), c.reason, int(c.resolved))
                                 for i, c in enumerate(result.conflicts)])
        finally:
            con.close()
    d = run_dir(rid)
    (d / "result.json").write_text(json.dumps(asdict(result), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return d


def resolve_run_id(run_id: str) -> str:
    """Accept a full run id or a unique prefix, from saved rows or run directories (a crashed run has only a
    directory). Raises KeyError when nothing or several match."""
    con = _db()
    try:
        like = run_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = {r["run_id"] for r in con.execute("SELECT run_id FROM runs WHERE run_id LIKE ? ESCAPE '\\'", (like,))}
    finally:
        con.close()
    if RUNS_DIR.is_dir():
        rows |= {d.name for d in RUNS_DIR.iterdir() if d.is_dir() and d.name.startswith(run_id)}
    if run_id in rows:
        return run_id
    if len(rows) == 1:
        return next(iter(rows))
    raise KeyError(f"no saved run matches '{run_id}'" if not rows else f"'{run_id}' is ambiguous: {', '.join(sorted(rows)[:5])}")


def load_run(run_id: str) -> RunResult:
    rid = resolve_run_id(run_id)
    con = _db()
    try:
        r = con.execute("SELECT * FROM runs WHERE run_id = ?", (rid,)).fetchone()
        if r is None:
            raise KeyError(f"run '{rid}' has no saved result (it may have crashed); its trace is in {RUNS_DIR / rid / 'events.jsonl'}")
        sources = [Source(s["url"], s["author"], s["org"], s["date_written"], s["fetched_at"], s["snippet"])
                   for s in con.execute("SELECT * FROM sources WHERE run_id = ? ORDER BY idx", (rid,))]
        claims = [Claim(c["id"], c["text"], c["kind"], c["status"], c["confidence"],
                        [Evidence(**e) for e in json.loads(c["evidence_json"])])
                  for c in con.execute("SELECT * FROM claims WHERE run_id = ? ORDER BY idx", (rid,))]
        conflicts = [Conflict(json.loads(c["claim_ids_json"]), c["reason"], bool(c["resolved"]))
                     for c in con.execute("SELECT * FROM conflicts WHERE run_id = ? ORDER BY idx", (rid,))]
    finally:
        con.close()
    return RunResult(run_id=rid, question=r["question"], sources=sources, claims=claims, conflicts=conflicts,
                     answer_md=r["answer_md"], uncertainty_notes=json.loads(r["uncertainty_json"]),
                     assumptions=json.loads(r["assumptions_json"] or "[]"), stats=json.loads(r["stats_json"]))


def list_runs(limit: int = 20) -> list[dict]:
    con = _db()
    try:
        return [dict(r) for r in con.execute(
            "SELECT run_id, question, created_at FROM runs ORDER BY created_at DESC, run_id DESC LIMIT ?", (limit,))]
    finally:
        con.close()
