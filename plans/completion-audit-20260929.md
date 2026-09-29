# Requirement completion map, 2026-09-29

Dalton. Read-only product audit; this document is the only authored file.
It does not replace Boyle's `plans/remaining-plan-closure-20260929.md`.

## Source authority and exact snapshots

- Core main **11dcae2769d5f02e94b58b5a9bb6ae865e55db3d**, including359/361/362/363.
  Original census was d7745d0e; current363 removes the supplement boundary and
  reduces SelectedExecution814→804. Later open candidates are not treated as main.
- Toad main **5059d4aa23a085bbeada04957fb9dfe9cb220bd8**, including160/163/166/167. Open169/170/168 are distinct current scopes, not closure of all T4.
  The initial75eb snapshot advanced during this audit;167 is now merged, not pending.
- Original archive: `/home/ts/.agent-comms/plans/nominal_refactor/files.zip`:
  `00-index.md`, `01-shared-abstractions.md`, C0 and S1–S8.
- Round2 archive: `/home/ts/.agent-comms/plans/refactor2/agent-comms-refactor-round2.zip`:
  rules/index/shared/coordination, L0, R0/R1, S9/S10/S12/S13. The unpacked
  `plans/refactor2/L0-legacy-sweep.md` was also read.
- Toad archive: `/home/ts/.agent-comms/plans/toad-comms_refactor/toad-refactor.zip`:
  rules/index, TR0/TL0/T1–T8. Later authoritative loose files in that same shared
  directory: **S14-long-conditions.md and T9-long-conditions.md**. They remain
  obligations even though absent from the old package indices.
- Original dispatch override: `plans/nominal_refactor/README.md` and
  `/home/ts/wt/comms-refactor-dispatch-20260927/FINAL-ORIGINAL-PLAN-AUDIT.md`,
  `plans/POST-PR95-DECISION.md`, and the authoritative current override at the
  beginning of that worktree's `plans/00-index.md`. Its C0/current-components and
  universal-size qualifications are binding; its old runtime/PR prose is historical.
- Latest exact `/home/ts/code/projects/nominal-refactor-advisor/skills/refactor-audit.skill`
  SKILL, pattern README, principles13/14 and receipt guidance were reread, alongside
  NRA/global AGENTS. Pattern IDs below use that authority. No old2216 copy assumed.

Method: fetch/read Git objects, inspect selected current source and callers with
`git grep`, parse the named current files with Python AST, read retained receipts,
and query PR/issue state. **No NRA/global debt scan, test matrix, provider call,
new runtime, live-state inspection/mutation or competing implementation.**
AST observations are source witnesses, not detector certification or executed tests.
Prior receipts below are identified as prior executed evidence; they were not rerun.

## Reading the status and evidence columns

**I**: implementation/current caller present, with named scoped acceptance evidence.
**D**: named obsolete mechanism/callers deleted. Neither means universal correctness.
**O**: concrete remaining implementation. **U**: explicit acceptance not proved by
the available evidence; not automatically a new product task. **S**: superseded by
binding newer rules/owner directions. **M**: merged; current paired live acceptance
is a separate parent responsibility. Every row names an owner or honestly says
**unassigned; parent dispatch**. A historical author is not assumed actively working.

`C:` paths are in the pinned core tree; `T:` paths are in the pinned Toad tree.
The following receipt abbreviations keep the tables readable:

| Receipt | Acceptance source and strength |
| --- | --- |
| CE | C:evidence/current-global-coverage/{README,REQUIREMENTS}.md,315. Earlier694-file exact compact global run:81 requested/analyzed detectors,0 omitted,139 raw leads. Not a current-head scan or zero-debt verdict. |
| OS | C:evidence/original-s1-s4-acceptance/README.md,290/298. Retired SelectedSource fixtures removed/current helpers used; combined installed acceptance. |
| E1 | C:evidence/s1-event-settlement-behavior/README.md,305. Current event/error effects, ordinary/manual/relay settlement; actual local native success/503/manual commit. OPEN2 deliberate standby policy delta documented. |
| E2 | C:evidence/backend-response-lifecycle/HANDOFF.md and evidence/turn-failure-native-acceptance/RESULTS.md,303/320. Actual native scenarios plus public failure fact/no replay; not every historic trace combination. |
| E3 | C:evidence/s3-legality-behavior/README.md,300.47 original predicates/couplings mapped to executed current family/SQLite behavior;111 installed checks. |
| E4 | C:evidence/s4-read-characterization/README.md and evidence/s4-mounted-read-ack/README.md,307. Randomized/actual crash/rebind controls plus four installed channel/DM/native-paint/read-ACK paths. |
| E7 | C:evidence/s7-contention/{RESULTS,HISTORICAL}.md,285, and evidence/registry-marker-contention/s7-fixed.log,289/304. Actual50/100/150,three pollers,current/pre-A8 p50/p99 and lock measurements; marker-race repair. Do not rerun unchanged. |
| NJ | C:evidence/native-proof-journal-closure/README.md,283, plus current native evidence/streaming tests. Durable context proof decode/reopen; not issue107's entire bounded recovery specification. |
| NC | C:evidence/native-reusable-lifecycle/HANDOFF.md,325; evidence/native-custody-terminal/README.md,362; tests/test_backend_native_lifecycle.py. Real child reuse/retire/selected/manual/reopen paths. |
| MC | C:evidence/typed-compaction-results/RESULTS.md,319 correction/322; tests/test_backend_native_lifecycle.py retained-child case strengthened324. Actual RuntimeServer/attached ACP compact route, not just direct compact_context. |
| FT | C:evidence/native-fork-first-input/RESULTS.md and evidence/native-token-deployment/actual-installed-native-complete.txt,338. Real ordinary63%/fork24% selected context, actual first answers,0 compaction, no replay, parent preserved. |
| NR | C:evidence/native-channel-reply-roundtrip/RESULTS.md,330, and evidence/keyed-response-delivery/README.md,331. Actual two-native-owner A→B→A, automatic author observation, feedback, strict full/certified receipt rejection. |
| REG | C:evidence/s14-registration/README.md,357, and evidence/s14-registry-lifecycle/README.md,361. Actual installed saved histories/reply/restart/fresh one-input journey, current transition callers/deletions. |
| AW | C:evidence/selected-awareness-lifetime/HANDOFF.md,363.181 production lines deleted; typed OptionalAwarenessResult/Projection replace supplement/builder/JSON/revalidation. Actual pinned native installed case1pass3.23s, source-cited passive awareness/tools/reply/proof/cursor/lease preserved. Not automatic wake authority or current LIVE attestation. |
| TI | T:evidence/integration/{ACCEPTANCE.md,t2-guards-final.txt},125; T:evidence/t1,t3-sol,t5-goal,t6,t7,t8 HANDOFFs. Scoped paired owner/caller proofs; their old future-install prose does not override merged PR state. |
| UI | T:evidence/saved-state-user-journey/BODY-REUSE.md and continuous-rendered-body-8207.log,163. Complete physical saved/channel/participant/A-B-A/fork/first-answer/reply/status journey on82070170/core1dbb/Textual1738/native d396. Visible Markdown leaves13/17/13, exact paint/editor/scroll/undo; fast lookahead1→3/reverse/End; idle pending0. Earlier RED preserved. |
| CFG | T:evidence/agent-configuration/HANDOFF.md and native-final-acp.log.gz and native-final/configuration.svg,167. Actual saved native/model/thinking picker/reconnect/paint/draft/undo, one provider input. |
| ATT | T:evidence/terminal-attention/README.md and journey.json/terminal-titles.json,166. Actual native/ACP/App/LinuxDriver PTY/private D-Bus/Ask/permission/lifetime behavior. |
| FIL | T:evidence/transcript-filter/README.md and census.json/installed-versions.json,162. Actual saved native checkbox/older-answer/empty/cancel/offset/resize/tab/editor/no replay. |
| WEB | T:evidence/browser-serving/README.md,50. Actual authenticated loopback Chromium, physical keyboard/rendering, installed ACP initialize/new; not a model turn or general external publication. |

## Concrete remaining work queue

These are work assignments or acceptance qualifications, **not percentages**.
Nothing here holds a useful checkpoint for CI/final latency.

