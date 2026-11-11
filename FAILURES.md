# Failures and limits

This is the honest list. It comes first because it matters most to anyone deciding whether to trust a report. It starts with what the agent gets wrong or cannot check today and the issues a reviewer found in the demo run, then the failures found while building and what happened to each, then what the evaluation does not cover.

## What the agent gets wrong or cannot check today

| Failure | Cause | Fix, or why it stays |
|---|---|---|
| Many cited pages cannot be opened for checking | Paywalls, bot blocks, PDFs on a machine without poppler, scanned PDFs and PDF pages past the 15th, pages with under 1,500 characters of text, and an 8 second timeout | Those claims still count but start lower and get a lower ceiling, and every run reports its own count. Cited PDFs are now read with poppler's `pdftotext` (first 15 pages) when it is installed, and a headless browser would raise the rate further and was cut for time |
| The official list is a list of web addresses | Any `.edu` page counts as official, and a central bank missing from the list counts as ordinary news. One think tank on an `.edu` name is carved out by hand | It stays, because a fixed list is easy to read and argue with. The fix is to grade the organization behind the page and not its address |
| A paraphrase fails the page match | The check needs about half of a claim's numbers and key terms inside one sentence of the page | That page is dropped as support for the claim. A semantic match would catch it and cost a model call per citation |
| The checker and the writer are one model family | One vendor and one model alias do the search, the extraction and the passage check | It stays. A second family as the checker is the next step |
| A claim taken from your own PDF counts as one official source | There is no web page to compare it with | An eval case plants a wrong figure in a PDF to test this. Until another source disagrees, a wrong figure in the PDF is repeated |
| Conflicts depend on a model reading claim text | One consolidation call decides which claims contradict | It can miss a conflict that differs only in units or definitions, and flag one that is only a difference of scope. It stays until a person or a second model reviews the groups |
| Two runs of one question differ | Live search results change and the model alias moves | It stays. docs/evaluation.md measures how much |
| The budget bounds time and not cost | Tokens depend on what the model writes in that time | It stays. A token cap is the fix and has not been built |

## Issues a reviewer found in the demo run

These four were found by a reviewer reading the demo run's report. Each is marked fixed or not fixed against the code as it stands, and a prompt rule that no re-run has confirmed is not counted as a fix.

| Issue | Cause | Status |
|---|---|---|
| A fed funds peak is labelled with the wrong period. The monthly March 1980 peak sits next to a quarterly average | Figures from two claims about one measure were put in one sentence, so one took the other's period | Not fixed by a check. The writer's prompt now says to quote only a claim's headline value, keep the period label exactly as the claim wrote it, never attach a figure to a period its claim does not state, and never put figures from different claims in one sentence. That is a prompt rule and not a check in code, and no re-run has confirmed it |
| A low confidence Scribd claim is phrased as fact | Scribd was not on the never-counted list, so it counted as an ordinary site, and the writer was not told to soften claims with weak backing | Fixed. scribd.com and other document-upload sites (dokumen.pub, slideshare.net, studocu.com, coursehero.com and similar) are on the never-counted list, so they cannot back a claim. The writer is also told to hedge or leave out a claim under 0.50 confidence or resting on a single Wikipedia, document-upload or blog source, and never to put one in the bottom line. An upload site that is not on the list still counts as an ordinary site. The sample report in `samples/demo_run` was made before this fix, so it still cites a Scribd upload in its bottom line |
| The bottom line says "proved incorrect" over a dispute that is not settled | The writer turned one side of a contested finding into a verdict | Not fixed by a check. The writer's prompt now says the bottom line must state which part is settled and which part is still contested, and forbids "proving" and "both confirm". It is a prompt rule, a word like "proved" is not blocked in code, and no re-run has confirmed it |
| Citations were never opened, 167 of 300, mostly because they are PDFs | When that run was made, the page fetcher read HTML and text only, so a cited PDF came back as non-text | Partly fixed. A later change reads the first pages of a cited PDF with poppler's `pdftotext` when it is installed, and falls back to link-only when it is not. The 167 of 300 figure comes from a run before that change. Claims on pages that cannot be read still count, start lower and get a lower ceiling, and each run reports its own count |

## Failures found while building

| Failure | Cause | Fix, or why it stays |
|---|---|---|
| The passage check failed for whole batches | The model returned a bare JSON list where the code expected an object, and a claim with no verdict was then treated as supported by its passage | Fixed. Either shape is accepted, and a claim with no verdict is marked unchecked, loses confidence, and the run notes it |
| A citation's quote was the model's paraphrase and not the page's words | The quote was taken from the model's own search notes | Fixed. A quote is shown only when it is a verbatim sentence of the fetched page, and otherwise the link stands alone |
| A claim backed by one blog could be called supported | The first scoring only rewarded more independent sites and never required them | Fixed with the source rule in ARCHITECTURE.md, Research quality, |
| Claims from the last round skip the merge and conflict pass when time runs out | Consolidation is itself a model call, and the research deadline had already passed | It stays. Fixing it means reserving time for it, which shortens research, so the run records that it stopped on budget instead |

## What the latest evaluation run showed

These numbers are from `evals/results/latest.md`, 3 runs per case at a 2 minute budget. The causes of the weak spots have not been diagnosed yet.

