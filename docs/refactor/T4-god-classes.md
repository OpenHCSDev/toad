# T4: Remaining god classes

**Dispatch head:** Toad fork `main` at `67ddc9e` (#125), 2026-09-28. **Rules:** [00-RULES.md](00-RULES.md). **Origin:** both. **Step 4,** last. Pattern IDs refer to the refactor-audit skill's catalog. The original audit below is retained as history.

## Current independent App slice

Parent assigns TabOrder and text clipboard strategy to Sol in
`~/wt/toad-t4-tab-clipboard-sol-20260928`. Carver owns Conversation/blocks/Agent
in PR127; Tesla/PR116 owns workspace/resource state, editor/shell/Agent lifetime
and screen pooling. Coordination is recorded in their existing PR threads.

AST dispatch sizes: ToadApp **1,803**, Conversation **2,943**, Agent **1,523**
lines. ToadApp still owns open order, visited-history list/cursor and history
pruning/traversal (16 order sites), and lazy clipboard support/per-copy branching.
This slice transfers those fields and mutations into TabOrder and the clipboard
family. Logical mode identities are not a second workspace/session registry.
Screen construction, mount/reparent, resource teardown, existing target labels
and Conversation/Agent ownership stay with their assigned owners.

Completion includes deletion of `_open_tab_order`, `_tab_history`,
`_tab_history_index`, history bookkeeping helpers, `_supports_pyperclip` and the
mocked clipboard transport test; actual callers consume the new owners directly.
Textual's public `copy_to_clipboard(text)` contract remains the framework boundary.
UI events and state guards exercise the installed components; private X11 and
real PTY output establish clipboard transport. No live/shared checkout writes.

### App slice completion receipt

Initial integration base is merged `main` b472e487/Toad128; final branch is
rebased onto parent132/main b4bdae1 with core287 and merged Textual8. Six installed
owner/native/tab UI checks pass; the independent per-class ratchet has zero
positive deltas. This slice preserves
ViewportPresentation and Carver's merged owners. Compared with that main,
ToadApp is **1,803 → 1,712** AST span lines; PromptTextArea **368 → 363**
(check the shared ratchet for semantic-size counts). Conversation **2,829** and
ACP Agent **1,354** are unchanged here and remain separately owned. FilePreviewScreen
stays **26** semantic-size lines: the framework Screen name owns the filename,
its project_path owns the containing directory, and the mounted preview owns
its file path. No additional full-path mirror or compatibility property remains.

TabOrder owns opening order, visit history, cursor, pruning and previous/next
navigation plus its change Signal. Closed intervening visits can leave adjacent
visits to the same mode; the owner now advances that cursor without remounting
or replaying the same Screen. All main/channel/pending/preview callers use this
owner; root-private history methods and fields are deleted.

New-case edit counts: a new clipboard behavior adds **one declared subclass,
zero App/Prompt/consumer branches or registry entries**, verified by the new-case
guard. A new logical tab kind admits/retires its identity through the same
open/close API, requiring **zero order/history/previous-tab implementation
edits**; formerly its lifecycle sites had to maintain App's private order and
history-pruning helpers. The component is not a second workspace catalog or a
mixin carve.

Clipboard selects its platform transport once, shares Textual's existing local
value, and owns native copy and threaded paste. Actual X11 testing found that
xclip may return text for an unsupported image/png target. The image boundary
now reports no PNG and lets native text paste continue; genuine PNG capture,
size bounds and attachment storage stay in their existing owner.

The 106-line mocked clipboard transport test is deleted. Retained pilots use
actual installed components, private runtime roots and local native transports;
no provider prompt is sent. Receipts and exact installed dependency origins are
recorded with the PR. Shared per-class/AST guards apply independently; CI is
deferred by owner instruction. Workspace/resource/surface lifetime remains
Tesla's scope and Conversation/blocks/operational Agent remains Carver's scope.

This surface runs against classes the other surfaces will already have shrunk, so its file names what is known to remain and how to judge the rest. **Re-measure at dispatch** (`overlay.py --upstream upstream/main` shows each class's size then and now) and rewrite this file's findings against that head before starting.

---

## Current dispatch findings (2026-09-28)

Re-measured merged main67ddc9e after125, with all T2/T3/T5/T6 declarations retained. This worker owns Conversation turn state/block navigation and ACP Agent process lifecycle only. Parent retains App TabOrder/clipboard; Tesla116 owns App/MainScreen/workspace lifetimes.

| Class | Current AST span | Residual ownership |
|---|---:|---|
| Conversation | 2943 | string turns plus managed ID/ingress order; duplicated outer/inner block selection |
| ToadApp | 1803 | parent and Tesla116; excluded from this slice |
| Agent | 1523 | subprocess/group/task lifetime mixed into ACP protocol handling |

Conversation still stores string turn permissions at13 sites plus watcher dispatch; managed turn ID and ingress source/sequence are independent fields. Prompt and two command callers repeat the string test. A TurnOwner family and a ConversationTurn component will own permissions, managed identity and ordering; adding a state requires its declaration, not consumer branch edits.

Only AgentResponse implements inner BlockProtocol navigation. Conversation repeats protocol probing in cursor movement, selection and current-block access. A nominal block contract will supply an owned cursor component for atomic blocks or child navigation; one content navigation component owns outer selection. New block behavior belongs at its declaration; movement consumers stay unchanged.

Agent owns process, process-group ID, stopping flag and two lifetime tasks, plus a separate response-task set. Start/run/EOF/stop duplicate cleanup and OS decisions. This is a real component boundary: AgentProcess will own subprocess/task lifetime, with one platform control selected at the OS boundary. ACP decoding/session/auth/attachment facts remain Agent-owned. No persisted store changes.

## Now, before step 4

Add a class-size measure to TR0's ratchet: **no class in `src/toad/` may grow past its size on `main`.** It stops the growth today, costs nothing, and leaves the decomposition itself to this surface. Features that would have grown a big class get their own owner instead, which is the correct outcome anyway.

---

## Known residual responsibilities

**Turn ownership as strings (IDEN-3, IMPL-2).** `Conversation` compares or assigns `self.turn` against `"agent"` and `"client"` at 15 sites, and gates behaviour on it (`elif self.turn == "agent": …` inside command handling). Target: a `TurnOwner` family (`AgentTurn`, `ClientTurn`) owning what each permits (`accepts_prompt`, `can_compact`), consuming T2's turn records.

**Block navigation written twice, with protocol checks (IMPL-12, BOUND-7).** `action_cursor_up` and `action_cursor_down` are symmetric 28-line functions making seven `isinstance(…, BlockProtocol)` checks between them, asking whether each child is a block at all. Target: the conversation's content holds only blocks (non-block widgets live outside that container), blocks own whether they take the cursor, and one `move_cursor(direction)` replaces the pair.

**Tab order kept as a private list (IMPL-8).** `ToadApp._open_tab_order` has 16 uses, including the previous-tab choice TL0 renames. Target: a `TabOrder` component owning open, close and focus-previous.

**Clipboard strategy spread through the application (IMPL-13).** 17 mentions in `ToadApp`, with OSC 52 used when the system clipboard is unavailable. Target: a small clipboard family (`SystemClipboard`, `TerminalClipboard`) chosen once by what the platform supports.

**`Agent` after T2:** the ACP specification's own updates and the agent process's lifecycle. Judge at dispatch whether the process lifecycle deserves its own component.

---

## How to judge the rest

- **Extract components that own state** (IMPL-8): a component takes the fields it owns and the methods that change them, and the big class delegates to it.
- **Never carve mixins.** Mixins split one class's `self` across files, and a new case still edits the same shared state (AGENT-6).
- **Every extraction must reduce a new-case edit count,** stated in the PR. An extraction that only moves lines is relocation; label it as such or drop it.
- Report each class's size before and after, and the components extracted.

## Guards

The class-size ratchet (above); no `self.turn` string comparisons; no `BlockProtocol` checks in navigation; `_open_tab_order` used only inside `TabOrder`; clipboard handling only inside the clipboard family.

## Tests

One state test for `TurnOwner`'s permissions; one navigation test across mixed blocks; one test each for `TabOrder` and clipboard selection. Delete tests of the replaced branches.

## Done when

The known responsibilities are owned by components, the classes' remaining size is justified by what they still own (stated in the PR), and the guards pass.

## Dispatch

> **`toad-t4`:** Complete T4 per `docs/refactor/T4-god-classes.md`, after T2, T3, T5 and T6 merge. Read `00-RULES.md` first. Re-measure the classes at your head and rewrite this file's findings against it before extracting anything. Components that own state, never mixin carves; every extraction states the new-case edit count it reduces.

## TL0 ownership handoff (Copernicus, 2026-09-28)

Parent's existing T4 ownership includes `app.py` previous-tab/local-thread
selection names and OSC52 comment, plus `widgets/transcript_history.py` cursor
direction wording. Remove the remaining TL0 marker vocabulary while closing
these files; preserve clipboard and pending-thread behavior. The `getattr`
shape probes remain assigned to T4 by TL0's original plan. TL0A has removed
Conversation's `in_out_only` and migrated all retained filtering callers.

## TR0 class-size closure (2026-09-28)

Comms PR268 adds the required independent class-size measure to the existing installed ratchet. Paired Toad117 pins that implementation and passes it against current main. Unique qualified-name moves retain their baseline; new owners report no baseline until their first merge. Existing classes cannot offset their growth with another class shrinking. This closes the immediate TR0 guard requirement; the remaining T4 decomposition is still assigned in its existing order.

## Goal/input-delivery observation closure (current main137, Carver)

Current main5983adb remeasure: Conversation AST span 2817; this slice 2709.
The duplicate goal and input-delivery task/revision/read loops are removed.
SessionObservation owns one scheduling/custody lifecycle; GoalObservation and
InputDeliveryObservation own source reads and their typed projection reactions.
Delivery history/dismiss readers leave the root with their revision fence.
Actual callers consume the owners directly, with no old wrappers or fields.
Task cancellation and source-identity fencing prevent stale success/error paint
after rich view retirement or owner replacement. A new case adds one subclass,
zero root/scheduler branch edits. No persistent schema changes.

Existing installed native goal and loopback ACP/UI pilots protect behavior;
retained/live response acceptance now requires compositor text and regions.
The duplicate weak/captured replay pilot is deleted and the existing history
pilot is strengthened. Permanent deletion/new-case guards and scoped per-class
ratchet apply. App/workspace/shell/sidebar lifetimes remain with Tesla/Noether.

## Current remaining dispatch: live output streams (main138, Carver)

Remeasured main06003af: Conversation AST span2709. Its remaining response/thought
state is two nullable blocks, a shared posting lock, duplicate append loops,
route-change finishing, turn-settled loading cleanup and manual reset at15
boundaries. This is transient presentation custody, not source Agent process or
saved transcript state. Next full slice gives admitted blocks and their
mutation/finishing to OutputStream cases, and serialization/boundary/retirement
to LiveOutput. Response delivery belongs to ResponseStream; whitespace-only
initial thoughts and thought-before-response completion belong to ThoughtStream
and ResponseStream. Add a new stream declaration without editing scheduler,
boundary or retirement branches; no hand-maintained kind inventory.

Delete root fields `_agent_response`, `_agent_thought`, `_post_lock` and root
`post_agent_response`, `post_agent_thought`, `new_block`; migrate all event,
checkpoint and retained pilot callers. Keep actual cropped live/native and
retained-read paint acceptance. App/workspace/shell/sidebar and core deployment
remain excluded. No stores or schemas change. Completed production1952bf4:
Conversation AST span2709 →2667. Installed new-case/paint guard, actual native
ACP/UI live and saved cropped paint, retained NRA26-event source paint and
zero-positive class/debt ratchet pass. PR140 receipts record exact boundaries;
parent owns paired merge/live installation. No own-scope blocker remains.

## Current remaining dispatch: saved transcript publication (Carver, after140)

Remeasured ready140f4ec98b: Conversation AST span2667. Root still owns generation,
dirty/required-checkpoint flags, painted cursor and an exclusive worker while
mounting saved snapshots and retiring committed live cohorts. Move actual state
and mutations into TranscriptPresentation; TranscriptPublication public ABC owns
a read's captured source/resources/generation. SnapshotPublication owns the
initial render transaction; CheckpointPublication owns read/prepare/evidence/
publication/retirement using existing CheckpointPlan/CommitEvidence declarations.
No second history engine. A new publication case inherits source/resource fencing
and shared lifetime, requires zero root/scheduler/retirement case branches; root
raw-state hooks and methods are deleted. Source replacement resets the owned
frontier and cancels old work. Late mount invalidation removes the rejected page.

Tesla owns App's single read receipt call; migrate its cursor read directly to
conversation.transcript.displayed_cursor in the same integration, no alias.
Noether panel and Tesla persistent WorkspaceScreen/shell changes are disjoint.
All current source/event/viewport/FollowTailCheckpoint and retained pilot callers
migrate here. New-case/invalidation/retirement, actual native committed-page read
plus cropped paint and retained NRA source paint are acceptance gates. PR141
is the existing scoped draft; no live changes or CI wait.

## Current remaining dispatch: goal interaction custody (Carver, after141)

Remeasured1413faecdf: Conversation2455 AST-span lines. Source goal snapshots are
already GoalObservation-owned. Root still stores goal modal, repeats action
strings across five UI controls, gates polling on modal/current screen, writes
goals and binds editor saves through its mutable current Agent. GoalBar keeps a
second hand-written control inventory and collapse/disabled/toggle decisions.
Next full slice transfers modal/poll/write/edit custody to GoalSession and UI
behavior to GoalInteraction declarations. GoalObservation remains read authority;
core GoalAction/GoalState remain persistent behavior and transition authorities.
Delete root _goal_modal/_poll_goal/change_goal and action ladder; derive controls
and presentation from declarations and migrate slash/current native callers.
One new control adds one declaration, zero root/bar/list branches.

Tesla reusable source initialization owns Conversation constructor/mount binding,
WorkspaceScreen/pool and shell. GoalSession is source-bound: replace after close,
one existing Widget timer dynamically addresses the current owner. Edit captures
Agent+Goal and refuses another source. Noether panels remain untouched. Parent's
partial async-callable worker fix and App cursor closure are consumed exactly in
the isolated continuation; shipping141/shared trees are unchanged.


### Goal interaction completion (merged main129)

Main129e46f8cb remeasure Conversation2358 →2287, GoalBar249 →238,
GoalControl19 →19. Productiona7bda05 transfers complete custody above and removes
all actual root/caller branches. Actual installed native owner/backend goal UI
and final installed declaration/fence/cropped-control paint guard pass;
independent shared per-class/debt ratchet has zero positive deltas. PR144 receipts
separate native backend, controlled UI and parent ACP shipping proofs. No
own-scope blocker. Tesla consumes source-bound GoalSession in reusable view
initialization; parent retains merge/deployment and completed141/143 gates.

## Current remaining dispatch: permission presentation (Carver, after144)

Ready144 remeasure Conversation2287 AST span. Root still decodes external tool
content, chooses a diff modal or inline question and owns display/retirement
closures. Agent PermissionController already owns pending futures, source
attachment, completion and cancellation. This slice decodes presentation once at
ToolPermissionRequest admission into PermissionPresentation declarations; shared
present owns eligibility, Diff/Inline own complete rendering/retirement. Existing
Agent lifetime is unchanged, no new source store or presentation flags. Delete
root raw dispatcher and request raw-tool mirror; actual callers use the decoded
request. A new presentation adds one declaration with admission/behavior, zero
root/controller case edits. Tesla owns source/workspace; Noether renderer is
untouched. Conversation2287→2204; request classes unchanged AST span45/13.
Existing permission lifecycle pilot now checks actual inline/diff paint through
installed RPC, removal/rebinding and final grant/reject/cancel. Obsolete97-line
raw-future pilot deleted. Physical Pi/MCP + actual runtime proxy + installed UI cropped choices, source
removal/rebind, granted execution and child cleanup pass with loopback-only
model. Final shared per-class/debt ratchet has zero positive deltas. Parent owns
merge/install; no own-scope blocker.