| ID | Remaining requirement, exact witness | Current owner / next concrete action |
| --- | --- | --- |
| Q1 | T9/T4 native publication/source snapshot decisions: T:transcript_publication.py:102 has9 operands; T:widgets/transcript_history.py:811 has8. Snapshot/lifetime checks must move to the existing owners (IDEN-1/3, IMPL-10), not one rule per boolean. | **Tesla168**, existing source-activation/read continuation; coordinate these actual source callers within that scope. No second cache or test framework. |
| Q2 | T4/T9 App opening chains at T:app.py:764/1089; app._finish_open_thread_session112 lines. | **Noether169**, active ThreadOpening/ThreadNavigator and typed routes claim. Preserve current native startup/origin admission and continuous saved/open/return evidence; do not duplicate. |
| Q3 | Core S14 ready-goal admission (C:turn_runner.py:564,10 operands) and queued post-turn drain (:720,8). Existing incarnation/admission/goal/queued-input authorities should answer the predicates. | **Boyle365, actively implementing** GoalScheduler/QueuedInput and READY recovery. Draft native/installed acceptance remains pending;361 did not close these sites. |
| Q4 | Core S14 C:pi_events.py:344,7 and:372,6: live receipt/UI request admission recombines TurnSession fields. | **Wegener next queued scope**, requested after363: PiEvent/TurnSession admission.359/362 custody are merged; no final readiness/merged closure for Q4 yet. |
| Q5 | Core S14 C:active_route.py:154,11 operands, plus hand key/type/root/package decoding. The coordinated supplement half is **deleted by merged363**; current SelectedExecution has no6+ BoolOp in this bounded read. | **Parent route queue**, separate from completed Wegener363. BOUND-1/IDEN-1/IMPL-14 after dominant-kind review; preserve route authority and corruption refusals. |
| Q6 | **Two live FieldCodec subclasses** remain: T:db.py:29 SessionCodec; T:render_protocol.py:21 RenderCodec. SessionTimestampStorage/SessionMetaStorage use the first; render_zmq.py:105/111/119/122 uses the second. Latest TIME-9 explicitly forbids codec forks. | **Parent actively taking paired A2 + T8/T6 full caller deletion**, including a guard across both repositories. Existing core-only ownership guard did not close Toad. Preserve durable sessions and renderer private captured-object contract; no aliases or parallel codec. |
| Q7 | T9 T:widgets/prompt.py:476,6 cursor/slash-entry predicates; separately T:app.py:661,6 first-frame admission predicates. | **Prompt: Noether next queue**, outside169 current scope. **App first-frame site: Noether domain, closure not yet claimed in169**; parent scope confirmation. Do not label either merged. |
| Q8 | Original universal size limits remain unmet: **12 core/6 Toad >500 owners**, enumerated with actual responsibilities below. SelectedExecution804 at current363; original module≤1000/method≤100 also have explicit counterexamples. | **Existing domains Wegener Selected, Boyle TurnRunner, Carver Conversation170, Noether App169, Tesla History168; rest explicitly unassigned below.** Correct behavior/caller deletion required; current excess ratchet is a growth guard, not absolute-cap completion. No cosmetic carve/mixins. |
| Q9 | PR116/110 final matched loaded+blank4/16/32/64 input/frame/GC/return tails, canonical raw-page revision reuse and30–40ms/<50ms user target remain unproved. Recent168 wall returns411–458ms and incidental render miss are not target success. | **Tesla168**. Current warm physical behavior UI is proved; canonical revision/read reuse remains actual work. Parent owns paired affected LIVE proof; final target does not stop useful tranches. |
| Q10 | Current whole-context clean detector result, every historical surface RuleR/edit-count receipt, exhaustive reachable S2 protocol/failure combinations, all three process platforms are not established by scoped receipts. | **Evidence qualifications**, parent triage; existing NRA owner for detector reporting, Wegener for native behavior, no universal PASS. Only assign a new code/test slice if a meaningful current requirement is actually uncovered. No unchanged global scan/matrix here. |
| Q11 | Native proof recovery issue107 is OPEN.283 typed decoding and284 bounded framing do not by themselves prove crash-atomic checkpoint/segment recovery cost independent of lifetime, all publication interruptions, UNKNOWN preservation, increasing-history memory/timing. | **Wegener queued after Q4**, per parent assignment. Reconcile actual native source against107 before claiming done; no raised constant or deletion of retained proof. |
| Q12 | Canonical raw-page identity/reuse and target-thread presentation for168. Current attach otherwise re-reads canonical pages and whole thread-view projections. | **Tesla paired core366/Toad168 active** for transcript identity/reuse; **parent separately owns target-thread projection**. Exact consumer API/actual physical native zero repeated-read evidence pending; no parallel cache. |
| Q13 | Additional S14 witnesses in the bounded large-owner read: C:wire_log.py:361,8 compared publication fields; C:thread_management.py:251,9 compared imported thread fields; C:compaction_journal.py:505/841,6 each enrollment/publication conditions. | **No active full-file closure claim found; parent dispatch**. Identity/snapshot and owned admission/state (IDEN-1/3/IMPL-10) must preserve strict receipt/lineage/UNKNOWN rules. Trace exact dominant semantics before extraction; do not turn each comparison into a rule. |

## Absolute limits and residual behavior ownership

**C0 boundary/caller deletion is complete; residual god-owner closure is not.**
Source: original C0 size acceptance6 and S7 migration9/acceptance4, original S2
method/nesting guard, T4 component ownership/done criteria, latest principle13.
These are different obligations:

| Explicit requirement | Current result | Remaining disposition |
| --- | --- | --- |
| C0 every module≤1000 except temporary bus/registry; S7 ultimately every module≤1000 | **O**. Current coordinated_runtime1005 and child_process1350 are direct counterexamples; no whole-repository size PASS. | Parent scopes correct behavior owners. Temporary C0 exemptions do not close S7, and D20 forbids using another carve to meet it. |
| S7 every method≤100; S2 new methods≤100 and nesting≤5 | **O/U**. Current _settle_fenced_response141, Toad opening112/publication119 are source witnesses; universal method/nesting compliance not established. | Boyle/Noether/Tesla owning the relevant behavior, plus parent unassigned residual scopes. No duplicated helper just to cut method text. |
| Latest class threshold500/no new crossing/no existing god owner growth | **Growth guard present, absolute owner closure O**.12 core/6 Toad owners remain beyond500; no new current measurement claims they are small. | Shared excess measure protects edits; existing excess needs substantive responsibility/caller deletion. It does not count a file/mixin shuffle as closure. |
| T4 every known responsibility component-owned; residual size justified and guards pass | **I/O**.167 configuration and166 attention are actual closures, but remaining source roles below still coexist. | Each current owner must publish the complete behavior/caller migration, deletion and affected path evidence, or a concrete retained responsibility justification. Not a blanket T4 completion. |

The supplied parent installed census is
`/home/ts/wt/comms-acp-saved-session-startup-20260928/evidence/configuration-lifecycle-deployment/remaining-large-owners.json`
at d774/5059. Cheap AST re-read of those named core files at11d confirms all12
still exceed500, with **SelectedExecution804 instead of814**. Toad is unchanged.
Methods below were read from current source; they identify real responsibilities
and invariants, not a new parallel registry or a claim that any proposed split is
already proved. Existing domain ownership is not an active full-class claim.

| Current owner / source, declared lines | Actual behavior that must remain owned across closure | Current assignment / concrete remaining gap |
| --- | --- | --- |
| C:history_views.py HistoryViews1018 | Notifications/history/attachment and display-basis capture; human painted read acknowledgements; channel/thread/recovery/presence projection. | **Parent target-thread projection** subset for Tesla168; **full residual decomposition unassigned**. Preserve E4 displayed-only ACK and inherited routing; source-read366 does not close this class. |
| C:coordinated_runtime.py SelectedExecution804 | Selected assignment/execution, native preparation, source-aware presentation and final admission/publication/custody. | **Wegener domain**;363 bounded reader/result deletion complete. **Remaining whole-owner closure not claimed**, coordinate next Q4/native scope. Preserve NC/NR exact execution fences. |
| C:goal_attempts.py GoalAttemptStore781 | Goal generation/readiness/recovery grants, attempt launch/resume/failure, provider-usage ledger and terminal retirement. | **Unassigned residual store scope**; Boyle365 owns scheduling, not a claim to this whole store. Preserve owner pause, generation CAS and E1/E3 outcomes. |
| C:message_bus.py MessageBus752 | Delivery/inbox projections, human/history source routing and pages, read/activity projections and passive awareness. | **Unassigned residual scope**. Keep one durable wire/delivery authority, automatic NR and human E4 semantics; no second awareness ledger. |
| C:compaction_journal.py CompactionJournal743 | Operation and selected-summary reservation/terminal state, enrolled owner coverage, raw-input send fence and committed publication linking. | **Unassigned whole-owner scope** including Q13 chains. Preserve MC/FT/UNKNOWN and native proof lineage; no journal/history reset inferred by splitting. |
| C:turn_runner.py TurnRunner721 | Input/goal scheduling, native turn events, terminal settlement and queued follow-up execution. | **Boyle365 active** scheduler/control/queued acceptance deletion; source main not yet changed. Preserve E1 ordinary/manual/relay effects and NR no replay. |
| C:wire_log.py WireLog659 | Canonical durable/private marker, verified full/certified reads, keyed receipt resolution and append/snapshot history. | **Unassigned residual scope**, Q13 identity comparison. Preserve strict duplicate/corrupt receipt rejection and publication lock/prefix authority. No lock or reader deletion solely for a metric. |
| C:input_drain.py InputDrain607 | Existing input queue/binding and Started/refused/UNKNOWN facts, owned inbox observation/drain/wake, native binding and follow-up lifetime. | **Unassigned full-owner scope**; coordinate Boyle365 queued acceptance seam. Preserve real input disposition, NR automatic return and no implicit UNKNOWN replay. |
| C:acp.py CommsAgent576 | ACP attach/new/input/config/cancel adapter, runtime requests and private cursor publication/refresh. | **Unassigned residual scope**. External ACP remains external; preserve MC actual socket/attached compact route and FT real first-input facts. |
| C:thread_management.py ThreadManagement561 | Register/claim/import/restore/rename, model/settings/session attachment, archive/fork/adoption and incarnation preservation. | **Unassigned residual scope**, Q13 import identity. Preserve FT true selected fork history/budget/parent custody and current registry identity. |
| C:owner_compaction_commit.py OwnerCompactionCommit543 | Native witness/source capture and independent CAS, selected commit/decline/original admission and interruption reconciliation. | **Unassigned residual scope**. Preserve actual NC/MC summary one-input transaction/native CAS; separate operation roles are not automatically duplicate code. |
| C:attempt_store.py AttemptStore512 | Coordination execution lease/advance, connectivity/replay/recovery audit and fenced settlement. | **Unassigned residual scope**. Preserve E3 legal transition, rollback, exact fence and failure equivalence. |
| T:widgets/conversation.py Conversation1936 | Prompt/editor, input/queue submission, transcript/navigation/rendering, permission/goal/tool presentation and session lifecycle. | **Carver170 active** input-case/submission lifecycle;163 proves retained painted bodies, not full Conversation closure. Coordinate Tesla retained body/source surfaces. |
| T:app.py ToadApp1510 | App/workspace routing/opening, screen/source activation, current permission/system/terminal/application lifetime. | **Noether169 active** thread opening;166 attention done. First-frame siteQ7 and other residual owners need exact further scope. No mixin relocation. |
| T:acp/agent.py Agent1134 | ACP request/notification/session update/permission/file/terminal RPC, prompt lifecycle, attachment, queue/goal/cursor owner requests. | **Unassigned full residual owner scope**.Carver167 configuration deletion complete; don't relabel it active ownership of every Agent role. Reuse existing AgentProcess/Session/Configuration owners. |
| T:widgets/comms_sidebar.py CommsSidebar924 | Navigation hydration/selection, visibility/observation and cached sessions, canonical snapshot polling and publication, grouped/virtual rows and action menus. | **Unassigned residual scope**.Noether169 routes do not claim this widget. Preserve UI physical channel/participant navigation, bounded work and canonical source custody. |
| T:widgets/comms_chat.py CommsChatView732 | Message paging/mount/history edge, style/prompt routing, painted human ACK and notification/activity refresh. | **Unassigned residual scope**.Tesla source policy domain coordinates; no full active extraction claim. Preserve UI/NR actual reply feedback and E4 displayed-only ACK. |
| T:widgets/transcript_history.py TranscriptHistory529 | Source/window/filter/page coverage and loader lifetime, preparation admission, scroll intent and exact display publication. | **Tesla168 active domain**, Q1 identity/admission caller closure.162 filter portion done; final retained/revision/reader state remains actual scope, not editor-only evidence. |

