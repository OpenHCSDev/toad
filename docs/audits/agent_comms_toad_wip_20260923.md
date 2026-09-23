# Toad agent-comms UI: WIP evidence and source-freeze gates (2026-09-23)

**Implementation-bearing draft, not merge acceptance.** This branch is based
on `OpenHCSDev/toad` `main` at `1188944cbc54ae27c0cbdae70ab944eae859d10b`.
The existing docs-only PR was updated with all 190 tracked/untracked
Toad source and test changes from the shared development checkout, preserving
its original audit note. The scope has not been independently reviewed as one
stopped whole, and a clean pinned startup is still outstanding.

This Toad PR is separate from the [agent-comms stages 3–6 evidence draft][core]
and from the Textual performance fork's own PR. `trissim/textual-window` is an
interaction inspiration mentioned in a local menu docstring, **not** a runtime
dependency or a fourth PR. The related performance work is tracked in the
existing [Textual fork draft][textual].

[core]: https://github.com/OpenHCSDev/agent-comms/pull/1
[textual]: https://github.com/OpenHCSDev/textual/pull/1

## Intended UI authority boundary

The proposed Toad workspace would display the core's already-authorized
threads, direct/channel In/out routes, relationships, collaborations, goals,
usage and Recovery. The UI is a projection, not a second resource-claim owner,
read ACK, monitoring daemon, retry engine, or proof of saved-message sender
provenance. Rendering header-looking text is never a typed FROM. Ordinary
cross-root false attribution and stale identity are in scope under the core
trust boundary; same-UID forgery is not this gate. Production publication,
monitoring, automatic retry, and `SILENT` remain **OFF**.

## Historical observations; none approves current code

- A stopped, historical **21-file** right-Comms-sidebar functional manifest
  `/tmp/opencode/right-comms-functional-manifest.md` SHA-256
  `1ac23ac19dcc90f5b9e449edef6becc41f79d144c5a765f639b259192859e7e6`
  received narrow independent CLEAN for its exact typed-route dev bytes; an
  earlier PTY run passed 12/12 workflows. It subsequently drifted with
  user-requested closeable preview tabs, Copy full path and navigation controls.
  The expanded draft requires a new whole-source review. The original specific
  `preview.py` failure still lacks its path/error; bounded Python previews pass.
- A genuine unannotated saved DM rendered FROM+TO in an actual dev widget
  (local log SHA `730861d322f974b18b46c3146a204f8433b01f8c6c63eceb553b7d66af08a907`);
  a header-only negative remained hidden (SHA
  `4929038aacc65a4ee64179c6022dc7bdc9115f1b2ad356d0a02dc5140eebdb1f`).
  The **last independently reviewed** core saved-FROM ops integration
  (`ecef7e82…`/`31083484…`) was **NON-CLEAN**: an ordinary Pi session from root
  B attached to root A can falsely label an identical root A DM as B's saved
  FROM. Later removal/correction is pending stopped-byte review; these two
  positive/negative UI controls do not establish provenance.
- Offline automatic-compaction pilot SHA `8f0944a9…` observed native Pi
  successful mid-turn start/end(summary) swallowed before ACP; manual summary
  control passed. Usage formatting in a test bridge is not a live ACP socket
  feeding actual widgets.

## Current source snapshot and remaining release gates

The source/test snapshot includes **55 tracked changes** (51 modifications,
four deletions) and **135 legitimate untracked Toad source/test files**. The
original `/tmp/opencode/toad-fork` development checkout remains untouched and
dirty; the draft was built in a separate worktree on the existing PR head.
This is publication of work in progress, not a claim of 190 independent clean
reviews or of any particular authorship for shared source hunks.

The mounted right-Comms panel, typed In/out filter, file-preview tabs, visited
Back/Forward navigation, scrollable tabs and the new centered, proportional
thread-attachment spinner have focused disposable UI pilots. The latest real
disposable PTY `tests/e2e_pty.py` passed 12/12 workflows with the latest fake
Pi prompt-ACK/user-start/final-stop control and default-expanded Comms panel.
That run used development Textual/backend code; its cold channel route was
48.2 ms. `tests/async_thread_open_pilot.py` also verifies the large spinner
remains visible and rescales while the owner/history reads are blocked, then
leaves drafts and switching intact after readiness.

`pyproject.toml` and `uv.lock` still pinned agent-comms `aa18e45c…`, which
lacks the experimental transcript/gateway APIs. An injected development
`PYTHONPATH` is not a compatible immutable pinned startup.

Before merge or release, freeze the complete source/test diff, obtain independent
review of shared code and current backend compatibility, then re-run mounted
Main/Comms sidebar navigation, typed In/out and historical-root negative,
renamed/deleted peers, drafts, Recovery gateway, and focused/broad PTY pilots
against that exact snapshot. Use a compatible reviewed immutable
agent-comms revision **in both manifest and lock**, prove clean pinned startup,
and capture live ACP socket → actual widget positive/unknown usage,
compaction lifecycle/summary and abort, routing, and Recovery without Retry or
read ACK. The Toad draft now consumes typed mid-turn compaction metadata;
`tests/midturn_compaction_pilot.py` proves mounted start/end/abort, bounded
summary, unknown usage and fresh positive restoration without a provider.
`tests/compaction_pilot.py` retains idle `/compact` and its full visible summary.
These fixtures do not prove a clean pinned live ACP socket or authorize a
fabricated zero as measured context usage.

The separate strict target is **worst completed semantic frame presented by a
real terminal emulator <16 ms** across busy scrolling, selection, tab/sidebar,
cold channel and Recovery. Historical cold useful-pixel observations roughly
197–366 ms fail; headless paint, `_display`, PTY enqueue and averages cannot
prove this target. A scoped functional review need not claim it passed.

Local `/var/tmp` logs/manifests may not be available on another machine; a
future release must preserve sanitized reproducible tests and stopped hashes.
This implementation-bearing draft has no compatible pinned startup, production
approval, <16 ms frame result, or release authority.
