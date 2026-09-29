# PR169: App session admission and root operation lifetime

## Deleted first

778 App lines deleted,33 added against merged main168 `8b5f410e`. App AST span1510 ->769; god-class excess over500 falls741. Removed App's comms/preview membership maps and reverse indices, preview return map, opening Futures, cached route/service fields, action pending set and opening/action/transfer/sync/close implementations. All actual callers now use the existing semantic owners. No retired API alias, parallel session registry, native-startup retry, format converter or compatibility path remains.

**Published production and gate source:** `3405cf3eaf11e6032edb7b3f5e29e3f15bff3680`. Normal merges preserve main170 Conversation submissions,171/172 DB/render/field ownership and168 operational transcript read/body ownership. New168 transcript-reader caller uses CoordinationAccess; its superseded Agent reader method is deleted.

## One authority per relation

- SessionAdmission is a public DeclaredFamily ABC. NativeSessionAdmission,HistorySessionAdmission andPreviewSessionAdmission own creation, address, tab projection, source relationship, dependent close/return and relevant rebinding. Instances are the callable factories in **existing WorkspaceSessions.factories**, the sole admission membership. Existing SessionTracker holds its native metadata; it is not another roster for preview/history admissions.
- SessionAdmissions consumes those case behaviors. App composes it and retains its existing framework activation/selection machinery. WorkspaceSessions.select/prepare, source body custody and viewport ownership are preserved.
- Existing ThreadNavigation becomes stopped/native/existing declaration-owned outcomes. ThreadNavigator and existing ThreadOpening own one real task per captured intent. Cancellation of one UI waiter does not revoke that shared task. Root/source identity and selected owner are captured once; closed/stale sources cannot manufacture another tab.
- CoordinationAccess owns validated observed route/service access. Actual writes still use the **existing core default-route lock through the synchronous sink**. Existing ThreadActionExecution owns its actual task and captured route; application close awaits accepted effects before source teardown. TransferRequest cases own dialog/apply/completion/menu and derive membership from declarations. Textual workers receive async callables rather than already-created coroutines.
- MainScreen owns source spawning. CommsScreen owns mounted identity/project/recovery rebinding. ConversationKind owns unread projection. No Agent/process/startup authority is relocated into App.

## Actual installed results

Own **noneditable** Toad wheel, read-only paired core `4febe05e386a9cfeb10982472a148baac34a9300`, Textual `1738abd8e3524b7e86171b70256d7f7e52fdb724`, physical Pi package `native-current-d3967e8b6ee0cf28`. Controlled localhost provider only; real normal App, saved native journals, SQLite, ACP and native workers. No live-default mutation/restart, paid calls, transport/render mocks or user-input replay.

1. **PASS EXIT0: actual NEW canonical fork -> physical sidebar open while RPC socket ABSENT -> successful attach -> inherited history paint -> first NEW reply painted exactly once.** Same logical tab,Agent andSessionDetails; title `immediate-fork` without @ placeholder; exactly3 physical provider inputs. The isolated actual child is held after its exec handshake and before socket binding, then resumed once. Socket absence is asserted at observation AND actual ACP session/load write. See [fork.log](fork.log),[fresh-fork.json](fresh-fork.json).
2. **PASS EXIT0: actual modal default publication changes root -> physical export submit refuses stale sink -> error painted -> no output file.** See [route.log](route.log).
3. **PASS EXIT0: actual installed two-owner Back, same-owner reuse/rebinding, closed stale owner refusal and dependent-close isolation.** See [owner.log](owner.log).
4. **PASS affected assertions before the separate warm gate:** two physically saved native histories paint; duplicate typed open with cancelled UI waiter produces one tab; existing native reuse; stopped DM without start; original Document/EditHistory/draft/undo return; single new SessionAdmission declaration paints a real file and closes through generic membership; production preview reuses one file and closes to origin.
5. **FAIL retained warm AgentResponse identity after Beta -> Alpha -> Beta -> stopped DM -> Alpha:**0/1 original response bodies returned, despite correct saved text/editor paint. The strict assertion remains. See [saved-warm-failure.log](saved-warm-failure.log). Parent/Tesla own the current pair's source/body and idle-preparation gate; this receipt does not claim that integration requirement passed or the actual default user's fork trigger resolved.
6. Seven existing affected T3/T4/terminal/admission deletion guards **PASS3.07s**. Production per-file ratchet has **ZERO increases**, including chain terms and foreign absence probes. App chain terms -13,foreign absence probes -10; god-class excess -741. See [ratchet.json](ratchet.json).