Unassigned means no current whole-responsibility implementation claim was found,
not that the historical feature has no author. Parent should assign coherent
behavior slices from this queue; this audit introduces no competing implementation.

## Original shared requirements

Source: original `00-index.md` acceptance1–5 and `01-shared-abstractions.md`.
Round2 rules override internal goldens/compatibility/freezes; owner overrides CI.

| ID / explicit requirement | Status | Current owner/caller and acceptance source | Remaining gap / owner |
| --- | --- | --- | --- |
| G1 new-case authored edits decrease to the declaration | I/U | Maintained event, phase, coordination, goal, export, command/new-helper family tests below. | Historical before/after authored edit counts for every noun not reconstructed; parent evidence qualification. |
| G2 surface NRA findings gone, no new findings | U | CE is real81/0 inventory with139 leads. | Not a current or zero-debt scan; parent/NRA owner. |
| G3 RuleR chain/type/string-read counts decrease | I/U | Per-slice receipts, current packaged ratchet; REG/FIL/CFG/ATT reductions. | Not every original baseline-to-final surface reconstructed. |
| G4 full suite/merged-tree CI gate | S | Newest explicit CI-deferred/focused+affected installed/LIVE instruction. | No full-suite-green assertion; parent actual pair gate. |
| G5 no duplicate roster, forwarding service or second authority | I/O | Domain components replace Comms aggregates; A1–A14 reused. | Q6 codec replicas and Q1–Q8 residual owner decisions; not global certification. |
| A1 derived family names, collision refusal, per-family registry/capability membership | I | C:declared_family.py:86, tests/test_declared_family.py; TI commands/settings. | No new foundation needed. External spelling overrides remain legitimate. |
| A2 field-derived encode/decode, strict keys/types, declared external names | I/O | C:field_codec.py:40; tests/test_field_codec.py; core272/283/287/319 caller closures. | Q6 Toad codec forks still need actual replacement/callers. |
| A3 state-specific data/successors/behavior; derived transition relation | I | C:lifecycle.py:13, execution/attempt/obligation/goal/journal families; E3. | Further S14 consumer decisions do not imply lifecycle family absent. |
| A4 every applicable class/MRO handler, shared capability reactions | I | C:mro_dispatch.py:21, agent_events/agent_event_updates; E1. | No second event dispatch inventory required. |
| A5 command-owned parameters/preconditions/effects, inbound/outbound | I | C:command.py:9, runtime_requests/cli_commands/pi_commands/goal_actions;287 typed tools. | None identified in the original central command seams. |
| A6 correlation/timeout/cancel helper reused at distinct boundaries | I | C:pending_requests.py:19; tests/test_pi_rpc_nominal.py; E1 future controls. | Distinct ACP/Pi instances are intentional, not duplicate authorities. |
| A7 incarnation, owner and turn identities change for the right event | I | C:thread_identity.py:21/59, exact TurnLeaseFence/ProcessIdentity; REG/S5 tests. | Q3 remaining callers still compare constituent facts. |
| A8 typed document ownership, shared reads/exclusive atomic updates | I | C:locked_store.py:23 and actual document stores; tests/test_locked_store.py; E7. | Do not replace append-only wire or SQLite transactions with JSON. |
| A9 only exact displayed basis advances human read | I | C:read_basis/read_ledger; E4 and retained native ACK. | Later source revision/custody Q1 belongs Tesla. |
| A10 one backend event family shared by producers/consumers | I | C:agent_events.py; E1, no old agent_loop implementation. | External Pi/session records are separate legitimate boundaries. |
| T1 golden names/formats | S/I | Only external Pi/ACP/ANSI/settings contracts stay pinned. | Our runtime/store formats are current-only; no internal equality restoration. |
| T2 test-only member works without old consumer/catalog edits | I/U | Named family/new-case tests below. | Do not infer a test for every historical family from examples. |
| T3 characterize a real defect before replacing behavior | I | S4 ledger/current native/return RED receipts retained; UI old475/ea15 and corrected8207. | Historical chronology cannot be recreated as a new test. |
| T4 recorded old/new replay | S/U | E1/E2 current behaviors executed. | Deleted consumer equality superseded; external Pi case coverage still qualified. |
| T5 random read operations preserve displayed-only invariant | I | C:tests/test_read_ledger.py/test_view_unread.py, OS/E4. | Scoped model+real crash controls, not all imaginable user sequences. |

## C0: original carve and final deletion

Source `C0-carve.md` §§3–5; round2 `03-COORDINATION.md` D20 drops the carve.

| Requirement | Status | Actual source/evidence | Gap / owner |
| --- | --- | --- | --- |
| Split operations/declarations solely for disjoint wave ownership | S/I | Explicit Comms construction root/domain components already landed180/182/Toad89. | Temporary mixins are no longer desired; do not redo C0. |
| Each old method belongs to one owner, no duplicate MRO method | I | Current comms.py/domain direct callers, original caller closure206/Toad100. | Historical method-identity relocation test is superseded, not new proof of behavior. |
| Temporary star-import aggregates keep73 old importers unchanged | S/D | operations.py/declarations.py absent; current callers direct. | Round2 forbids restoring them. |
| Ultimately remove mixins/aggregates and migrate Toad | D/I | Current source absence; TI/current installed UI. | Done for these named APIs, no new alias. |
| Unchanged full suite, exact unchanged NRA count, every-module import, crossings | S/U | Current domains and import paths inspected; no full suite run here. | Historic relocation-only oracle dropped with D20; broad import health not newly executed. |
| Every module≤1000 except temporary bus/registry | O | Current coordinated_runtime1005 and child_process1350 are counterexamples to literal universal cap. | Q8 parent-owned meaningful decomposition/qualification, not a freeze. |

## S1: event identity, consumers and settlement

Source `S1-event-protocol.md` §7 migration1–8, §8 acceptance1–6 and OPEN1–3.

| Requirement | Status | Current source / acceptance | Gap / owner |
| --- | --- | --- | --- |
| M1 event family plus shared consumer | I | agent_events/agent_event_updates, tests/test_agent_events.py; E1. | None in named old mechanism. |
| M2 all backend sites construct typed events; StreamSettled distinct | I | backend/TurnProgress; E1 normal/tool/manual/provider terminal facts. | No dict-event adapter restored. |
| M3 move giant ACP event arms to owning handlers | I | MRO consumer; runner/progress323 deletion receipt. | Scheduler residue Q3 is S7/S14. |
| M4 participant consumer/shared tool/info reactions | S/I | Unused agent_loop deleted; current native consumer E1. | OPEN3 deletion is intentional; no second loop to resurrect. |
| M5 collapse setting maps into shared correlation | I | PendingRequests; E1 equal IDs/failure/late result controls. | CFG167 separately closes Toad configuration mirrors. |
| M6 one public settlement owner across ordinary/manual/relay | I | turn_runner.settle_turn; E1 actual all three routes. | None; do not rewrite tested settlement. |
| M7 subscriber terminal/no-active-turn cases carry typed identity | I | TurnSettled/NoActiveTurn; E1 and T2. | No empty-ID compatibility substitute. |
| M8 delete string backend event dispatch and guard it | D/I | Old consumer/procedure deleted; maintained event/turn-progress guards. | Scope-specific evidence only. |
| A1 new event handled with unchanged consumer | I | tests/test_agent_events.py; DeclaredFamily/MRO. | Universal historical edit census G1 remains qualified. |
| A2 consumer string-dispatch guard | I | Current typed events plus maintained ownership guards. | Not a new global scanner result. |
| A3 normal/tool/compaction/model/thinking/diagnostic/reason observable effects | I/U | E1+E2 real current paths and typed effects/futures. | Exhaustive historic old/new stream replay superseded/unproved. |
| A4 former settlement sites same required effects, pause_waits OPEN2 | I | E1 manual success/refusal/relay/native lease/wait ordering. | Current ACTIVE standby clearing deliberately differs from old PAUSED policy; recorded, not hidden. |
| A5 RuleR decreases in touched files | I/U |323 deletions and per-slice ratchets. | No entire original baseline reconstructed. |
| A6 no shim/second event-name roster | D/I | No retired agent_loop/dict consumer; canonical family. | Not a global zero-mirror verdict. |

## S2: external Pi boundary and turn ownership

Source `S2-pi-rpc-boundary.md` §§7/8.195/196 already replaced the initial payload bypasses;
later303/311/325/359/362 strengthen actual lifecycle paths.

| Requirement | Status | Current source / acceptance | Gap / owner |
| --- | --- | --- | --- |
| M1 single PiRpcChannel for every reader | I | pi_rpc/backend/native readers; tests/test_pi_rpc_nominal.py, NC. | No retired _JsonLineReader. |
| M2 typed known/unknown Pi events decoded once | I | pi_events/pi_payloads; tests/test_pi_payloads.py;196/283. | External unknown lines retain their defined behavior. |
| M3 PiCommand response/correlation/session mutation capability | I | pi_commands/PendingRequests; native catalog316 and tool344 declaration guards. | No eight response-key dispatch copies. |
| M4 failure code/text/uncertainty/precedence owned by cases | I | turn_failure, tests/test_pi_rpc_nominal.py:94; E2 actual503/no resend. | Diagnostic text does not infer delivery. |
| M5 TurnSession replaces19-parameter closures | I | backend/turn inputs/stats/usage; NC. | Label original extraction correctly, not an extra session mechanism. |
| M6 typed TurnPhase excursions/stall exemption | I/O | turn_phase family/new-excursion test; current native reuse. | Q4 remaining consumer flag chains do not satisfy full S14 closure. |
| M7 UsageAccount owns nested accounting | I | turn_usage/actual typed usage; FT usage vs bytes correction. | Universal nesting bound not reconstructed. |
| M8 no raw Pi line decode/kind/phase switches outside owners | I/U | Current Pi channel/payload guards, NJ/NC. | Broader new helper/private format checks scoped, no global clean claim. |
| A1 new excursion and failure declaration-only | I | tests/test_pi_rpc_nominal.py:49/94. | No additional generic fixture required. |
| A2 complete external transcript scenario matrix | I/U | Original10 scenarios +303 seven actual native cases + current manual/selected/reuse/provider evidence. | Every abort/steer/UI/stall/malformed/unknown/failure combination not established; Q10 parent/Wegener triage. |
| A3 every co-occurring failure has correct winner/text/code/uncertainty | I/U | Declared precedence pair tests and E2. | Declaration-pair test is not exhaustive actual reachability. |
| A4 decoder/phase guards | I | Maintained Pi/S10/native guards; OS fixtures current. | No new run in this audit. |
| A5 retired stream gone, every new method≤100, nesting≤5 | D/U | _stream_agent_events absent; backend706 with no>500 class. | Universal original/new-module≤100/≤5 not certified; Q8/Q10. |
| A6 clean NRA/RuleR in all touched modules | I/U | Retained per-slice receipts and CE. | CE contains raw leads; no universal clean scan. |

