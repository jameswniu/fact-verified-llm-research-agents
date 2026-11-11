# Architecture

One run, from question to report, in order. The command is `python -m research run "<question>"`, and the file that does each step is named at the end of it.

1. The command line checks the input (an empty question, a missing PDF, a missing API key) and starts the run. `research/cli.py`
2. A clarity check decides whether the question needs one clarifying question, or picks a reading and writes the assumption down. `research/clarify.py`
3. Any PDF you supplied is validated, read by the model, and turned into claims. `research/agent.py`, `research/llm.py`
4. The planner applies six lenses to the question and makes 5 to 8 sub-questions, depending on the budget. `research/agent.py`
5. One worker per sub-question, five at a time, searches with Google Search grounding and pulls out claims. `research/agent.py`, `research/llm.py`
6. The cited pages are opened and their text, author and date are kept. `research/llm.py`
7. A ledger merges duplicates, finds conflicts, and proposes leads and gaps. Up to three follow-up rounds search those. `research/agent.py`
8. Each claim is checked against its page and given a tier, a status and a confidence. Claims that fail the source rule are dropped from the answer. `research/agent.py`
9. The answer is written from the claims that passed, citing claim ids. `research/agent.py`
10. The result is saved and the two PDFs are drawn. `research/store.py`, `research/report.py`

Every step writes a narrated line to the console and an event to the log as it happens.

## Where things land

Each run gets its own folder, `runs/<run id>/`, for example `runs/20261009-143152-ebdf/`.

- `events.jsonl` is the event log, one JSON object per line, appended as the run goes. A run that crashes still leaves this file.
- `result.json` is the whole result, with the question, sources, claims and their evidence, conflicts, the answer, assumptions and stats.
- `report.pdf` is the short report for a reader. It has the answer, its assumptions and limits, how strong the evidence is, and the sources.
- `trace.pdf` is the full trace of the same run. It has the budget and tokens, the plan and sub-question tree, a timeline of every step, the claim ledger, conflicts and how they resolved, verifier results, and the uncertainty notes.

The `samples/` folder holds the two PDFs of one real run, in `samples/demo_run/` as `report.pdf` and `trace.pdf`. The report links to `trace.pdf` by name, so keep the two together.

Beside the run folders, `runs/research.db` is a SQLite file holding every run's result in four tables (runs, sources, claims, conflicts), which is what `python -m research show` reads.

## When it stops

Research ends when the budget is nearly used (it gets 65 percent of the time you give), when no open conflicts, leads or gaps are left, when a round adds no new sources or claims, or after three follow-up rounds. Verification and writing then run in the remaining time.

## Three layers you can watch

The system shows itself at three levels, so you can look at whichever one you need.

The conceptual layer is what the person using it sees. In the chat, narrated progress lines say what the agent is deciding: planning, checking where economists disagree, settling a conflict, stopping because the budget is nearly used. A heartbeat line appears after 10 quiet seconds so a long run never looks stuck. The finished `report.pdf` is the conceptual result.

The structural layer is how the pieces are put together. That is the agent graph (a planner, one research agent per sub-question, a conflict and gap check, a verifier), the claim ledger and the run store, drawn on the Excalidraw board and kept in `research/agent.py`, `research/store.py` and `research/report.py`.

The physical layer is the raw record of what actually happened. Every model call, page fetch and heartbeat is one line in `runs/<run_id>/events.jsonl`. Follow it live from a second terminal with `tail -f` or `python -m research logs latest --follow`. `trace.pdf` is the same record laid out for reading, step by step, with times.

## Design in detail

The step-to-file map is at the top of this file.

The design is one pipeline with a loop in the middle. A question goes in, a planner splits it into sub-questions, workers search in parallel, a ledger collects the claims, follow-up rounds chase conflicts and gaps, a verifier applies the source rules, and a writer produces the answer from what survived.

### Execution flow

