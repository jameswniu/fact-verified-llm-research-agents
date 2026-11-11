# Evaluation

This file describes the eval set, how each run is scored, the recorded results from one live run on 2026-10-09 and how repeatable the runs are.

## The eval set and results

Repeatable checks that show quality and failure modes.

### What a good result means

For this task a good result covers the points an expert would expect, has citations that really are on the pages they point to, shows real disagreement and does not smooth it over, says so when the answer is not public, and finishes inside its time budget at a sensible cost. Each of those has a score, and none of them needs a person to read the answer.

### The eval set

Eight cases, in `evals/cases.py`. Each is a question with a rubric of points the answer should state, written as patterns so scoring is the same every time.

| Case | What it tests |
|---|---|
| 1970s monetary failure | An open causal question with a real academic dispute between monetarist and supply-shock explanations |
| SVB collapse | A mix of qualitative and quantitative claims where regulators, management and rate risk are all blamed |
| Yield curve inversion | A statistical claim with a famous recent miss, which tests calibrated language and numbers |
| Gold price drivers | Competing explanations, since the old link to real yields broke and sources should disagree |
| 1980 vs 2022 inflation peaks | A number-heavy question where each fact has one well-documented value, so a wrong number can be caught |
| False premise | A question that is wrong (the Fed never raised rates to 20 percent in 2010), where a good agent says so |
| PDF with a planted error | Figures only the supplied PDF holds, plus one macro claim in it that contradicts public data |
| Unanswerable private data | Figures that are not public, where the agent has to say so and not invent a sourced number |

### How each run is scored

Coverage is the share of rubric points the answer states, and a point counts when it appears in the answer text, in the agent's claim list or in its uncertainty notes. Citation validity is valid citations over valid plus invalid plus supported claims with no citation, where valid means the quote is found on the live cited page or in its stored snippet, so a quote the live page no longer shows can still count. Conflict found says whether a conflict mentioning an expected disagreement was surfaced, for the cases that have one. The unanswerable case is scored on abstaining without inventing a sourced number. Latency is wall-clock seconds against the budget, and cost is estimated from token counts at Gemini Flash list prices. A set of structural checks also runs on every result, for example no supported claim without evidence and no evidence pointing at a source that is not in the source list.

### How to run it

`python -m research eval run`, with `--cases` for a subset (comma-separated case ids), `--repeats` (default 3), `--budget-mins` (default 3), `--workers`, `--no-url-check` to trust stored snippets instead of fetching the cited pages, and `--fake` for an offline smoke test. Results land in `evals/results/latest.md` and a stamped folder beside it. The clarifying-question rule has its own cases in `evals/clarify_cases.py`, and `tests/` holds offline unit tests for the PDF renderer and the scorer.

### Latest results

Eval run 2026-10-09 14:56, 3 runs per case, budget 2 min per run, cited pages fetched live.

#### Quality

| Case | Runs ok | Coverage | Citation validity | Conflict found | Cost per run |
|---|---|---|---|---|---|
| 1970s monetary failure | 3/3 | 76% | 100% (2/2) | 100% (avg 1.3) | $0.018 |
| SVB collapse | 3/3 | 89% | 100% (8/8) | 67% (avg 1.0) | $0.017 |
| Yield curve inversion | 3/3 | 93% | 100% (21/21) | 0% (avg 0.0) | $0.020 |
| Gold price drivers | 3/3 | 72% | 100% (7/7) | 0% (avg 0.0) | $0.019 |
| 1980 vs 2022 inflation peaks | 3/3 | 87% | 100% (5/5) | None expected (avg 0.0) | $0.014 |
| False premise | 3/3 | 67% | 100% (22/22) | None expected (avg 0.0) | $0.017 |
| PDF with a planted error | 3/3 | 67% | 100% (17/17) | 0% (avg 0.0) | $0.019 |
| Unanswerable private data | 3/3 | 50% | 88% (15/17) | Abstained 100% | $0.016 |
| **All cases** | 24/24 | 75% | 98% (97/99) | 33% | $0.018 |