## S3: coordination state, legality and transactional recovery

Source `S3-coordination-state.md` §§7/8.292 removes coordination.py;301 removes
coordination_store.py/MutationStore, preserving transactional domain owners.

| Requirement | Status | Current source / acceptance | Gap / owner |
| --- | --- | --- | --- |
| M1 client roster replicas decode through canonical families | I/D | Recovery gateway typed records; tests/test_coordination_nominal.py. | No _STATUSES-style second registry. |
| M2 shared lifecycle/derived encoder, delete Projected mirrors | I/D | Lifecycle/FieldCodec, recovery owners;292/301/E3. | No old to_primitive mirror restored. |
| M3 obligation states own publication/successors | I | obligation_states; E3 current family projection. | None identified in old mechanism. |
| M4 execution states carry only legal data | I | execution_states; E3 real SQLite snapshots. | Residual SelectedExecution scheduling Q5 is different. |
| M5 assignment/claim state and wake policy behavior | I | claim/assignment owners, WakePolicy;350/351 and E3. | Actual frozen response authority NR retained. |
| M6 attempt lifecycle after OPEN1 disposition | I/S | Current actual attempt families/persistence, E3. | Unproduced historical phases not a restore obligation. |
| M7 RecoverySnapshot composed/encoded and cross-rules named | I | Current recovery family/table owners; E3 all47 original predicates. | Named constructor validation is not redundant solely because typed. |
| M8 delete literal transition tables/enum/string rosters | I/D |292/301 ownership guards, current families. | Scope-specific evidence; no all-source zero-case claim. |
| A1 test-only execution/obligation states decode/transition/project | I | tests/test_coordination_nominal.py. | Existing edges legitimately declared by predecessor owners. |
| A2 requested NRA cases/mirrors gone | U | CE full inventory/raw reports. | Absence of all named findings not certified at current main. |
| A3 exact old DB/gateway strings roundtrip | S | Round2 current-only schemas/runtime reset; D22 durable history separate. | No historical DB reader or internal golden restoration. |
| A4 old transition table equality before deletion | S/U | Current transition behavior/E3. | Historical exact table replay not recreated. |
| A5 every47 predicate/coupling executed or structurally impossible | I | E3 predicate-behavior.json/111 installed checks; real rollback/reopen. | Old source-accounting-only gap is closed, not still pending. |
| A6 full suite/merge gate | S | Owner CI override; focused/affected-path receipts. | Parent current pair gate only. |

## S4: channels, human-read authority, routing and presentation

Source `S4-thread-routing.md` PartsA/B/C, §§7/8.

| Requirement | Status | Current source / acceptance | Gap / owner |
| --- | --- | --- | --- |
| A built-in channel names, owned marker filename, derived records | I/D | ChannelCatalog/BuiltinChannel/ReadLedger/FieldCodec;192/204/205. | Broadcast alias later forbidden/deleted, not a missing feature. |
| B1 characterize any-mode/rebind/crash false reads | I | tests/test_read_ledger.py/test_view_unread.py; E4. | Maintained cases, no duplicate matrix. |
| B2 ledger keyed by viewer/conversation and exact display basis | I | read_basis/read_ledger; E4 replacement/painted prefix. | Fetch is not ACK. |
| B3 conservative scalar/view2 migration with notice | S/I | Current-only runtime marker reset, D22/retained cutover receipts. | Round2 explicitly revokes view2 preservation; no old scalar loader. |
| B4 every ACK/unread consumer routes through display authority | I | Mounted E4 real channel/DM/native/hidden/executor distinction. | Parent current live source-rebind gate independent. |
| B5 decide transcript versus conversation read fact OPEN1 | I | E4 explicit independent native offset/bus/executor facts, one durable read authority. | Bus ACK must not advance native offset. |
| B6 characterization cases now pass | I | OS/E4 actual crash/mode/rebind controls. | No suite-wide PASS inferred. |
| C ResponsePolicy owns eligibility/start/batch/input decisions | I | response policy declarations/current callers; E3+NR. | Automatic reply delivery solved331; not manual later-history substitution. |
| Viewer owns user/executor distinctions | I | E4 mounted/hidden controls. | No role string roster needed. |
| Display computation outside bus, one-way authority dependency | I | presentation/history owners; original S4/OS guards. | No fresh global import graph proof claimed. |
| Guards built-ins/policies/marker keys/import direction | I/U | tests/test_s4_ownership.py and core/current caller closures. | Scoped guards, not a source-wide alias allowlist claim. |
| A1 new view/policy/alias cases | I/S | Current view/policy family tests. | Alias new-case part superseded by L0 deletion; do not reintroduce broadcast. |
| A2 read implies displayed across random operations/crash | I | Ledger property/current mounted E4. | Future arbitrary permutations not universally proved. |
| A3 PartB characterization | I | E4. | Closed current obligation. |
| A4 existing old markers load/reset visibly | S | Runtime reset/current-only reader. | No historic-reader completion task. |
| A5 Toad ACK callers coordinated | I | E4 actual mounted native/channel/DM ACK; UI current journey. | Updated pair live proof remains parent-owned. |
| A6 NRA named policy/role/audience/control/mirror findings gone; DisplayOrder justified | U | CE requested coverage exists with findings. | Specific universal absence/DisplayOrder proof not established, Q10. |
| A7 full suite/merge gate | S | Owner override. | No CI hold. |

## S5: duplicate authorities and identity meaning

Source `S5-duplicate-authorities.md` §§7/8. Counter/current proof behavior is
distinct from retired identifier spelling or old registry format preservation.

| Requirement | Status | Current source / acceptance | Gap / owner |
| --- | --- | --- | --- |
| M1 resource_claims and its exclusive test deleted | D | Named module absent at pinned core; original206 closure. | None. |
| M2 classify old epoch increments by owner/incarnation/turn | I | ThreadIncarnation/OwnerIdentity/TurnIdentity; REG. | Historical classification receipt retained, no old epoch migration. |
| M3 split counters, turn claim never bumps owner identity | I | tests/test_turn_lease_release.py/current registry identity tests. | Exact lease remains; don't replace with PID. |
| M4 each expected generation consumer asks the right identity | I/O | Current typed fences,353/357/361 migration. | Q3/Q5 still compare parts at consumer sites. |
| M5 DM proof compares participants, not global registry revision/turn epoch | I | E4 accepted turn/rejected true rebind controls. | No whole-registry staleness mirror. |
| M6 old epoch identifiers/load keys retired | D/S | Core206/round2 loader deletions; durable retained references not renamed by guess. | Old-key loading explicitly superseded. |
| M7 attention/turn lease meanings separate | I | WakeAssignment/TurnLeaseFence/current ownership vocabulary. | User-facing claim tool/external concepts stay meaningful. |
| M8 guards enforce distinct identity/no obsolete mechanism | I | Exact turn release/owned-send/registration guards. | Blind ban of every external/history word is not proof. |
| A1 removed resource authority | D | Source absence. | No resurrection. |
| A2 owner/turn/rebind counter semantics | I | Current identity/lease/registration tests, REG restart journey. | Installed proof is Linux/current pair, not every platform. |
| A3 DM accepted after turn, rejected after deletion/recreation | I | E4 both directions. | Closed current behavior. |
| A4 pre-change registry loader | S | Round2 no dual-format loader. | No compatibility task. |
| A5 new owner-sensitive consumer/unrelated registry mutation | I | Current typed identity/ledger controls. | G1 universal historical edit counts qualified. |
| A6 no new mirrors/RuleR | I/U |353/357/361 per-file receipts. | Not universal zero-debt. |

## S6: export ownership and callers

Source `S6-export-kinds.md` §§7/8; round2 revokes named compatibility factories.

| Requirement | Status | Current source / acceptance | Gap / owner |
| --- | --- | --- | --- |
| M0 build A1/A2 once | I | Shared canonical modules/tests. | Q6 fork codecs not permission for another foundation. |
| M1 format owns header/row/importable | I | Current export families; tests/test_export_families.py/test_exporting.py. | Internal flag removal depends on actual external use, not a name grep. |
| M2 limit owns own data/bounds/truncation | I | Current export limit declarations. | No kind coercion. |
| M3 scope validates/resolves through catalog | I | Direct current scope/canonical channel owners; retained export receipt. | No #any duplicate literal admission. |
| M4 keep named constructors for old Toad | S/D | Round2 revokes; actual direct CLI/Toad callers migrated. | Do not restore factories. |
| M5 no old scope/limit kind/string re-coercion | D/I | Original exporter/caller deletion evidence and maintained family tests. | Scope-specific, not all raw-record absence. |
| A1 all old scope×limit×format byte goldens | S/I | Genuine export format tests retained. | Our internal scope header preservation not a blanket compatibility requirement. |
| A2 new LastMessagesLimit without exporter edit | I | tests/test_export_families.py:90. | Closed declaration experiment. |
| A3 actual Toad export construction/current calls | I | T:evidence/export-caller-migration/HANDOFF.md. | Old factories not the acceptance oracle. |
| A4 clean NRA kind findings | U | Original scoped evidence, CE. | No current global clean scan. |
| A5 each member validates only its fields, no re-coercion | I | Declaration constructors/current callers. | Actual boundary validation remains correct. |

## S7: residual owners, locks, tools and scale

Source `S7-residual-god-classes.md` §§7/8; original tools closure287 and paired
Toad132 are incorporated. The benchmark obligation is executed, not pending.

