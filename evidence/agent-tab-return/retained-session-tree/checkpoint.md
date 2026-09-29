# Session-owned mounted tree checkpoint

PR202 owns the native presentation lifecycle. Each admitted operational session
owns its actual Conversation, Window, editor, transcript and native Textual caches
under unchanged MainScreen ancestry. Workspace admission derives membership from
the existing session registry, recency from TabOrder, and resource limits from
PresentationBudget / PreparationRuntime. Inactive trees exceeding those limits
are evicted through the same owner, retaining the actual editor document/undo
state and operational Agent, rather than another model/goal/transcript store.

Replaced code is deleted: shared Conversation rebind/reset, retained history
keys, shelf, parked-body/page lookup, native reparent/admit transfer consumers.
Schrodinger207 explicitly handed off only History/Page lifecycle deletion hunks;
receipt and source_coverage regions remain his. Existing parked-source fencing
and post-paint native validation still gate committed coverage and publication.
Cold on_mount owns startup once; warm activation cannot schedule another ACP.

## Source native journey

2026-09-29 exit0, real application/ACP/Pi with loopback controlled provider:
`tests/native_loaded_return_cache_pilot.py`, two real prompts per thread, two
loaded histories, five physical returns, then held active-other/return/settlement.
Fixture establishes committed saved publication through the existing checkpoint
owner; navigation no longer performs that remount as a side effect.

Five selection-to-first-paint values (ms): 103.08, 93.80, 97.20, 107.83, 94.43.
Median 97.20 ms. All 15 completed destination frames retained the correct reader
and response, without blank/loading/stale-source frames. Every return reused
the actual outer history, admitted page and visible response body, with zero
prepared misses and zero TranscriptRenderTask submissions. Actual reader y=5,
draft document, undo history, Agent and ACP identity were preserved; no replay.
Held active gamma while beta was selected remained source-correct on return and
settled to idle. Prepared retained bytes 119924; no warm-body eviction in this
two-source cohort. Detail: `source-return.json`.

Native retire 0.19-0.28ms; activation 22.17-34.09ms. Goal read remained
22.43-32.60ms (parent-owned). These are phase durations that may overlap, not
additive CPU attribution. This fixture is smaller than the live 41MB history,
and its committed-history setup changed; it is not a controlled speedup claim
against earlier pairs, a terminal video acceptance, or the final 50ms target.

Syntax, diff whitespace and per-function/per-file StringDispatch/Arms and
TypeSwitch/Arms ratchets passed; the existing Conversation dispatch count stayed
3 subjects / 12 arms. Bounded merge review of integrated204/205 added no dispatch.
Large-history physical scrolling/video/worker profiling and independently loaded
16/32/64 resource acceptance remain open. Exact installed wheel acceptance follows.

## TC1 continuation

README+C0+TC1 from cleanup-2026-09-29.zip assign workspace-state/T9/T4 crossings to
this integration owner. TC1 is not complete. Pre129 (`e46f8cb5^1`) eight-file
aggregate is NoneIdentity4 / ForeignAbsenceProbe11; the current draft remains
above those levels. Required remaining lifecycle, Sidebar placement and tracing
record work is mapped in PR202. T5 coverage/receipt and TC2 ACP taxonomies remain
with their owners. Current usage installation does not wait on those targets.

Scratch owner PR202: `.artifacts/native-retained-layout*` under this persistent
worktree. Failed fresh runs and normal teardown are retained as diagnostic
evidence; no UNKNOWN input was replayed and no global/live-owner mutation occurred.
