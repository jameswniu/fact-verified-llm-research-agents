# Decisions

What was chosen, what each choice costs, and what was left out on purpose.

## Tradeoffs

| Decision | What it buys | What it costs |
|---|---|---|
| A time budget, not a cost cap | A run that ends when you said it would, so you can plan around it | Cost varies with how much the model writes in that time, and there is no hard spend limit |
| Research gets 65 percent of the budget | Checking and writing are never starved of time | A short budget means fewer follow-up rounds and a thinner answer |
| Five searches at once | Wall-clock time, so a 10 minute run can cover eight sub-questions and up to three rounds | A busy or low-limit API key sees retries and slower runs |
| One model family, Gemini Flash, with thinking off for most steps | Low cost and latency, with one key and one client to manage | The checker shares blind spots with the writer, and the `-latest` alias can move between runs |
| A written source rule, not a soft score | A claim with one blog behind it cannot be called supported | A true claim that only one non-official site reports is left out |
| A word-and-number match against the page text | Cheap and repeatable, and the quote shown is a real sentence of the page | A paraphrase fails the match, and a page that cannot be opened cannot be checked |
| Dropping claims that fail the rule instead of hedging them in the answer | The answer holds only claims with sources | A reader sees dropped claims only in the ledger |
| Always returning a result | Something usable on a bad day, with the gaps written down | A thin answer can look complete if the uncertainty section is skipped |

## What was cut, and why

Steering a run while it works. It needs agents that can be interrupted and a lock on the claim ledger, and a half-steered run is hard to reproduce. Saved runs plus a follow-up command give most of the value without that risk, and the Roadmap at the end of the README describes it.

A web interface. The task is a terminal tool that leaves a PDF. A web interface adds a server, sessions and state, and none of that makes the research better.

Reading PDFs found on the web. The page fetcher reads HTML and plain text itself, and for a cited PDF it calls poppler's `pdftotext` on the first pages when that tool is installed. It was kept to that because a PDF reader built into the project adds a dependency and download time on every source. The cost is that without poppler, or past the first pages, a central-bank or working-paper PDF cannot be checked against its text and stays link-only.

A second model or search provider as an independent checker. It is the right next step for correlated errors, and it doubles the keys and the cost.

Resuming a crashed run. The trace survives, so you can see what happened, but the run is not continued from it.

A cache of searches and pages. Two runs of one question pay twice and can differ.

A calibrated confidence score. The score is a rule written down, not one fitted to labelled claims. ARCHITECTURE.md, Research quality, says how it works and what calibrating it would take.

## Reasoning and ownership

Honest reasoning about the choices and the priorities behind them.

### What was built

The pipeline in ARCHITECTURE.md, a store with a full event trace, two PDFs per run, a command line, an eval harness with eight cases run three times each and scored without a judge model, and a small offline test suite.

### Reliability, latency and cost

Reliability came first. A run always returns a result, a claim needs sources by a written rule, and what could not be checked is listed. That costs some answers, since a true claim that only one non-official site reports is left out and a short budget gives a thin report.

For latency, the work that can run in parallel does, five searches at a time, and the time budget is a hard knob. Research stops at 65 percent of it so checking and writing always have room. For cost, one cheap model does everything, with thinking switched off for most steps, and cost is reported per run by the eval harness. The budget limits time and not spend, so a cost cap would need a token limit that does not exist yet.

### What was cut

Steering a run while it works, a web interface, reading cited PDFs without needing a system tool, a second model as an independent checker, resuming a crashed run, and a cache of searches and pages. [DECISIONS.md](DECISIONS.md) says why for each. The first of these is written up in the Roadmap at the end.

### Ownership

If you inherit this, start at the constants at the top of `research/agent.py` (rounds, workers, the source lists, the score), and change the environment with `RESEARCH_MODEL`, `RESEARCH_CONCURRENCY`, `RESEARCH_DOC_MODE`, `RESEARCH_RUNS_DIR` and the `EVAL_PRICE_*` variables. To find out why an answer looks wrong, open that run's `events.jsonl` and `trace.pdf`, find the claim in the ledger, and follow it to the page. The first thing to improve is the calibration of the score, and the second is reading cited PDFs without relying on poppler's `pdftotext`, which is optional today.
