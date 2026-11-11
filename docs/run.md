# Run it yourself

This file explains how to run the agent with a Gemini API key, what each command does and where the output goes.

## Start the chat

From a fresh terminal, this gets you to the chat in four lines. The numbered steps below explain each one.

```bash
git clone https://github.com/jameswniu/fact-verified-llm-research-agents.git && cd fact-verified-llm-research-agents
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
export GEMINI_API_KEY="<your key>"
./research-agent
```

## Step by step

Everything below runs from a plain terminal. No AI tooling is needed.

1. You need macOS or Linux, Python 3.11 or newer, and git. Poppler (`brew install poppler` on a Mac) is optional. With it the agent reads the first pages of PDFs it finds on the web, and without it those sources stay link-only.

2. Get the code and make a virtual environment.

```bash
git clone https://github.com/jameswniu/fact-verified-llm-research-agents.git
cd fact-verified-llm-research-agents
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` has two packages. `reportlab` draws the PDFs and `pypdf` lets the eval scorer read PDFs it checks quotes against. Everything that touches the network uses the Python standard library.

3. Set the Gemini key. This project uses the Gemini Developer API with an API key only. It does not use Vertex AI. A key comes from Google AI Studio at https://aistudio.google.com/apikey.

```bash
export GEMINI_API_KEY="<your key>"
```

Or put `GEMINI_API_KEY=<your key>` in a local `.env` file in the repo root. `.env` is gitignored, so the key never enters the repo. A key already in your environment wins over the file.

4. Ask a question. There are two ways in, and both run the same agent.

**The chat app.** This is the main way to use it. Start it with one command and type your question at the prompt.

```bash
./research-agent
```

You type a question at `you>` and the chat answers in plain sentences while it works.

- On a Mac a second Terminal window opens beside the chat and follows the run's event log live. The chat window shows what the agent is deciding. The second window shows every model call, page fetch and heartbeat behind it.
- To give it a document, drag a PDF into the prompt or type its path along with your question. It reads the file as context.
- When a run finishes, the full paths of the report and the trace are printed as clickable links, and both PDFs open in whatever app your computer uses for PDFs.
- Inside the chat, `/open` opens the last report, `/show` prints the last answer, `/logs` prints the latest events, `/budget <mins>` changes the time budget, and `/quit` leaves. Ctrl+C cancels a run without leaving the chat.
- `RESEARCH_NO_LOGS_WINDOW=1` turns off the second window and `RESEARCH_NO_OPEN=1` stops the PDFs from opening on their own. The command line below does the same two things.

**The command line.** The same agent can be called directly, which is the entry point for scripts and the eval suite.

```text
.venv/bin/python -m research run "In the 1970s a lot of economists said monetary policy wasn't working anymore and we needed fiscal policy instead. Was that actually right?" --budget-mins 3
```

This line needs your real key and spends a few cents of API budget. The `.venv/bin/` prefix means it works without activating the virtual environment. If the environment is active in your shell you can write `python -m research` instead, which is how the rest of this page spells it. The default when you leave `--budget-mins` out is 10. A short budget finishes early, because research stops once less than 45 seconds of research time are left. With 2 minutes a run usually ends after about a minute and one round of searching, and a 3 minute budget is enough to see a follow-up round.

Add `--pdf path/to/paper.pdf` to give it a document to work from, and repeat the flag for more than one. `--budget-mins` is the time you are willing to spend and the default is 10. Research uses the first 65 percent of it and the rest goes to checking and writing, so the run ends at or under the number you give, and sooner when it runs out of new evidence.

Whichever way you start it, the agent prints a narrated line for each step, starting with the time since the run began, so you can watch it plan, search, find a disagreement and check its claims. This is a shortened excerpt from a development run.

