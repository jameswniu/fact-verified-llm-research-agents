# Roadmap

This file lists work that is not built yet.

Not built yet. Written down so the path is clear.

## Follow-up prompts that steer a run

Today a run is one question in, one report out. The next step is a conversation. The user reads the report, types "now focus on the UK", or "ignore the oil shock angle", and the agent revises instead of starting over.

How it fits the current design
- Every run is already saved, with its claims, sources, conflicts and the agent graph (the run store and event log). A follow-up loads that saved run.
- The follow-up text goes through the same planner. It becomes new sub-questions, or a filter that marks some existing branches as out of scope.
- The research loop runs again on only the new or changed branches. The claim ledger and the verifier are reused as they are, so old claims keep their sources.
- The report writer produces version 2 of the report and notes what changed since version 1.

What would be added
- A `research follow-up <run_id> "<text>"` command, and a version number on each report.
- A small step that classifies the follow-up as narrow (add a branch), re-scope (drop branches) or restart.
- A "superseded" status on claims, so a drop is visible rather than silent.
- Eval cases for it, such as "a follow-up must not discard verified claims that are still in scope".

Steering a run while it is still generating is a harder second step. It needs interruptible agents and a lock on the claim ledger. The saved-run approach above covers most of the value without that risk.