1. A clarity check (`research/clarify.py`). One cheap model call decides whether the question has two readings that would send the research in different directions and whether the default reading is doubtful (under 0.6 confidence). If both are true it asks one question and waits 20 seconds. Otherwise it picks the likelier reading, writes the assumption down, and shows it on the console and in the report. It never asks twice.
2. Documents. Any PDF you supplied is checked (size, header, not encrypted, not cut off), sent to the model, and mined for up to 12 claims, which go into the ledger. A PDF that cannot be read is skipped and the report says so. By default the whole PDF is also attached to every research agent, so each one can read all of it and check it against outside sources. `RESEARCH_DOC_MODE` changes that. `full` is the default. `picked` gives each agent only the few passages that fit its own sub-question, picked by a small model call, and `start` uses the document only to seed the ledger and the plan. In one side-by-side test on the same question and an unrelated PDF, `full` kept the most claims and sources (185 claims, 33 sources against 160 and 26 for `start` and 155 and 13 for `picked`) and used about 50 percent more tokens (182,204 against roughly 104,000 to 121,000). It is one run each on a PDF that did not match the question, so it shows the cost, not that the document helps.
3. Plan. The planner applies six fixed lenses to the bare question. They are the hard numbers and their primary sources, where economists disagree, what would have happened otherwise, comparisons across countries and periods, what cannot be verified, and the strongest case for the other side. It skips a lens when it does not fit the question and says why on the console. It turns them into 5 sub-questions for a budget under 5 minutes, 6 for 5 minutes up to under 10, and 8 for 10 minutes or more. You never have to ask for these angles.
4. Parallel research. Each sub-question goes to its own worker, five at a time by default (`RESEARCH_CONCURRENCY` changes it). A worker asks Gemini with Google Search grounding to write up to 300 words of notes with source markers, then a second call pulls up to ten atomic claims from the notes, each tagged as a number or a statement and tied to the sources that back it.
5. Opening the sources. The search tool returns redirect links. The agent follows each to the real page, downloads it (8 second timeout, first 600 KB), and keeps the visible text plus the author, date and site name when the page declares them.
6. The ledger. Claims from all workers go into one ledger. A consolidation call merges duplicates, groups the claims that contradict each other with a one-sentence reason, and proposes up to three leads (a named episode, institution or dataset worth its own search) and up to three gaps (an aspect of the question the ledger does not answer).
7. Follow-up rounds. Open conflicts (at most two per round), leads and gaps become up to five new searches per round, skipping any question that overlaps one already asked. Steps 4 to 6 then repeat on the new work.
8. Verification and the answer, described under Research quality below. Only claims that pass go to the writer, and the report renderer (`research/report.py`) draws the PDFs.

### When it stops

The loop ends for one of four reasons and the run records which. The budget is nearly used up (research gets 65 percent of your time, and no new round starts with fewer than 45 seconds of research time left). Nothing is left to chase, meaning no open conflicts, leads or gaps. A round added no new sources and no new claims. Or it reached three follow-up rounds, a fixed cap that keeps cost and time bounded.

### State

All state for a run sits in one in-memory object while it runs. It holds the ledger (claim id, text, kind, and the sources and passages behind it), the source table, the open conflicts, leads and gaps, the questions already asked, token and call counters, and the deadline. Nothing carries over between runs.

What goes to disk is for people to inspect, not for the agent to resume from. The event log is appended as the run goes, so a run that crashes still leaves its trace, and `show` can list it from its folder. At the end the result is saved to a SQLite file (`runs/research.db`, which has four tables for runs, sources, claims and conflicts) and to `runs/<run id>/result.json`.

### Tools

The agent has two tools and no framework. One is the Gemini `generateContent` REST endpoint called with an API key, in three modes. It uses Google Search grounding for research, JSON mode for the structured steps (plan, extract, consolidate, passage check), and plain mode for the final write. The other is a plain HTTP page fetcher built on `urllib`. The default model is `gemini-flash-latest` and `RESEARCH_MODEL` changes it. There is no Vertex AI, no cloud SDK and no agent library, so the whole control flow can be read in `research/agent.py`.

### Data model

```python
Source(url, author, org, date_written, fetched_at, snippet)
Evidence(source_url, quote, stance)        # stance is "supports" or "refutes"
Claim(id, text, kind, status, confidence, evidence)
Conflict(claim_ids, reason, resolved)
RunResult(run_id, question, sources, claims, conflicts, answer_md,
          uncertainty_notes, assumptions, stats)
```

`kind` is `qual` or `quant`. `status` is `supported`, `contested` or `unsupported`. `confidence` runs from 0 to 1 and is explained under Research quality below. `stats` holds tokens, seconds, nodes (the number of model-driven steps), searches, rounds, why the run stopped, and the citation-check counts. The agent only writes `supports` today. Disagreement is recorded at the claim level, as a `Conflict`.

## Research quality

Depth, evidence, analysis and an answer you can defend. The agent is built so that every sentence in the answer can be walked back to a claim, every claim to a page, and every gap or disagreement is written down rather than smoothed over.

### How sources are chosen and traced

The search tool picks the pages, and the prompt tells it to prefer primary and authoritative sources (central banks, statistical agencies, regulators, official filings, working papers) over blogs and news summaries. Each sub-question is its own search, and the five lenses push the research toward disagreement and counterfactuals instead of one narrative.