#### Latency and output files

| Case | Latency p50 (s) | Latency p95 (s) | Report pages (max) | Report within 10 pages | Trace PDF written | Trace written at (s) |
|---|---|---|---|---|---|---|
| 1970s monetary failure | 61 | 64 | 5 | 3/3 | 3/3 | 62 |
| SVB collapse | 49 | 57 | 4 | 3/3 | 3/3 | 49 |
| Yield curve inversion | 54 | 86 | 4 | 3/3 | 3/3 | 54 |
| Gold price drivers | 59 | 67 | 4 | 3/3 | 3/3 | 59 |
| 1980 vs 2022 inflation peaks | 56 | 60 | 4 | 3/3 | 3/3 | 56 |
| False premise | 59 | 63 | 5 | 3/3 | 3/3 | 59 |
| PDF with a planted error | 61 | 68 | 4 | 3/3 | 3/3 | 61 |
| Unanswerable private data | 49 | 56 | 3 | 3/3 | 3/3 | 49 |
| **All cases** | 58 | 68 | | 24/24 | 24/24 | 58 |

#### Source and quote rules (passes out of items checked)

| Case | No claim on wiki or social alone | Two domains when unofficial | Quote is on the page | Quote is not the claim text | Link without a quote | Pages not readable |
|---|---|---|---|---|---|---|
| 1970s monetary failure | 62/62 | 59/62 | 2/2 | 2/2 | 143 | 0 |
| SVB collapse | 47/47 | 47/47 | 8/8 | 8/8 | 72 | 0 |
| Yield curve inversion | 40/40 | 39/40 | 20/22 | 22/22 | 40 | 1 |
| Gold price drivers | 26/26 | 26/26 | 7/7 | 7/7 | 48 | 0 |
| 1980 vs 2022 inflation peaks | 25/25 | 25/25 | 5/5 | 5/5 | 44 | 0 |
| False premise | 47/47 | 47/47 | 21/22 | 22/22 | 58 | 0 |
| PDF with a planted error | 53/53 | 28/53 | 17/17 | 17/17 | 55 | 0 |
| Unanswerable private data | 8/8 | 8/8 | 15/17 | 17/17 | 3 | 0 |
| **All cases** | 308/308 | 279/308 | 95/100 | 100/100 | 463 | 1 |

#### Clarifying-question rules (pass or fail)

| Rule | Runs passed | What it checks | First failure |
|---|---|---|---|
| Clarify: clear question, no ask | 3/3 | A clear question is never answered with a question. | None |
| Clarify: ambiguous question asks once | 3/3 | Two doubtful readings get exactly one one-line question with two options. | None |
| Clarify: never asks twice | 3/3 | After the user answers, even vaguely, the system does not ask again. | None |
| Clarify: non-interactive run proceeds | 3/3 | With no one to ask, the run goes on with the default and records the assumption. | None |
| Clarify: empty or slow answer | 3/3 | An empty answer, None, an error or silence takes the default and does not hang. | None |
| Clarify: mild ambiguity assumes | 3/3 | When one reading is the obvious one, assume it, say so and invite a correction. | None |

Coverage is the share of rubric points the answer states. Citation validity is valid citations over (valid + invalid + supported claims with no citation), where valid means the quote appears on the cited page or its stored snippet. A quote that only the stored snippet holds counts as valid even if the live page no longer shows it, and coverage counts a point found in the claim list as well as in the answer text. Latency is question received to report.pdf written. The trace column is when trace.pdf was written. A page that could not be read counts as not passing the quote rule. Cost is estimated from token counts at Gemini Flash list prices.