| Requirement | Status | Current source / acceptance | Gap / owner |
| --- | --- | --- | --- |
| M1 adopt locked documents/shared reads, remove facade lock wrappers | I | LockedStore/document owners; E7 actual lock timing. | Wire/SQLite/native authority transactions intentionally retain locks. |
| M2 RuntimeRequest/CliCommand derive parser and behavior | I | runtime_requests/cli_commands; original/new-case tests and287. | No central tool tuple/handler/kind roster remains from287. |
| M3 ACP update consumer over typed events replaces _emit_event | I/D | AgentEvent/MRO/AgentCommsUpdate; E1/TI. | Shared extension handling not a second protocol family. |
| M4 Pi decode and session-transcript families | I | PiRpcChannel/NativeEntry/NativeTranscript196/202/283/306. | NJ durability retained; issue107 separate. |
| M5 ACP session/input/turn/config state components | I/O | Session/input/turn owners;323 and Toad167. | TurnRunner/SelectedExecution residuals Q3/Q5/Q8. |
| M6 WireLog/Publisher/Registration own state | I |184/REG current boundaries, one root format. |361 registry lifecycle now merged, not pending. |
| M7 Comms becomes composition root, no carve mixins | D/I | comms.py components/callers. | No service forwarding old self. |
| M8 delete aggregates/migrate all actual importers | D | Named aggregate modules absent; Toad89/100 direct callers. | None in those retired names. |
| M9 no outer store mechanics/string command dispatch, module≤1000/method≤100 | I/O/U | Canonical stores/commands; counterexamples Q8. | Literal universal lock-location grep not achieved/appropriate authority proof; parent classify, don't remove fences. |
| A1 runtime/CLI/document/ACP update new cases | I/U | Canonical command/store/event tests;287 new native tool membership. | All four historic authored-edit count experiments not universally reconstructed. |
| A2 50/100/150,three pollers,p50/p99,wait/hold before/after | I | E7 executed current+pre-A8,1200+600 sends. | Shared flock reduced wait; total-send causal/uniform improvement NOT proved. No rerun. |
| A3 runtime/CLI/stores contracts and paired Toad callers | I/S | Current typed callers/TI/287+Toad132. | Internal-format goldens superseded; external CLI/ACP honored. |
| A4 all size/lock guards/aggregates gone | D/O/U | Aggregates gone; Q8 actual size counterexamples. | Parent scope actual owners; no blanket structural PASS. |
| A5 clean NRA/RuleR | I/U | Per-slice ratchets; CE contains139 leads. | Not current universal clean. |
| A6 full-suite/merge gate | S | Owner override. | Parent actual affected pair gate. |

## S8: goals, pause authority and notification

Source `S8-goal-lifecycle.md` §§7/8.190/323/353 close record/action/progress/failure
authority; remaining scheduling chains belong Boyle365/Q3, not a new GoalState family.

| Requirement | Status | Current source / acceptance | Gap / owner |
| --- | --- | --- | --- |
| M1 typed goal/pause source carries provenance | I | goal_states/goal_management;190, test_goal_nominal.py. | Unknown interrupted inputs still retained/no automatic replay. |
| M2 remove goal string-switch/toggle mirrors | I/D | GoalState presentation/current Toad goal owners. | Current goal scheduling predicate Q3 remains separate. |
| M3 typed actions/shared compare-and-set instead of15-parameter switch | I | goal_actions/GoalPrecondition. | None in original central dispatch. |
| M4 actor capabilities derive model choices | I | Current ModelInvocable action/tool declarations287. | External comms_goal spelling may remain declared. |
| M5 authoritative GoalChanged replaces tool-name inference | I | goal_management event and runner consumer; E1. | Native publication triggered by own authority, not tool text. |
| M6 GoalExecution derives from typed state/waits | I | Current execution owner323/E1. | No second goal-status map. |
| M7 typed ready/reserved generation, one waits filename, state presentation | I |190/323 typed goal attempts/waits. | Scheduler ready admission stillQ3. |
| M8 no status/action/name inference/coercion guards | I | Current goal/action/owned progress guards. | Scoped evidence; not all scheduler completion. |
| A1 pause source/action/new paused rewrite controls | I | test_goal_nominal.py including automated owner-pause preservation:144. | G1 universal historical experiment qualification remains. |
| A2 old registry/pause status byte compatibility | S | Current-only round2/D22 retained history distinction. | No old goal loader. |
| A3 external model tool schema behavior | I | tests/fixtures/s8/comms_goal_schema.json;287 schema receipt. | Actual external names honored, internal schema tag can change. |
| A4 each action/current goals behavior | I | Goal family/action/standby/owner pause tests, E1 actual wait release. | No broad unchanged rerun. |
| A5 clean goal NRA findings | U | CE plus historical scoped receipts. | Current universal absence not claimed. |
| A6 full suite/merge gate | S | Owner override. | No CI hold. |

## Added original closure: R1–R7, D1–D4 and PF1–PF5

These later dispatch requirements remain in the whole goal. Old future-work
phrasing in the historical dispatch is superseded by actual current code/PRs.

| Requirement | Status | Deletion / acceptance source | Gap / owner |
| --- | --- | --- | --- |
| R1 Pi payload boundary: declarations own request/event/tool data; old raw mirrors deleted | I/D |196/Toad96, current Pi payloads/events/tool socket; E2/NC/FT. | Current admission conditionsQ4 are a later S14 obligation, not evidence the196 caller migration never landed. |
| R2 catalog documents and Message: one modeled document/projection boundary | I/D |192/Toad94, current Message/catalog declarations, original8478 retained rows/projections receipt. | No old catalog loader; universal mirrors qualificationG2/G5. |
| R3 input/delivery documents: migrate queue/cursor/recovery and retain failed input history | I/D |199/Toad97 followed by272/318 current InputAttempt/structured RequestFailed; E2/NR. | Current UNKNOWN/Started/not_sent semantics supersede the earlier input shape; no replay. InputDrain residual classQ8 not fully closed. |
| R4 goal-attempt lifecycle: typed generation/attempt/provenance and actual goal caller closure | I/O |190/Toad93 followed by323/E1 and current typed goal families. | Boyle365 schedulingQ3; GoalAttemptStore residualQ8 remains unassigned, not covered just by190. |
| R5 runtime/collaboration documents: typed owner projections, activity sorting and metadata | I/D |195/Toad95, current document/runtime request boundaries; original174 checks/10000-record activity receipt. | Current target-thread projectionQ12 is parent-owned performance follow-through, not a second document authority. |
| R6 saved transcripts: whole original/attached source with cursor/render/input/ACP consumers | I/D |202/Toad99 and306 current native transcript codec/callers, E4/UI. | Canonical source read identity/reuse paired366/168 remainsQ12; do not restore TranscriptCodec or truncated history. |
| R7 selected execution: actual transaction vocabulary/lease and native consumers | I/D/O |202/206+Toad99/100, current source/assignment authorities; AW363 removes awareness bridge and validates actual installed native tools. | SelectedExecution804 residualQ8 remains Wegener domain; no claim its whole owner decomposition is complete. |
| D1 one manual transaction/current owner, delete direct weaker writer | I/D | Canonical compact_manual_owner/bridge, retired manual_compaction.py absent;251/253, MC. | Distinct manual versus automatic operation remains intentional D21. |
| D2 operation/summary/publication lifecycles, terminal/UNKNOWN/ACK rules | I | compaction_journal families186/272, actual journal/native/MC receipts. | No nullable old outcome adapter; UNKNOWN must never imply admission. |
| D3 typed NativeWitness, decoder once, native independent disk CAS | I | Shared witness/preparation/commit callers185/283/308. | Native freshness verification is essential, not duplicate Python shape checking. |
| D4 remove str summary/test adapter and detached provider | D/I | Canonical selected summary path;185/343 delete unused/dry-run path. | No standalone paid transport added. |
| PF1 native tool runtime status/data one owner | I | NativeToolCall/OwnerToolSocket/current native tools344/287. | No new case roster. |
| PF2 wire metadata/prefix/marker/seals derive from authority | I | WireMetadata/PrefixWitness; C:evidence/pf-deletion-closure/AUDIT-PF1-PF5.md. | Current proof checks retained. |
| PF3 native proof decode/current bounded framing | I | NJ/284. | Does not close all issue107 recovery/memory criteria Q11. |
| PF4 route observation avoids constructing Comms | I | resolve_comms_route/source observation receipts. | Route boundary validation stillQ5. |
| PF5 historical view scope/index targets captured once | I | HistoryView/historical_page current code; PF audit. | Tesla canonical page revision reuse is distinct current workQ9. |

## Round2 rules, cutover and L0

Source `00-RULES.md`, `03-COORDINATION.md`, `L0-legacy-sweep.md` (archive+loose copy).

