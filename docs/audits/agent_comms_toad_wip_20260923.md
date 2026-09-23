# Toad agent-comms UI: WIP evidence and source-freeze gates (2026-09-23)

**Document-only WIP, not an implemented feature PR.** This draft branch is based
on `OpenHCSDev/toad` `main` at
`1188944cbc54ae27c0cbdae70ab944eae859d10b`. It contains this **one new
file only**. None of the 179 dirty UI/source/test paths in the developer's
separate `/tmp/opencode/toad-fork` worktree is in this branch. Do not merge,
mark ready, deploy, or mistake the historical development results below for
source included in this PR.

This Toad PR is separate from the [agent-comms stages 3–6 evidence draft][core]
and from the Textual performance fork's own PR. `trissim/textual-window` is an
interaction inspiration mentioned in a local menu docstring, **not** a runtime
dependency or a fourth PR. At this document's preparation there was no Toad
fork PR to link; add a real Textual PR URL after that separate PR exists.

[core]: https://github.com/OpenHCSDev/agent-comms/pull/1

## Intended UI authority boundary

The proposed Toad workspace would display the core's already-authorized
threads, direct/channel In/out routes, relationships, collaborations, goals,
usage and Recovery. The UI is a projection, not a second resource-claim owner,
read ACK, monitoring daemon, retry engine, or proof of saved-message sender
provenance. Rendering header-looking text is never a typed FROM. Ordinary
cross-root false attribution and stale identity are in scope under the core
trust boundary; same-UID forgery is not this gate. Production publication,
monitoring, automatic retry, and `SILENT` remain **OFF**.

## Historical observations; none approves this PR's absent code

- A stopped, historical **21-file** sidebar/Recovery functional manifest
  `/tmp/opencode/right-comms-functional-manifest.md` SHA-256
  `1ac23ac19dcc90f5b9e449edef6becc41f79d144c5a765f639b259192859e7e6`
  received narrow independent CLEAN for its exact typed-route dev bytes; an
  earlier PTY run passed 12/12 workflows. It subsequently drifted with
  user-requested closeable preview tabs and Copy full path. The current preview
  failure and changed 21-file subset still need a new stopped manifest/review.
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

## Current fork inventory and blocked source PR

At 18:48 UTC, `/tmp/opencode/toad-fork` resolved to
`/home/ts/.agent-comms/.test-tmp/toad-worktree`, dirty `main` at the same
`1188944…` base with **179** status entries (51 modified, four deleted,
124 untracked). This is **not** an attributable source manifest: sidebar and
maintenance owners share screens; no moving files were copied into this PR.
`pyproject.toml` and `uv.lock` still pinned agent-comms `aa18e45c…`, which
lacks the experimental transcript/gateway APIs. An injected development
`PYTHONPATH` is not a compatible immutable pinned startup.

Before a separate curated source commit may join this draft (or a new code PR),
stop every relevant UI writer, obtain a complete owned SHA-256 source/test
manifest with exclusive owner handoff, compare exact bytes before/after review,
and stage **only** the reviewed attributable subset in an isolated branch.
Do not stage the dirty 179 paths wholesale. Resolve preview tabs/Copy-path
failure without silently reverting another owner's work; re-run mounted
Main/Comms sidebar navigation, typed In/out and historical-root negative,
renamed/deleted peers, drafts, Recovery gateway, and focused/broad PTY pilots
against that exact manifest. Then use a compatible reviewed immutable
agent-comms revision **in both manifest and lock**, prove clean pinned startup,
and capture live ACP socket → actual widget positive/unknown usage,
compaction lifecycle/summary and abort, routing, and Recovery without Retry or
read ACK.

The separate strict target is **worst completed semantic frame presented by a
real terminal emulator <16 ms** across busy scrolling, selection, tab/sidebar,
cold channel and Recovery. Historical cold useful-pixel observations roughly
197–366 ms fail; headless paint, `_display`, PTY enqueue and averages cannot
prove this target. A scoped functional review need not claim it passed.

Local `/var/tmp` logs/manifests may not be available on another machine; a
future source PR must preserve sanitized reproducible tests and stopped hashes.
This docs-only draft has **no passing implementation test**, compatible pinned
startup, production approval, or release authority.
