# Toad

## The goal

Responsive scrolling and interaction in the live Toad application: about 16 ms of total UI frame and input work during held PageUp and PageDown, wheel bursts and reversal, active responses, growing history, End, and returning to an open tab. Writer-only timings, passing paths, merged commits and proofs are not this result.

## How to work

- One fact, one owner; derive the rest. Fix the owner and delete the copies in the same change.
- Read the source before editing: trace each fact through its declaration, storage, lifecycle and every consumer.
- When behavior is hard to explain, simplify. Remove states, layers and distinctions; do not add new ones to cover the old ones.
- Prefer deleting code to adding it. If the current design is the problem, say so and propose the replacement.
- Work moved to a thread is still waiting: this CPython build has a GIL, so a CPU-bound thread takes turns with the UI.
- The UI is a view of canonical history. Never keep a second copy of queue, turn, goal or message state in a widget.
- Report plainly: what changed, what evidence supports it, what still fails, the next step. No status ceremony; no hashes unless asked.

## Verification

- No automated tests, fixtures, fake responses or synthetic apps. A hook blocks test edits and test runs.
- Verify in the real application on Tristan's saved sessions with the configured provider. This is standing authorization. Fork sessions for new input; never replay an uncertain input.
- Performance evidence is one table: `docs/performance/scroll-series.md`, one line per change, from `tools/performance/capture_live.py` on the fixed scenario (a fork of the saved session; held PageUp from the input box; wheel bursts with reversal; an active response; End; tab return). Record total frame time and input-to-paint latency, median and p95. No per-change receipts.
- Known environment: unset `NO_COLOR` and `TOAD_VALIDATION`; run real `st` on an isolated display.
- Privileged tooling is limited to read-only `sudo -n py-spy dump/record`. Never use sudo for Python or process-code injection, including an owned frontend. Load the existing live meter at normal-user frontend startup when attribution needs instrumentation.

## Workflow

- Review the plan for scroll-path changes (`widgets/viewport_body.py`, `presentation_window.py`, `prepared_markdown.py`, `streaming_markdown.py`, `transcript_history.py`, `transcript_fragments.py`) or the Textual fork with claude-code. Tristan's approval is not required (Tristan, 2026-10-16).
- One checkout and one branch for this work. No new worktrees, no evidence-only PRs.
- Delete your own generated output when done with it. Never delete raw failures, saved sessions or other agents' work.

## Background

What the previous agent did wrong, with the evidence: `docs/agents/CODEX-POSTMORTEM.md`. Reread it whenever you are about to report progress.