| Requirement | Status | Current source / acceptance | Gap / owner |
| --- | --- | --- | --- |
| Exactly one current internal format; external formats honored | I/O | Current typed store/protocol readers; no old converters. | Q6 current codec adapters violate latest ownership rule; not an old-format reader claim. |
| Runtime/derived reset, durable history classified/carried once | I | D22/retained-history-live-cutover/attached-history-checkpoint receipts; old operators264/345 removed. | Preserve native durable proof; no blanket reset. Parent cutovers. |
| D22 rewrite durable wire once in place | I/D | Parent's actual conversion and history/checkpoint preservation receipts; current-only WireLog; tools deleted264. | No converters to restore; later frozen response authority conversion is separately recorded331. |
| Quiet paired install/restart, settings/history/no replay preserved | I/M | Parent deployment receipts through warm-native/workspace and current359 stage. | This audit does not attest live activation of5059/11d; parent owns that gate. |
| Delete replaced code/tests/docs/config, report removed/added lines | I/O | Substantial named deletions in core292/301/323/325/REG and Toad162/166/167. | Remaining scoped Q1–Q8; net growth alone not debt proof. |
| Total caller/guard closure, no unnamed stubs | I/O | Named paired implementations; queue above. | No whole-goal COMPLETE assertion while Q1–Q13 remain. |
| Behavior tests, families/new cases, external goldens only; no weakened assertions | I/S | E1–E4/UI RED retained and later GREEN. | Old internal-format goldens superseded; exhaustive evidence stillQ10. |
| Guards retained/required CI | I/S | Packaged ratchet/surface guard files present. | Automatic/required CI explicitly deferred, not a new block. |
| One current owner per coherent scope; disjoint worktrees/claims and actual caller handoff | I/U | Current365/366/168/169/170 scopes and supplied parent Q4/Q6/Q7 assignments; this audit preserves all producer ownership. | No universal audit of every agent's claims; unassigned residual table is concrete parent dispatch. Older feature freeze/review ceremony is superseded by newest progress instructions. |
| Original promised coordination-plan file | U | Original index references02-coordination-plan.md; it is absent from the supplied original archive and dispatch worktree. Actual index/round2 coordination rules are mapped here. | No invented acceptance from an unavailable file; parent supplies it only if a separate authoritative document still exists. Not a product/CI hold. |
| L0A goal/registry/epoch/scalar marker/broadcast/attempt/catalog legacy readers deleted | D/I | Current loaders/names and retirement audit; round2 deletions/D22. | Lexical markers alone do not prove behavior. |
| L0A unused legacy transcripts/channel tool/helpers gone | D/I | Current catalog/typed tools287, native transcripts202/306. | External/durable contract not reset by grep. |
| L0B publisher/input-drain/wire production one path | D/I | Private native production entrypoint/D22/NR, no supervised_cutover.py. | No old root/path flag. |
| L0B delete one-use tools and exclusive old tests | D/I | tools/cutover absent at core snapshot; retired modules absent. | Parent preserves previous failure/history receipts. |
| L0 literal zero legacy/compat/fallback/shim/cutover tokens | U/O | Core still uses local diagnostic variable fallback (acp_failure:201/230); external fallbackTransport is Pi-owned. | Not a second old-format path. Lexical guard stricter than semantic debt; parent classify without inventing feature work. |

## R0/TR0 and R1 coverage

Source round2 `R0-R1-stop-the-inflow.md`; Toad `TR0-ci.md`; later S14/T9 ratchet.

| Requirement | Status | Current source / acceptance | Gap / owner |
| --- | --- | --- | --- |
| R0 packaged touched-source differential measures, move/reduction/new-file behavior | I | C:debt_ratchet.py, tests/guards/test_debt_ratchet.py; core254/268/347. | No repeated measurement here. |
| R0 no pragma/allowlist/baseline exception | I | Current ratchet/ownership guards, no exception alias found in owner read. | Manual owner override is distinct. |
| R0/TR0 automatic required PR ratchet/suite under one minute | S/U | Workflows explicitly workflow_dispatch/manual while CI deferred. | Not enabled required PR status; deliberately not a merge gate. Historical runtime receipts only. |
| S14/T9 chain terms per touched file, codec subclasses, >500 excess, foreign absence | I | Canonical shared measures/core347; Toad pins packaged CLI. | Existing debt is allowed to persist under growth ratchet; Q6 fork codecs remain actual debt. |
| TR0 one shipped CLI with --root, delete tools/debt_ratchet.py copy | I/D | agent-comms-ratchet packaged console, Toad workflow invokes it. | No second script. |
| TR0 derive pilot collection, don't rewrite228 pilots | I | T:tests/conftest.py;117/268. | Full collector run not newly proven green; no blind port. |
| TR0 move profiling scripts/delete manual procedure/editable stack roster | I/D | tools/performance and117/268 retired driver evidence. | One runtime command receipt is not an active hardcoded test driver. |
| TR0 every pilot pass or justified deletion, no retries/skips/internal goldens | I/U | OS and specific deleted obsolete test mechanisms; CI deferred. | No final all-pilots PASS claim or unnecessary unchanged matrix. |
| TR0 no hardcoded /home paths in executable tests/src | U | Own current UI pilot uses env paths; historical operator/receipt paths are not that pilot. | Not globally inventoried here; no automatic cosmetic sweep assigned. |
| R1.a mapping-read descent, decode site excluded | I | NRA PR9 merged; CE78 mapping projections and seven mirror leads. | Current domain meaning still reviewed manually. |
| R1.b unmodeled3+key shapes and positive/negative tests | I | CE33 raw shapes, PR9 owner evidence. | Not every raw shape is an internal protocol to delete. |
| R1.c declared redundant attribute type checks | I | CE56 paired leads/PR9 fixtures. | Constructor validation can be necessary; don't delete annotations blindly. |
| R1 full inventory/calibration≤25% growth | I/U | Earlier PR9 calibration44.11→50.06s,13.49%; CE81/0 inventory. | Current main timing/context clean verdict not rerun. |
| R1 receipt contains bypassed/unmodeled/type owner evidence | I | CE paired-raw/summary and canonical skill instructions. | Full/raw CLI scan_status reporting gap sent existing NRA owner; no toolmissing CI hold. |

## S13/A12: process lifetime

Source `S13-child-supervision.md`, shared A12; later native/Toad lifetime callers.

| Requirement | Status | Current source / acceptance | Gap / owner |
| --- | --- | --- | --- |
| One lifted process owner/stop algorithm and shared grace | I | ChildProcess/AttachedChild/BoundedRun/DetachedProcess, NC and actual process tests. | OS/native abort grace has distinct semantic role. |
| Always process group; stronger namespace capability explicit | I/U | Real Linux group/namespace/cancellation/deadline proofs. | Darwin/Windows native all-platform acceptance not supplied; Q10. |
| ProcessIdentity pid+start, liveness/signals never bare PID | I | Exact DetachedProcess tests/current registry startup;359/REG. | Already-running settings/session preserved. |
| Platform capability family, no scattered platform switches | I/U | Current child_process owner/capabilities and guards. | Whole-platform behavioral proof not inferred. |
| ChildOutcome variants reflect exit/signal/timeout/start failure | I | tests/test_child_process.py new outcome:124. | No flag-bag outcome adapter required. |
| Every owned spawn/stop/liveness caller migrated and old algorithms deleted | I/D | S13 guards, NC native custody, Toad152 current AgentProcess. | No second startup patchQ4. |
| Three shapes grandchild cleanup/identity refusal/newcase | I/U | Actual Linux child tests and attached/native reuse evidence. | All three CI platforms unproved, no CI wait. |
| Owners relaunched at cutover | I/M | Parent D22/current deployment histories; idle exact fences. | Current11d/5059 activation is parent, not this audit. |

## S12/A13: typed persistence

Source `S12-typed-tables.md`, shared A13, including projections/native inputs.

| Requirement | Status | Current source / acceptance | Gap / owner |
| --- | --- | --- | --- |
| Frozen row owns schema/keys/indexes/STRICT, DDL derived | I | typed_table.py:348 and coordination/compaction rows230/237/292/301. | Retained external/durable tables preserve valid contract. |
| Delete hand mappers/positional inserts and string/index row reads | I/D | Current typed owner/caller guards; E3. | Toad MODEL_HISTORY_SCHEMA remains a separate T8 store witness, not core S12 completion evidence. |
| Typed projection-query result records | I | Current coordination/recovery database query rows;292. | No second raw-result authority. |
| NativeRuntimeInput row and actual readers migrate | I | InputRow variants272/318, native send/admission proofs. | not_sent versus Started UNKNOWN distinction remains binding. |
| Names derive from admission/turn identities, no retired schema aliases | I/D | Current declared schema, no old epoch loader. | Preserve historical bytes only through completed cutover classification. |
| Runtime tables reset; durable tables carry once/delete tools | I/D | D22/parent cutover receipts264/345; no tools/cutover at snapshot. | Do not reopen a converter path. |
| One family roundtrip/new table declaration and meaningful store behavior | I | tests/round2/test_typed_table.py; E3 real commit/rollback/reopen. | Not another per-table fake matrix. |
| Guards no hand DDL/raw row/positional writes in owned core sites | I/U | Maintained typed-table/mutation guards;301 source deletion. | Current global zero raw SQL not newly scanned/proved. |

## S10: small remaining Pi boundaries

Source `S10-pi-boundary.md` V1–V3.

| Requirement | Status | Current source / acceptance | Gap / owner |
| --- | --- | --- | --- |
| V1 SelectedToolRequest from_wire/from_arguments deleted; canonical decode | I/D | Selected tool owners/FieldCodec; tests/test_s10_boundary_guards.py. | External tool names/schema honored. |
| V2 verify_sent_full_input uses typed NativeRuntimeInput | I | InputRow/current verification boundary;272/318/native guard tests. | No nullable old state/UNKNOWN replay. |
| V3 UI choice cancelled/confirmed/value owner, no raw choice keys | I | ExtensionUiChoice declarations, current Pi response. | Admission surrounding choice remainsQ4; don't claim fully closed S14. |
| Strict boundaries/no hand modeled record reads; delete old parser tests | I/D/U | S10 guards/NJ current callers, OS deletions. | No blanket absence of every new boundary typecheck. |
| External Pi recordings preserved; broker internal goldens deleted | I/S | Current Pi contract tests vs our current-only socket. | Exhaustive Pi external matrix qualificationQ10. |

## S9/A14: compaction

Source `S9-compaction.md` K1–K6 and D21. Manual and owner compaction are
distinct operations sharing lower-level authorities, not duplicated pipelines.

| Requirement | Status | Current source / acceptance | Gap / owner |
| --- | --- | --- | --- |
| Existing operation/summary/publication states reused | I | Journal families186/272 and MC. | Do not replace sound pipeline roles. |
| K1 one PiCompactionSettings, no copied default16384/20000/second settings | I | Current canonical settings/decision/native helpers; FT actual units correction. | No hidden disabled compaction/cap raise. |
| K2 embedded JavaScript becomes packaged helper code/typed records | I/D | PiHelper/shared helpers; tests/round2/test_pi_helper.py, S9 guards. | No new script strings. |
| K3 journal/fresh/continued tables through A13 | I | Typed journals/runtime input states; actual retained/restart/MC. | Journal reset at parent cutover, history preserved. |
| K4 helper/manual/watchdog process supervision through A12 | I/D | NC canonical process custody; retired manual writer/launcher algorithms. | Namespace/authority FD guarantees retained. |
| K5 exact key-set hand parsers replaced by FieldCodec | I/D | S9 strict boundary/new-helper tests; NJ/MC current callers. | Native independent source validation still required. |
| K6 guaranteed type rechecks removed after boundary tracing | I/U | Scoped S9 owner receipts/current typed source; CE type leads. | Not every boundary check is redundant; current universal zero check not claimed. |
| One real pinned-Pi helper integration per helper | I/U | Prior S9/native helper proofs and actual selected/manual paths. | Every today's helper separately accounted/executed not newly reconstructed. |
| A14 declaration-only helper test | I | tests/round2/test_pi_helper.py:23 NewCaseHelper. | No second helper runner. |
| External Pi settings contract preserved | I | Actual native settings/context admissionFT; canonical units not JSON length. | Parent actual configured-provider GetState intermittency remains parent-owned. |
| No local subprocess/JS strings/raw rows/settings replicas, current result callers migrated | I | S9 guards,319 corrected derived kind/324 actual socket route,343 dryrun deletion. | Q6 Toad adapters are outside this compaction closure. |