### Commands in this worktree

```sh
TOAD_TEST_SOURCE_HEAD=$(git rev-parse HEAD) TMPDIR=$PWD/.artifacts \
AC_NATIVE_COPIED_PACKAGE=/home/ts/.local/share/agent-comms/native-current-d3967e8b6ee0cf28/node_modules/@earendil-works/pi-coding-agent \
L0A_EVIDENCE=$PWD/.artifacts/installed-final-pair-fork \
timeout 120 .venv/bin/python -u tests/first_fork_native_installed_pilot.py

TOAD_TEST_SOURCE_HEAD=$(git rev-parse HEAD) TMPDIR=$PWD/.artifacts \
AC_NATIVE_COPIED_PACKAGE=/home/ts/.local/share/agent-comms/native-current-d3967e8b6ee0cf28/node_modules/@earendil-works/pi-coding-agent \
L0A_EVIDENCE=$PWD/.artifacts/installed-final-pair-saved \
timeout 120 .venv/bin/python -u tests/thread_navigation_installed_journey.py

TMPDIR=$PWD/.artifacts \
AC_NATIVE_COPIED_PACKAGE=/home/ts/.local/share/agent-comms/native-current-d3967e8b6ee0cf28/node_modules/@earendil-works/pi-coding-agent \
timeout 40 .venv/bin/python -u tests/session_route_installed_pilot.py

TMPDIR=$PWD/.artifacts timeout 40 .venv/bin/python -u tests/owner_navigation_pilot.py

.venv/bin/python -m pytest -q tests/guards/test_session_admission.py \
tests/guards/test_t4.py tests/guards/test_t3.py tests/guards/test_terminal_attention.py

.venv/bin/python -m agent_comms.debt_ratchet --root src/toad \
--base 8b5f410e55aba5f9f8a75463751adf908734eb9d --head 3405cf3eaf11e6032edb7b3f5e29e3f15bff3680
```

## Ownership method and limits

Reread current NRA/refactor-audit and its catalog. IMPL-1/4/5: declared outcomes/admissions/transfers own complete behavior, not another central switch. MEMB-1: workspace membership and transfer menu derive from existing owners. IDEN-1: ThreadOrigin andRouteSelection compare captured values instead of field chains. IDEN-3: observation owns optional service state. TIME-9: actual callers/retired implementations deleted, no wrapper over competing old mechanism. AGENT-8: guard covers actual declarations/callers, not only prose. Dominant chain-kind guidance applied; no touched production file increases chain terms or foreign absence probes.

This is a substantial useful original T4 checkpoint, **not full T4/all-plan closure**: App remains769 lines. Global NRA completion and final performance/CI are not asserted. Parent owns whole-source review, paired installation and affected LIVE/default-user gate. Q7 Prompt cursor/slash/first-frame is assigned next; no overlapping App implementation until whole169 review.

## Attempt/resource disposition

The preceding repeated cold test timed out after suspending the pre-exec launcher, blocking the actual fork spawn handshake before physical opening. Confirmed stopped command/registry; retired only its root-attested private test processes. Gate now waits for actual `python -m agent_comms.worker` before suspension, retaining every socket/open/reply assertion. Earlier source14b's cold test also passed; final3405 is the current integrated proof. Packaging setup initially lacked the canonical pi-comms-native console entrypoint; it was supplied from the installed core distribution in the **own test venv**, with no product admission workaround.

Owned scratch `.artifacts`3.1MiB and own installed test environment22MiB at completion; no remaining native workers from these final runs. Earlier failed fixture/native journal/proof files are kept as bounded diagnostic artifacts. No other agent's tree, original history or live store was changed.