```text
[0:00] Starting research (6.0 minute budget): In the 1970s a lot of economists said monetary policy wasn't working anymore ...
[0:02] Assuming the historical macroeconomic debate surrounding stagflation in advanced economies ...
[0:09] Planner: 6 sub-questions across 5 lenses (it skips a lens that does not fit)
[0:09] Agent q1 started: Pulling the hard numbers and their primary sources
[0:24] Agent q3 finished: 8 claims from 10 sources
[0:50] Opened 22 of 48 cited pages to check them
[0:56] The ledger holds 53 claims: 0 open conflicts, 3 new leads, 3 gaps
[1:30] Found 4 claims that conflict: ...
[2:38] Stopping: reached the limit on follow-up rounds
[2:38] Checking every claim against its sources
```

Progress goes to stderr and the final summary to stdout. `--quiet` hides the progress lines. The same lines are always written, with more detail, to `runs/<run id>/events.jsonl`, one JSON object per line. A run id looks like `20261009-143408-dc3b`, so the file is `runs/20261009-143408-dc3b/events.jsonl`. `./research-agent` opens a window that follows it for you. To follow a run by hand from any terminal, use the command below, or `python -m research logs latest --follow` for a readable version.

```text
tail -f "$(ls -td runs/*/ | head -1)events.jsonl"
```

Each line has `ts` (clock time), `t` (seconds since the run began), `type` (start, clarify, pdf, plan, search, claims, fetch, consolidate, conflict, round, verify, synthesize, warning, stop or done), `msg` (the sentence you saw on the console), and extra fields that depend on the type, such as the search queries an agent used.

Before it plans, the agent may ask you one clarifying question. It does so only when the question could mean two different things and it is not sure which you meant. You get 20 seconds to answer, and silence means it goes with its own pick and states the assumption. `--no-clarify` turns this off, and it never asks when input is piped.

When the run finishes it prints a summary. The numbers here are from an early development run and only show the shape.

```text
Run 20261009-143152-ebdf finished (3m 14s, 67,637 tokens)
  117 claims: 112 supported, 0 contested, 5 unsupported; 0 open conflicts; 98 sources
  Report: /home/you/fact-verified-llm-research-agents/runs/20261009-143152-ebdf/report.pdf
  Trace:  /home/you/fact-verified-llm-research-agents/runs/20261009-143152-ebdf/trace.pdf
  Details: python -m research show 20261009-143152-ebdf
```

5. Look at the result. Open `report.pdf` for the answer and `trace.pdf` for how the run got there. Both are in `runs/<run id>/` next to `events.jsonl` and `result.json`. The command line can also read a saved run back.

```bash
.venv/bin/python -m research show
```

That lists the ten most recent runs. Two more forms, which need a real run id from that list.

```text
python -m research show 20261009-1431             # one run, any unique prefix of the id works
python -m research show 20261009-1431 --rebuild   # redraw both PDFs from the saved run
```

6. Run the tests and the evaluation suite.

```bash
.venv/bin/python -m unittest discover -s tests -t .
.venv/bin/python -m research eval run --fake --repeats 1
```

The first line runs the offline unit tests and needs no key. The second is a smoke test of the evaluation harness with a fake agent. The real suite calls the API for 24 runs, takes roughly 15 to 20 minutes and costs under a dollar, so it is shown here and not run by the checks on this page.

```text
python -m research eval run          # the real suite, uses the API
python -m unittest discover -s tests -t .  # also runs the break-it tests against the real command line when a key is set
```

The real suite runs 8 cases 3 times each, six runs at a time, each capped at 3 minutes by default, so give it 15 to 20 minutes. The result tables below were made with `--budget-mins 2`. It writes `evals/results/latest.md` and a time-stamped folder next to it with the per-run details. A key with a low rate limit will see retries, and `--workers 2` eases that.

You should end up with a PDF report in which every claim is linked to a source, a trace of how it was produced, and a scores table from the eval run. The `samples/demo_run/` folder holds the two PDFs of a real run, and `samples/fake_run.py` writes a made-up result through the same report code, so you can see the layout without a key. That one is stamped as synthetic.
