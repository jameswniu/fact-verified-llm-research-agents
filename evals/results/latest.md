Eval run 2026-10-09 14:56, 3 runs per case, budget 2 min per run, cited pages fetched live.

### Quality

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

### Latency and output files

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

### Source and quote rules (passes out of items checked)

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

### Reliability across repeated runs

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

### Clarifying-question rules (pass or fail)

| Rule | Runs passed | What it checks | First failure |
|---|---|---|---|
| Clarify: clear question, no ask | 3/3 | A clear question is never answered with a question. | None |
| Clarify: ambiguous question asks once | 3/3 | Two doubtful readings get exactly one one-line question with two options. | None |
| Clarify: never asks twice | 3/3 | After the user answers, even vaguely, the system does not ask again. | None |
| Clarify: non-interactive run proceeds | 3/3 | With no one to ask, the run goes on with the default and records the assumption. | None |
| Clarify: empty or slow answer | 3/3 | An empty answer, None, an error or silence takes the default and does not hang. | None |
| Clarify: mild ambiguity assumes | 3/3 | When one reading is the obvious one, assume it, say so and invite a correction. | None |

Coverage is the share of rubric points the answer states. Citation validity is valid citations over (valid + invalid + supported claims with no citation), where valid means the quote appears on the cited page or its stored snippet. Latency is question received to report.pdf written. The trace column is when trace.pdf was written. A page that could not be read counts as not passing the quote rule. Cost is estimated from token counts at Gemini Flash list prices.