- Only 100 of 563 citations carry a quote, because a quote is shown only when the page could be opened and a verbatim sentence was found. The other 463 are links with no quote, so the 98 percent citation validity (97 of 99) rests on a small share of the citations.
- Before the quote fix, the same check found none of 156 quotes on the cited pages. Now 95 of 100 are found, and the 5 misses are 2 on the yield curve case, 1 on the false premise case and 2 on the unanswerable case.
- Conflict found is 0 percent on the yield curve, gold and planted-error cases, which all expect one, and no conflict was found in any of their runs.
- The planted-error PDF case still misses the planted 4.9 percent yield error in some runs. It is a measured weakness and not a pass.
- Coverage is 50 percent on the unanswerable-data case, which did abstain in every run, and 67 percent on the false premise and planted-error cases.
- The 1970s case is Unstable across repeated runs, and the gold and 1980 versus 2022 cases are only Mostly stable.
- Repeated runs of one case overlap on only 7 to 26 percent of source sites.
- The two-domains rule for unofficial sources passed 279 of 308 times. Of the 29 misses, 25 are claims resting only on the user's own PDF, where one local file cannot have two domains.

## What the evaluation does not cover

- The rubric is a set of patterns. A right idea in unexpected words is missed, and a keyword in the wrong context counts.
- Citation validity shows that a quote is on the cited page or in its stored snippet. It does not show that the claim is true, and a quote can pass through the stored snippet without being found on the page.
- Pages a site blocks are counted apart and left out of the validity figure, so the figure reads higher than the share of citations anyone could check.
- Cost is an estimate from token counts at Gemini Flash list prices, not a bill, and the `-latest` model alias can move between days.
- Eight cases is a small set, mostly US macro questions in English. It says nothing about equities, other markets or other languages.
- Coverage counts a point when it appears in the answer text, in the agent's claim list or in its uncertainty notes, so an answer can score a point that its readable text never states.
- The citation checker opens whatever address a run recorded, including local files, and does not block private network addresses. That is safe on your own runs and unsafe on a run file from someone else.
- No person grades answer quality.
- Hostile input, such as a web page written to mislead the agent or a PDF carrying hidden instructions, is not part of the scored suite.
- The clarifying-question rule is tested separately in `evals/clarify_cases.py` and does not appear in the results table.
- The confidence score has not been checked against claims a person labelled, so a score of 0.75 is not known to be right 75 percent of the time. It is not meant to be.
- The README check is a substring match over the whole file, hidden text included, so it can pass while a number a reader sees is stale.
- The recorded result files are taken as given. The check proves the page matches them, not that they came from a real run.

The per-case scores are in docs/evaluation.md and in `evals/results/latest.md`.

## Found by code review, not fixed

A code review found these. They are listed here rather than patched.

- Citation markers are placed with a first-match text search, so a sentence that repeats can get the citation meant for its twin. Fix is to place markers by the grounding offsets the search API returns.
- A claim that contains numbers can pass the page check on the numbers alone, even when no key word of the claim appears on the page, because the number match alone clears the threshold. Fix is to require some key word overlap as well, or to refuse an unchecked numeric match.
- When a research worker runs past the time limit, the run moves on but the worker is not stopped. It can keep calling the model and writing trace events, which spends API budget until it finishes. It stays because stopping a call in flight needs a rewrite of how workers are run.
- Ctrl+C in the chat stops the printed output only. The run keeps going in the background and can still save a result. It stays because the chat has no way to cancel a worker thread.
- An official web address whose page could not be opened still counts as support, with a confidence of at most 0.80. A stale or made-up government link can therefore back a claim that nobody read. It stays because many official sites block automated readers, and dropping them would lose true claims.

## Found by the review of the document handling

When a PDF is supplied, the agent keeps up to 24 short passages from it. There are three modes. The default `full` attaches the whole PDF to every research agent. `picked` gives each agent only the passages that fit its own sub-question, chosen by a small model call that picks none when the document is about something else. `start` uses the document only at the beginning. The two notes below are about the passage handling in `picked`, and the first one also applies to the passages used in the plan. Two reviews of this code said it needs attention. Neither was patched further, because the review rounds stopped converging, so both are listed here.

- The passages are written by a model reading the PDF, and they are then placed in the research prompts. They are marked as untrusted data, but that is an instruction to a model and not a hard boundary. A PDF written to carry instructions could still steer the extraction. The break-it test with an injected memo checks that it does not change the answer, and it passes, but that is one case. The fix is to take the passage text straight from the PDF without a model in between, and to check each passage against the file's text.
- In `full` mode a document is simply attached to every agent, so a PDF written to carry instructions can reach every agent directly, and the cost is about 50 percent more tokens for a PDF-backed run.
- The pick call runs once per research agent, with a 40 second limit. With a short budget and a slow service it can eat into the time meant for searching. It is cached per sub-question and skipped when under 40 seconds of research time are left, and a smaller limit or one shared call for all sub-questions would be safer.
- On a test run with an unrelated PDF, 8 of 22 agents were still given passages, so the picker is better than keyword overlap, which gave them to every agent, but it is not exact.

## When something goes wrong during a run

| What goes wrong | What the agent does |
|---|---|
| The API key is missing | Stops before any call, with a message saying where to set it |
| The key is rejected | Stops that call at once with the status code, because retrying cannot help |
| The API is rate limited or fails briefly | Retries up to four times with growing waits, honouring a retry-after header |
| A supplied PDF is missing, too large, encrypted or cut off | A missing file stops the run with a message. The rest are skipped and the report says the answer does not draw on them |
| One search worker fails | Logs a warning and carries on with the others |
| The time budget runs out mid-round | Moves on from unfinished workers without stopping them (see the code review notes above), keeps what it has, and records that it stopped on budget |
| The passage check cannot run for a batch | Marks those claims as unchecked, lowers their confidence, and adds a note to the report |
| The PDF cannot be drawn | The result is already saved, a plain fallback PDF is tried, and `show --rebuild` retries |