What the table shows. Across the 24 runs, coverage averaged 75 percent and citation validity 98 percent (97 of 99 judged citations), at about $0.018 a run and a median of 58 seconds (95th percentile 68 seconds). Every report stayed within 10 pages and every run wrote its trace. Coverage is lowest on the unanswerable-data case (50 percent), and the false premise and planted-error PDF cases both score 67 percent. A conflict was found in 33 percent of runs overall, and none was found in any run of the yield curve, gold and planted-error cases, which all expect one. On the source rules, no claim rests on a wiki or social page alone (308 of 308) and 95 of 100 quotes were found on their page.

Three limits belong next to those numbers. Only 100 of 563 citations carry a quote, because the agent shows a quote only when it could open the page and found a verbatim sentence in it, so the other 463 are links with no quote and citation validity is judged on those 100 only. Before the quote fix, the same check found none of 156 quotes on the cited pages (three live runs, 190 evidence items), so the improvement is measured, and the 5 quote misses now are 2 on the yield curve case, 1 on the false premise case and 2 on the unanswerable case. And the rubric is regex based and written by us, so coverage measures whether points are stated and not whether the reasoning is right, and the planted-error PDF case still misses the planted 4.9 percent yield error in some runs, which makes it a measured weakness and not a pass.

### What the checks do not cover

- The rubric is a set of patterns. A right idea in unexpected words is missed, and a keyword in the wrong context counts.
- Citation validity shows a quote is on the page. It does not show the claim is true in the world.
- Pages a site blocks are counted apart and left out of the validity figure, so the figure reads higher than the share of citations anyone could check.
- Cost is an estimate from token counts, not a bill, and the `-latest` model alias can move.
- Eight cases is a small set, mostly US macro questions in English. It says nothing about equities, other markets or other languages.
- No person grades answer quality, and nothing here tests hostile input such as a web page written to mislead the agent.

[FAILURES.md](../FAILURES.md) has the failure modes in full.

## Reliability

Accuracy, measured three times over. Each eval case runs three times and the answers are compared, because a live web search and a model that is not deterministic mean one good run proves little.

### What is compared

Across the three runs of a case, the harness reports how wide the coverage range is, how many of the same rubric points all runs covered, how much the source sites overlap, and how much the numbers in the quantitative claims agree. A case is called Stable when the same points are covered at least 80 percent of the time and coverage varies by no more than 20 points, Mostly stable at 60 percent or more, and Unstable below that.

### Latest results

The same run as the Evaluation section above.

| Case | Coverage range across runs | Same points covered | Same source sites | Same numbers | Verdict |
|---|---|---|---|---|---|
| 1970s monetary failure | 43% wide | 60% | 25% | 38% | Unstable |
| SVB collapse | 17% wide | 89% | 22% | 23% | Stable |
| Yield curve inversion | 20% wide | 87% | 24% | 21% | Stable |
| Gold price drivers | 17% wide | 63% | 10% | 20% | Mostly stable |
| 1980 vs 2022 inflation peaks | 40% wide | 73% | 26% | 35% | Mostly stable |
| False premise | 0% wide | 100% | 7% | 27% | Stable |
| PDF with a planted error | 0% wide | 100% | 20% | 33% | Stable |
| Unanswerable private data | 0% wide | 100% | 21% | 12% | Stable |

What the table shows. Five cases are Stable, two are Mostly stable and one is Unstable. The unstable one is the 1970s case (60 percent of the same points covered, coverage 43 points wide). Repeated runs of one case overlap on only 7 to 26 percent of source sites, and the numbers in quantitative claims agree on 12 to 38 percent. The same question gives broadly similar answers, but not the same evidence.

### A complete run, and how to inspect it

A run always ends with a result. Step by step it is traced in `runs/<run id>/events.jsonl`, the whole result is in `result.json`, `show <run id>` prints it in the terminal, and `trace.pdf` lays out the plan, the timeline of every step, the claim ledger, the conflicts and the verifier results. Every claim in `report.pdf` has its sources and, where a page could be read, the sentence it rests on.