## Toad common rules, TL0 and T1–T3

Source Toad package rules/index and each named surface target/guards/tests/done.
TD1 shared core owners; TD3 agent-comms fork only; TD2 CI later overridden.

| Requirement | Status | Current source / acceptance | Gap / owner |
| --- | --- | --- | --- |
| TD1 shared core A1/A2/A13, no parallel base/library | I/O | Current direct core imports. | Q6 existing subclass codecs are the concrete violation. |
| TD2 required CI from first day | S | Owner CI deferred; manual workflow present. | No hold. |
| TD3 delete old alternate ACP-client shapes/capability negotiation | I/D |107/118/T2, pinned MCP current admission. | Genuine official ACP SDK formats remain external. |
| TL0 legacy models/text-only/transport-only/row aliases removed | I/D | Current typed extension/process/navigation,167 model decoder deletion. | No backwards-compatibility restoration. |
| TL0 delete product test-target hook | D | TOAD_COMMS_TEST_TARGET absent in current production grep; guards. | None. |
| TL0 dead modules removed after entrypoint check | I/D |118/107/l0a receipts; render_server is actual entrypoint. | Not every source module newly globally reachability-certified. |
| TL0 capability negotiation/MCP executable defaults removed | I/D |118/158 actual current MCP owner. | Current external discovery doesn't justify old handshake. |
| TL0 zero lexical markers/dead-module/test-env global guards | U/O | External Rich legacy_windows/TTY_COMPATIBLE legitimate; render_zmq compatibility_with is build refusal; backward cursor comments innocent. | Stricter rename-only guard not wholly satisfied. Do not call these automatically old behavior or spawn cosmetic sweep. |
| T1 each SettingKind owns parse/constraints/widget | I | setting declarations/kinds, tests/settings_tree_pilot.py and tests/test_settings_guards.py; T:evidence/t1/HANDOFF.md. | No schema_to_widget switch. |
| T1 typed attribute tree/effect on declaration, derived screen | I/D |119/current settings, setting_effects/screen; old Settings.get/schema/INPUT_TYPES/setting_updated absent. | No dotted-key coercion API. |
| T1 choice behavior/capability composition incl expansion | I | Setting choices/ExpansionPolicy current caller. | New declaration experiment scoped. |
| T1 valid/invalid widget family/new kind+effect/save/current settings load | I | Retained T1 consumer/settings/effect/load pilot logs. | No repeated whole settings matrix. |
| T1 all45 old read sites/guards deleted | D/I | Current name search plus T1 caller guard receipts. | No current global no-string-key claim. |
| T2 extension declared once and every producer constructs shared facts | I | Core acp_extension/decode_updates + Toad handler,262/122/125. | No new extension copy. |
| T2 decode once, UI carries record not copied field messages | I/D | TI/current Agent boundary, hand cursor/queue decoders gone. | Current public failure family reused by log viewer. |
| T2 one coordination owner, no private name probes | I | Typed Comms interface/state owner125. | Whole T4 configuration/context extraction is separately167/169. |
| T2 capability flags/epoch names/shape negotiation deleted, features on | I/D | TI/core262 caller closures; parent default bus/runtime activation. | Preserve external ACP capabilities, not our retired feature flags. |
| T2 shared family roundtrip/new fact producer→handler/real recorded path | I | Paired TI and maintained T2 guards, actual UI+E2 typed failures. | No internal golden protocol matrix. |
| T2 readable typed errors/detail/disposition, no diagnostic retry inference | I | core276/acp_failure + actual provider1011/UI/log receipts. | Started failure never automatic resend; parent live intermittency distinct. |
| T3 slash command owns name/help/parse/apply; advertised commands boundary | I/D |120/125 command catalog and ACP advertised command;53 superseded. | Actual completion/member tests retained. |
| T3 ThreadAction owns core command/labels/menu/completion | I/D | Current thread_actions and typed core tools287/Toad132 migration. | No restored TOOLS alias. |
| T3 MCP uses Textual button declarations/typed inventory | I/D |120/158 MCP boundary; current mcp_inventory no6-term chain. | Earlier six-term MCP queue is closed, not still unassigned. |
| T3 family/new-command/no name probes/string rosters guards | I | tests/guards/test_t3.py, T:evidence/t3-sol/HANDOFF.md/menu receipts. | Scoped acceptance, not every future command shape. |

## T4: actual residual state owners

Source `T4-god-classes.md`; latest principle13 supersedes raw all-class growth
ratchet with **excess beyond500**. Small valid owners can absorb behavior.

| Requirement | Status | Current source / acceptance | Gap / owner |
| --- | --- | --- | --- |
| TurnOwner carries permissions, no self.turn string authority | I/D |127/current ConversationTurn; T4 mixed block/turn pilot. | None in that retired mechanism. |
| Blocks own navigation, one cursor movement, no BlockProtocol checks | I/D |127/149 ContentNavigation/BlockCursor, protocol.py deleted. | Current native/terminal widgets retain correct non-DOM capability. |
| TabOrder owns open/close/focus previous, no App list mirror | I/D |130 tab owner/current callers. | Workspace custody isTesla168, not a new tab pool. |
| Clipboard family chooses once, no scattered App platform strategy | I/D |130/current clipboard, actual X11/PTY receipt. | No new platform acceptance matrix here. |
| Agent process lifecycle/attachment/custody moved together | I |131/152 AgentProcess; NC/current attached native UI. | Parent configured GetState intermittency remains actual issue, not proof of no lifecycle owner. |
| Agent configuration actual state+operations/callers moved together | I/M |167/CFG now merged5059; old _publish_models/ID/controller/thinking mirrors deleted. | Parent deploy/LIVE gate; no stale pending167 label. |
| App attention/title/desktop/Ask/permission lifetime component | I/M |166/ATT,148 production lines deleted; App size1510. | Parent current paired LIVE check. |
| App thread opening intent/task/routes/dedup/cancellation owned | O |169 active code-bearing draft, actual source still has opening function/map. | **Noether169**, no competing task. |
| Conversation input cases, source-bound draft/queue submission and return lifecycle | O |170 active code-bearing draft; normal main still owns submission closure in Conversation. | **Carver170** current input scope. Preserve actual QueueItem/request custody and UI no replay; not a competing Tesla viewport implementation. |
| Root/source actual field+mutation owners; no mixin carve | I/O | WorkspaceChrome/NativeSessionSurface/Viewport;160 and open168. | Other large residual responsibilitiesQ8 require actual owned scope, not file relocation. |
| Each extraction reduces new-case count, report residual size/justification | I/U | Scoped CFG/ATT/T4 receipts; AST exact large-owner inventory below. | Whole T4 residual ownership not complete merely because size fell. |
| Class-size/turn/navigation/tab/clipboard guards | I/U | Current shared excess ratchet/tests/guards/test_t4.py. | Existing >500 owners and Q2/Q8 remain; growth guard isn't absolute cap. |
| Turn/navigation/tab/clipboard behavior tests | I | Existing installed mixed block/turn/X11/T4 receipts. | No repeated matrix, current continuous UI supplements real user path. |

## T5: comms interface and source state

Source `T5-comms-interface.md`; later T9 assigns its source chains to T5 owners.

| Requirement | Status | Current source / acceptance | Gap / owner |
| --- | --- | --- | --- |
| SidebarRow owns activate/menu/target; ChannelLike derived grouping | I |121/125 rows/typed NavigationTarget and current CommsSidebar. | No kind:string dispatch/second literal pairs. |
| One ConversationKind reused for sidebar and rendering | I/D |123→125; HistoryKind retired. | No parallel row/history vocabulary. |
| RowAction/menu choices derived, ThreadAction reused | I |120/121/current core287/Toad132 context menu. | No old raw action dict/TOOLS roster. |
| Transcript state owns publication/pruning/closing permissions | I/O | TranscriptState/source preparation, current publisher. | Q1 remaining publication/snapshot chain still actual workTesla168. |
| Filter owns snapshot/admission/coverage/cancel/retirement | I |162/FIL deletes overlay flags/private probes/precreated workers. | Old transcript_filter14-term remainder is closed. |
| Events own merge behavior, no type comparison roster | I | T5 EventMerge/shared family and125. | External SDK type boundary stays legitimate. |
| Goal display distinct no-goal/showing/unavailable | I |121/current goal interaction144. | No optional goal+flag illegal state. |
| Delivery errors use T2 shared family | I | T2/276/current failed input and typed error view. | No delivery inference from diagnostic strings. |
| Sidebar queried by widget owner not identifier mirrors | I | Current nominal sidebar/nav guards. | No new sidebar. |
| Family/state/new row tests and retired flag/dispatch tests removed | I | tests/guards/test_t5.py and TI T5 logs. | Later source-return behavior UI/OQ1 still separate. |

## T6/T7/T8: rendering, terminal and small boundaries

