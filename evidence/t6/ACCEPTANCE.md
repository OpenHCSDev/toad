# T6 acceptance and practical limits

Production code: e71cd02, PR123. Installed Python3.14.2 wheel in this tree's `.venv`, core78adae (including268), Textual16ede/native dependency installation read only. No editable install or source overrides. Private fresh roots only; no model calls, live writes, history conversions or CI wait.

## Scope

The full original T6 owner/caller/deletion batch is implemented, including early shared ConversationKind, task reuse policy, command codec/execution, reply progression, declared backend setting, category capabilities, typed delivery and TL0 crossing. [OWNER-CALLERS.md](OWNER-CALLERS.md) maps every retired mechanism to its current callers. T5 confirmed adoption and received later contracts; T2 received typed presentation contracts. Toad117 ViewportPresentation and the core268 shared per-class ratchet are incorporated. Parent owns final integration/live install and native cold compaction.

## Verification

| Receipt | Result | Boundary |
| --- | --- | --- |
| final-guards.txt | 6 passed | shared collector/retirement/families/new conversation family |
| final-families.txt | 5 passed | installed declaration families, settings and renderer selection |
| final-installed-first-attempt.txt | 8 passed, 2 failed | persistent IPC/UI; paint proofs/DM rebind; categories/activity; bounded preparation/body restoration. Two failures below are corrected, not called green |
| final-installed-corrected.txt | 2 passed | actual CLI PTY: local and saved persistent, clean exit/no traceback; mounted routed/unrouted dividers |
| final-scope.txt | 10 passed | current typed-category/routed filter/navigation/history callers and permanent guards |
| final-family-binary-ids.txt | 4 tests passed | current binary IDs/derived command-reply records; inherited category behavior; real process service admission/retention/isolation/new task |
| final-terminal.txt | 1 passed | final installed CLI terminal with relocated choice declarations, local and saved persistent |
| final-codec-path.txt | 3 passed | final current binary codec over actual persistent IPC; mounted Markdown/diff/file preview/Read; retirement guard |
| final-ratchet.json | exit0 | existing-class deltas never positive. TypeIdentity0, LongBooleanChain-1, StringSubscript-2; new owners get null baseline |
| final-ui.txt | passed | two actual mounted Toad instances share one real renderer; Markdown/diff/file preview/Read |

Each collected script imports the installed wheel and owns detached test process cleanup. Family reaction tests use a fake client only for isolated reaction contracts; readiness additionally uses real installed clients/server/processes and UI/terminal frames. No broad/full-suite-green, native model or live cold-compaction claim is made by T6.

## Performance

Baseline is exported fork main df0a758 installed in a separate venv, with the same pinned core/Textual/other dependencies as the candidate. Runs are serial, not concurrent with other T6 pilots. `renderer_benchmark.py` is the retained actual RPC recipe; three paired rounds each send21 warm patch requests and verify result parity.

| Existing boundary / extra measurement | Baseline | Candidate |
| --- | --- | --- |
| Local process pilot, five cases | 1.065s | 1.033s |
| Local worker CPU heartbeat maximum | 11ms | 11ms |
| Prepared 10K-row height median | 0.013ms | 0.010ms |
| Real persistent reconnect + patch pilot | 134.58ms | 133.87ms |
| Extra cold RPC median of3 rounds | 2134.45ms | 2076.86ms |
| Extra warm RPC median of3 rounds | 32.43ms | 32.89ms |
| Extra warm RPC p95 median of3 rounds | 55.32ms | 52.39ms |

The existing pilot timings are preserved or improved after fixing a real worker import regression (4.121s) by moving UI-only renderer choices into render_choices. No arbitrary cap, timer change or alternate protocol was added. The extra RPC benchmark records a0.46ms/1.4% increase in median warm latency and variable heartbeat gaps on the shared machine; tail latency improves. This is not evidence of identical latency or a guarantee against slower workloads. All raw samples/ranges are retained in performance-summary.json and paired receipts; parent can include them in original acceptance audit without retesting unchanged work.

## Failures retained and corrected

- Actual RPC caught a stale `submission.admitted` reference after its carrier was retired. Fixed acknowledgement ownership; rejection remains distinct and does not ACK an unadmitted request.
- The installed CLI fixture exceeded Unix-domain socket pathname limits under nested roots. It now owns a short disposable /var/tmp runtime root; both actual CLI backends pass.
- One divider fixture still supplied retired AgentResponse.route. Migrated to the current typed delivery boundary; guard prohibits old production keyword.
- Worker import timing traced the slowdown to UI theme/choice imports. Common worker backend no longer imports those modules; before/after import logs and the regression receipt remain.
- The old private bus-byte replacement test bypassed the log owner's current storage/proof boundary and was deleted. Actual history/page/paint tests remain. Early wrong-selector/old-codec/fixture failures are retained as diagnostic failures, not passing evidence.

## Deletion accounting and cleanup

Against the incorporated117 base: production source1048 lines added,624 deleted; tests615 added,268 deleted. Net additions represent declaration-owned behavior/typed progression plus real installed terminal/IPC/family/retirement tests, not aliases or duplicate implementations. Class size remains individually bounded by the shared ratchet.

Only owned disposable roots/exports/build helper scripts and temporary terminal captures are removed after retaining diagnostics. Candidate venv and branch remain for integration. Cleanup receipt records actual paths and absence of owned live test children.
