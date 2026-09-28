# T4: Remaining god classes

**Head audited:** Toad fork `main` at `43e57c9` (#108). **Rules:** [00-RULES.md](00-RULES.md). **Origin:** both. **Step 4,** last. Pattern IDs refer to the refactor-audit skill's catalog.

This surface runs against classes the other surfaces will already have shrunk, so its file names what is known to remain and how to judge the rest. **Re-measure at dispatch** (`overlay.py --upstream upstream/main` shows each class's size then and now) and rewrite this file's findings against that head before starting.

---

## Where the classes stand

| Class | At the merge-base | At `43e57c9` | Taken by other surfaces |
|---|---|---|---|
| `Conversation` | 1,686 | 3,049 | T2 extension handling, T3 slash commands, T5 goal display |
| `ToadApp` | 632 | 1,902 | T1 setting effects, T3 thread actions |
| `Agent` | 773 | 1,886 | T2 extension decoding, coordination facts and hand mappings |

`Conversation` and `ToadApp` both grew again while these plans were being written (from 3,042 and 1,889 at `511a1a2`): **AGENT-4 is still happening.**

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
