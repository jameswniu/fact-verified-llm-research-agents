#!/usr/bin/env python3
"""Fail when README.md disagrees with the recorded run, the figures, the unit tests or the landing limits.

tools/facts.py computes every number from evals/results/latest.json. This checker compares the README against it:
the shields.io badge values, the figure and GIF references, key numbers written in prose, whether each figure file
matches its generator (`--check`), whether the tests badge equals a real run of the unit tests with no API key
(passed means tests run minus tests skipped), and the landing limits (word count, paragraph and sentence length, badge
and image counts, a picture near the top). One line is printed per check. Exit 0 and a final OK line when all pass,
exit 1 on any drift.

    python3 tools/check_readme.py
"""
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
README = REPO / "README.md"
sys.path.insert(0, str(HERE))
import facts  # noqa: E402

BADGE_RE = re.compile(r"img\.shields\.io/badge/([A-Za-z_]+)-([^-\"\s?]+)-[0-9a-fA-F]{6}")
FIGURES = ("media/hero.svg", "media/pipeline.svg", "media/results.svg")
MAX_WORDS, MAX_PARA, MAX_SENT = 900, 70, 35
bad = []


def ok(msg):
    print(f"ok    {msg}")


def fail(msg):
    bad.append(msg)
    print(f"DRIFT {msg}")


def decode(v):
    return v.replace("%2F", "/").replace("%24", "$").replace("_", " ")


def prose(text):
    """Visible prose: no code fences, HTML tags or code spans. Table cells and bullets stay."""
    t = re.sub(r"```.*?```", "", text, flags=re.S)
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"`[^`]*`", "", t)
    t = re.sub(r"\]\([^)]*\)", "]", t)
    return t


def main():
    text = README.read_text()
    _, f = facts.load()
    ok(f"facts: latest.md matches the tables rebuilt from latest.json ({f['eval_date']})")

    expected = {
        "runs": f"{f['runs_ok']}/{f['runs']}",
        "citations": f"{f['cit_valid']}/{f['cit_checked']}",
        "median": f"{f['p50']} s",
        "cost": f"{f['cost']} per run",
        "license": "MIT",
    }
    found = {}
    for label, value in BADGE_RE.findall(text):
        found[label] = decode(value)
    for label, want in expected.items():
        got = found.get(label)
        if got is None:
            fail(f"badge {label} is missing from the README")
        elif got != want:
            fail(f"badge {label} says {got}, recorded run says {want}")
        else:
            ok(f"badge {label} {got}")
    t = facts.test_counts()
    got = found.get("tests")
    want = f"{t['passed']} passing"
    if got != want:
        fail(f"badge tests says {got}, a real run says {want} ({t['ran']} ran, {t['skipped']} skipped)")
    else:
        ok(f"badge tests {got} ({t['ran']} ran, {t['skipped']} skipped)")

    r = f["rules"]
    pairs = {
        "citations valid": f"{f['cit_valid']} of {f['cit_checked']}",
        "citation percent": f"{f['cit_pct']}%",
        "median seconds": f"{f['p50']} seconds",
        "p95 seconds": f"{f['p95']} seconds",
        "cost": f"{f['cost']}",
        "tier rule": f"{r['tier'][0]} of {r['tier'][1]}",
        "independence rule": f"{r['independence'][0]} of {r['independence'][1]}",
        "quote on page rule": f"{r['quote_on_page'][0]} of {r['quote_on_page'][1]}",
        "coverage": f"{f['coverage_pct']}%",
        "conflict found": f"{f['conflict_hit_pct']}%",
        "link-only citations": f"{f['link_only']} citations",
        "eval date": f["eval_date"],
        "runs": f"{f['runs']} runs",
        "quote not claim rule": f"{r['quote_not_claim'][0]} of {r['quote_not_claim'][1]}",
        "questions": f"{f['cases']} questions",
        "runs per question": f"{f['runs'] // f['cases']} runs",
        "lowest case coverage": f"{min(c['coverage'] for c in f['per_case'])}%",
        "highest case coverage": f"{max(c['coverage'] for c in f['per_case'])}%",
        "coverage range in the figure text": (f"from {min(c['coverage'] for c in f['per_case'])} to "
                                              f"{max(c['coverage'] for c in f['per_case'])} percent"),
    }
    for name, want in pairs.items():
        if want in text:
            ok(f"prose {name}: {want}")
        else:
            fail(f"prose {name}: README does not contain {want!r}")

    # The page says one question was labelled unstable across its three runs. Count them in the recorded run.
    unstable = sum(1 for c in f["per_case"] if c["verdict"].strip().lower() == "unstable")
    if unstable == 1 and "one question was labelled unstable" in text:
        ok("prose unstable questions: one")
    else:
        fail(f"prose unstable questions: README must say one question was labelled unstable, recorded run has {unstable}")

    for fig in FIGURES:
        if fig not in text:
            fail(f"README does not reference {fig}")
        else:
            ok(f"README references {fig}")
    if "media/demo.gif" not in text:
        fail("README does not reference media/demo.gif")
    else:
        ok("README references media/demo.gif")
    for g in sorted(HERE.glob("render_*.py")):
        p = subprocess.run([sys.executable, str(g), "--check"], capture_output=True, text=True)
        (ok if p.returncode == 0 else fail)(f"figure generator {g.name} {'matches its file' if p.returncode == 0 else 'drifted'}")

    pr = prose(text)
    words = len(pr.split())
    # a bullet or a table row is its own paragraph; plain lines join until a blank line
    paras, cur = [], []
    for ln in pr.splitlines():
        if not ln.strip() or ln.lstrip().startswith(("-", "|", ">", "#")):
            if cur:
                paras.append(" ".join(cur))
                cur = []
            if ln.strip():
                paras.append(ln)
        else:
            cur.append(ln)
    if cur:
        paras.append(" ".join(cur))
    longest_para = max(len(p.split()) for p in paras)
    sents = [s for s in re.split(r"(?<=[.!?])\s+|\n", pr) if s.strip()]
    longest_sent = max(len(s.split()) for s in sents)
    print(f"words {words}, longest paragraph {longest_para} words, longest sentence {longest_sent} words")
    (ok if words <= MAX_WORDS else fail)(f"word count {words} of {MAX_WORDS}")
    (ok if longest_para <= MAX_PARA else fail)(f"longest paragraph {longest_para} of {MAX_PARA}")
    (ok if longest_sent <= MAX_SENT else fail)(f"longest sentence {longest_sent} of {MAX_SENT}")
    badges = len(BADGE_RE.findall(text)) + text.count("badge.svg")
    (ok if badges >= 4 else fail)(f"{badges} badges, at least 4")
    imgs = len(re.findall(r"<img ", text))
    (ok if imgs >= 3 else fail)(f"{imgs} images, at least 3")
    (ok if ".gif" in text else fail)("at least 1 GIF")
    first = [ln for ln in text.splitlines() if ln.strip()][:15]
    (ok if any("<img" in ln for ln in first) else fail)("a picture within the first 15 non-empty lines")
    if bad:
        print(f"\n{len(bad)} check(s) failed")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