Each claim keeps the sources behind it. The redirect link the search tool returns is followed to the real page, and each source carries its author, organization, publication date and retrieval time when the page says them. The PDF numbers every source and links each claim to its sources and back.

### How claims are checked

A claim is one atomic statement with its figures, units and dates. It is checked in three steps.

First the agent opens each cited page and looks for the one sentence that best covers the claim's numbers and key terms. That sentence is kept as the claim's quote, word for word, and only when it covers at least half of them. If no sentence does, the page does not count as support for that claim.

Second, a separate model call is given the claim and that sentence and says whether the sentence supports the claim, supports it only in part, or does not support it. A claim whose sentence does not support it is dropped.

Third, the source rule below decides whether the sources are enough. A claim that fails it is marked unsupported, kept out of the answer, and still listed in the ledger so a reader can see it was dropped.

### Conflicts and gaps

The consolidation call flags groups of claims that contradict each other, such as two figures for the same measure or opposite conclusions, and ignores differences that are only scope. Each open conflict triggers a tie-breaker search that asks for the primary source behind each figure and why they differ (definitions, dates, revisions, scope). A claim inside a conflict nobody resolved stays in the answer as contested, loses confidence, and the answer must give each side with its own claim ids.

Gaps work the same way. The ledger proposes what it cannot yet answer, follow-up rounds try to fill them, and whatever is still open at the end is listed in the report as not established.

### The answer

The writer is given only the surviving claims, with their status, confidence and source tier, and told to cite claim ids in square brackets (such as `[c14]`), to state each side of a disagreement separately, to phrase corroborated-only claims as reported and not established, and to label inference as inference. In the PDF each id jumps to the claim and its sources.

### How confidence is decided

Every kept claim carries a confidence between 0.05 and 0.95. That number measures how strong the evidence is. It is not a probability, and 0.75 does not mean three chances in four of being right. It is a heuristic, written down here so anyone can challenge it, and the constants sit at the top of `research/agent.py` where they are easy to change.

The first part of the rule is how many sources a claim needs, which depends on what kind of source they are.

| Source tier | What counts | What a claim needs |
|---|---|---|
| Official | Government and military sites, central banks, international bodies such as the IMF, universities, regulators, filings, and paper repositories such as NBER and SSRN | One source |
| Everything else | News, think tanks, blogs, company sites | Two independent sites, three is better |
| Wikipedia | Counts as one of the two or three | Never enough alone |
| Never counted | Quora, YouTube, social media, forums, question-and-answer sites and document-upload sites such as Scribd | Ignored, even as the second source |

Two pages on the same site, or on subdomains of one organization, count as one source.

The second part is a check on each citation, described above. The agent opens the page, and the claim's numbers and key terms have to appear in a sentence of it, with commas ignored in numbers. A second model call then checks that the sentence supports the claim. Qualitative and quantitative claims go through the same rule, and the only difference is that a claim with figures is matched on its figures first.

The score then works like this.

- An official claim starts at 0.70, adds 0.06 for each further independent official site (up to two), and adds 0.04 for each non-official site that also backs it (up to two). Its ceiling is 0.95.
- A claim with only non-official sources starts at 0.50 with two independent sites and 0.60 with three or more. Its ceiling is 0.65 and 0.75.
- A page that was opened and matched adds 0.08. If no cited page could be opened and matched, the claim loses 0.05 and the ceiling drops to 0.80 for an official claim and 0.55 for the rest.
- A sentence that supports the claim only in part takes off 0.15, and a claim the passage check gave no verdict on takes off 0.03.
- A claim inside an unresolved conflict takes off 0.25 and is labelled contested.
- Nothing goes below 0.05, so a claim that is kept is never shown as impossible, and nothing goes above its ceiling, so nothing is ever shown as certain.

As far as we can tell, no vendor publishes a numeric confidence formula, so there is nothing to copy and nothing to compare this score against. Perplexity and OpenAI's Deep Research attach inline citations and prefer primary sources, and neither says how that turns into a number. The common practice is some mix of source quality, a check that the source really supports the claim, and agreement across independent sources, and that is what this score does. GRADE, the evidence-grading framework from medicine, is sometimes cited for this, but it grades clinical studies and not web pages, so it is a model for having explicit tiers and not a ranker we could apply.

The next step is calibration. Take a set of claims a person has labelled true, false or unclear, run the scorer over them, and check whether claims scored 0.75 are right more often than claims scored 0.50, and by how much. Then move the constants until the numbers mean something. Until that is done, read the score as a way to decide which claims to check first, not as a measure of truth.