| Requirement (source surface) | Status | Current source / acceptance | Gap / owner |
| --- | --- | --- | --- |
| T6 tasks derive membership; reusable task meaningful key | I/D |123 render tasks/PreparedRenderer; no RENDER_TASK_TYPES. | No extra syntax/render cacheTesla168. |
| T6 command payload is the declaration; enum/paired payload match gone | I |123 render_protocol/shared family. | Q6 RenderCodec is a separate ownership violation. |
| T6 each reply carries valid state data and owns client transition | I |123 render replies/client exchange. | No old RenderStatus switch. |
| T6 backend family owns startup/typed setting selection | I | RendererChoice/current local/persistent startup. | Parent coherent pins required. |
| T6 categories/capabilities own presentations, typed routes | I |123 MessageCategory/conversation kinds. | No hand-built membership roster. |
| T6 codec roundtrip/reply behavior/new declaration/performance | I/O/U | render_families_pilot/T6 receipt; original render pilots. | Q6 codec fork; universal no-slowdown final-current claim not established. |
| T6 retired enums/roster/status chain tests deleted/guards | I/D |123 source closure/TI. | No aggregate T6 COMPLETE whileQ6 ownership remains. |
| T7 each ANSI command owns async apply, union/match gone | I/D |114 ansi declarations,44 real contract cases. | External cursor reply stays async. |
| T7 each StreamRead owns feed, shared loop, type switch gone | I/D |114 parser/read hierarchy. | No parser-result shim. |
| T7 modes/escape introducers derived family, feature bags gone | I/D |114 modes/numeric external names/introducers. | Actual external bytes honored. |
| T7 external sequence table/new command+mode/deletion guards | I | T:evidence/t7/HANDOFF.md; current guards. | No new per-member matrix. |
| T7 mounted large terminal stream no slower | I/U | Retained median5.293740→5.173180s; intermediary regression retained. | Local matched proof, not universal current latency guarantee. |
| T8 one terminal environment/shell selection used by both launchers | I/D |115 TerminalEnvironment/current shell+CommandPane, real PTY receipt. | Literal external variable names correct. |
| T8 Session typed row/derived DDL, prompt_count correct | I |115 current db Session TypedTable;46 original copied rows preserved. | MODEL_HISTORY_SCHEMA is additional hand DDL outside Session, not proof all DB tables derived. |
| T8 SessionMeta decode once, actual readers/update caller migration | I/O |115 current typed metadata/ACP/store/resume callers. | Q6 SessionCodec must be replaced while preserving durable external values. |
| T8 DangerLevel owns spans, bashlex visitor, unused aggregate gone | I/D |115 danger visitor/current Prompt spans and dead DangerWarning removed. | External command data is not a closed family roster. |
| T8 real DB load/metadata/PTY/resume/danger/new declaration guards | I/O | T:evidence/t8/HANDOFF.md; actual SQLite contention/mounted46 sessions. | Historical receipt explicitly used codec subclass; latest TIME-9 overrides that rationale. |

## Later S14 and T9: completion is still open

These are binding **current** requirements, not optional polish inferred from
line counts. Source observations below were read from the pinned files; they are
counterexamples to completion, not a reexecution of an overlay detector.

| Requirement | Status | Closed portion / remaining precise source | Owner |
| --- | --- | --- | --- |
| S14 per-file chain-term/codec/>500-excess/absence ratchet first | I |347 packaged canonical measures and current Toad dependency. | Parent preserves measure when pairing; no new tool. |
| S14 each identity compared once through its determining owner | I/O |350/351/353/354/357/361 remove admission/awareness/goal/registration/registry chains. TurnRunner ready/queued sites still Q3. | **Boyle365 active**; not yet merged. |
| S14 absence reported by state owner, not nullable field recombination | I/O | owned_turn now no6+ specimen; live status/UI pi_events remainingQ4. | **Wegener Q4 queued after363**, no completed proof yet. |
| S14 shape decoded once, consumers trust typed boundary | I/O |350/351/357 and NJ; active route raw decoderQ5 remains; supplement replaced/deleted363 with actual installed native evidence. | **Parent active-route queue**; Wegener363 portion complete. |
| S14 unrelated rules name failures; literals/own flags use family/state | I/O | Existing ReservationRule/admission state/current response owners. | Dominant-kind classification before Q3–Q5; never mechanically one rule per term. |
| S14 no chain of6+ anywhere; take every chain in owned file | O | turn_runner564/720; pi_events344/372; active_route154; wire_log361/thread_management251/compaction_journal505/841 explicit current counterexamples. | Q3–Q5/Q13. No global remaining count asserted. |
| S14 behavior equality/named failure, not structural goldens | I/U | REG/E3/NR/NC behavior and prior per-slice guards. | Remaining actual caller behaviors must accompany assigned implementations. |
| T9 own flag state per affected widget | I/O | ToolCall/session_view long specimens now absent; Plan/tool/process owners145/151/152. Prompt chainQ7 and publicationQ1 remain. | Tesla168/Noether169; Prompt Noether next queueQ7. |
| T9 source/intent snapshot compared once, not parts | I/O |162 FilterSnapshot/current retired workspace preparation. Transcript history811 eight-piece condition remains. | Tesla168. |
| T9 no private foreign-state conditions/type recovery | I/O | T2/162/167 remove known mirrors; transcript publication102 still probes window/agent/dirty fields. | Tesla168, preserve actual ownership. |
| T9 MCP validation/literal rules family | I |158/current mcp_inventory.py no6+ condition in bounded read. | Noether completed; don't reassign old census specimen. |
| T9 no6+ anywhere including T4/T5 shares | O | App661/764/1089, Prompt476, publication102/history811. | Noether169 opening; Tesla168 source; Prompt476 **Noether next queue**, App661 requires Noether/parent exact scope confirmation. |
| T9 guards/ratchet stand, original whole-widget caller deletion | I/O | Current guards/ratchets and162/167; residual sites above. | Don't claim allcomplete from decreasing total. |

## Feature/PR reconciliation required by the whole goal

| Item / explicit acceptance | Status | Actual current disposition/evidence | Remaining owner |
| --- | --- | --- | --- |
| Core271 summary terminal failure and not_sent input family | D/I | CLOSED, merged through272 per terminal PR comment. Current typed input/recovery, retained native failed/UNKNOWN controls. | No duplicate PR271 merge or old decoder. |
| Toad53 command/menu discovery | D/I | CLOSED, superseded120/125 per terminal comment; current CommandCatalog/ThreadAction/core287+Toad132. | No new prototype; external ACP commands preserved. |
| Toad50 bootstrap cookie/protected routes/WS Host+Origin/auth before child | I/M | MERGED c3f7b632, web_server BrowserAdmission, WEB actual installed Chromium/ACP/stream. | Parent current/live browser validation if shipping route, not an unmerged source task. |
| Toad50 no second server/flag, old227 mock-only tests/docs deleted | I/D | Existing textual-serve serving paths reused; WEB. | Provider turn/general external hosting not claimed or silently required. |
| PR116 unique viewport PageDown/End painted-tail gate | I | Adapted through142/160, UI/retained_body_transfer/viewport_rapid_scroll. | Tesla168 continuation; don't merge obsolete Screen/chrome/pins. |
| PR116 persistent selected surface across logical session kinds | I/U | Current WorkspaceScreen/native frame/source owners129/142/156/160; real continuous UI saved/native/channel/fork. | All possible64 executing/mixed agents not proved by blank64 or two-native proof. Tesla168. |
| PR116 bounded inactive rich presentation, operational ACP/permission/state preserved | I/U |160 visible leaf identity/editor/undo/Agent/process and existing byte/widget/LRU;UI. | Visible/protected data can exceed warm quota; no whole-process RAM ceiling. Source read/revision reuseQ9. |
| PR116 matched4/16/32/64, spike/GC/input tails,30–40ms goal | O/U | Historical blank64/native input adverse tails retained;160 warm return519–569ms,168411–458ms. | Tesla168; useful functionality ships before final target. Not median-only completion. |
| PR116 final whole suite/new pins/local+LIVE entry proof | S/M/U | Exact final full-suite pass not asserted; owner CI deferral. UI passed candidate8207; parent deploys coherent current pair. | Parent current LIVE gate, no unchanged suite gate. |
| PR163 complete actual saved/native journey + all distinct final receipts | I/D | Test code via160; final distinct evidence MERGED75eb17e via163.34 paths reconciled; no source/evidence left unlanded in163. | Completed; don't rerun unchanged. |
| Parent actual configured Sol high fork clone | I/U | Latest supplied18.56s second attempt PASS, first GetState timeout RED retained. | Parent owns intermittency; not assigned to acceptance workers. |
| Saved native ordinary/fork first input must not force compaction under budget | I | FT true token budget/context branch,0 compaction, two actual first-answer cases. | User attempts preserved; UI compaction progress owner separate. |
| Sending in channel wakes/answers/visible notification; return response reaches author | I | NR/UI actual automatic native author response context, Responding/Responded, no manual inbox/prompt/no loop. | Current pair's affected LIVE gate parent-owned, not a passive-history substitute. |
| Issue107 nonhardcoded durable bounded recovery | O/U | OPEN; NJ doesn't supply full specification. | Q11 parent assignment; no raised-cap bandaid. |

## What this map deliberately does not claim

- No percentage, every-file zero-debt result, detector-certified current main,
  every-family historical new-case count, exhaustive external Pi matrix, all-platform
  child correctness, final full-suite green, universal size/nesting/lock-location
  compliance, matched final latency, or current live activation of this snapshot.
- Old snapshots saying S7 benchmark unexecuted, C0 missing, PF3 decoder unclosed,
  S3 legality only source-accounted, S4 mounted ACK absent,163 receipts missing,
  or167 still open are superseded by the named actual evidence/current Git/PR state.
- No compatibility reader, namespace/PID guarantee, native CAS, wire durability
  barrier, UNKNOWN input or human-read authority may be discarded just to satisfy
  a lexical/size metric. Latest ownership patterns apply to product and tooling.
- Current active code scopes: Boyle365/Q3, parent Q6, Tesla366/168/Q1/Q9/Q12,
  Carver170 submission, Noether169 opening. Queued Q4/Q11 Wegener, Q5 parent and
  Q7 Noether remain unmerged. **Unassigned** residual owner decompositions below
  and Q13 are reported for dispatch, not claimed actively worked. This audit does
  not compete with their implementations. CI/final latency do not block useful shipping.

## Reproduction of this audit, without tests or new runtime

Read the three listed plan archives in place with Python `zipfile`; read later
S14/T9 loose files. Use `git show <snapshot>:<path>`/`git grep <snapshot> -- src/...`
for the named declarations/callers/retired modules, and `ast.parse` on the named
owner files for class/method extents and `BoolOp` nodes with at least6 operands.
The line observations count declared extents, including methods/docstrings, not
physical file size as class size. Query current PR state separately from archived
receipt prose. No generated extraction, source copy, runtime or scan cache retained.

This is a pinned completion snapshot; later merges should update the
affected requirement rows using current main and named actual receipts. Parent
owns assignment, coherent paired installation and affected LIVE verification.
