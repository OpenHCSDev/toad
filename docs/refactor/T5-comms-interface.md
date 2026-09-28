# T5: The comms interface

**Head audited:** Toad fork `main` at `43e57c9` (#108). **Rules:** [00-RULES.md](00-RULES.md). **Origin:** fork. **Step 3,** after T2, in parallel with T3. Uses agent-comms' `DeclaredFamily` and `LifecycleState` (TD1), T2's extension records, and T6's `ConversationKind`. Pattern IDs refer to the refactor-audit skill's catalog.

---

## What is wrong

**Sidebar rows are kinds spelled as strings (IMPL-1, MEMB-3).** Rows carry `kind: str` (`comms_sidebar.py:195`, `:228`; `app.py:970`), constructed with literals such as `kind="dm"` (`app.py:1370`, `:1395`). `CommsSidebar.on_click` dispatches on `row.kind` over five kinds (`channel`, `dm`, `irc`, `session`, `thread`); `_virtual_context_menu` dispatches again on `choice.kind` (`channel`, `irc`, `new-session`). The pair `("channel", "irc")` is written four times, each asking "does this row behave like a channel?". The kind string then flows into `NavigationTarget.decode(name, kind)`, one of NRA's findings.

**Row menu actions are read from a raw dict (BOUND-1):** `_show_thread_menu` reads `actions["close_view"]`, `["copy"]`, `["pin"]`.

**The transcript's lifecycle is a set of independent flags (IDEN-3, IMPL-10).** `TranscriptHistory` (680 lines) has 15 boolean chains of four or more terms, the most of any file in the fork, because each decision recombines private flags that together encode one state:

```python
self._committed and self.is_attached and not self._closing and not self._pruning
self.loader is None or not self.is_mounted or not self._publication_current \
    or not self.screen.is_current or not self._selected_categories
self._filter_overlay is None and bool(self._selected_categories) and self._filtered_source \
    and self._filter_has_older and (...)
```

Nothing says which combinations are legal. Merging transcript events decides by comparing types (`type(new_events[0]) is type(old_events[0])` after an `isinstance`), outside the events (IMPL-3).

**The goal display is two fields for three states (IDEN-3, IMPL-10).** `widgets/goal_bar.py` and `screens/goal_details.py` hold `goal: Goal | None` beside `unavailable: bool`, and decide with `goal is not None or self.unavailable`. Of the four combinations, three mean something and one (a goal that is also unavailable) should not exist.

**Errors are classified by type at the use site (IMPL-3):** `CommsChatView.submit_input` (117 lines) switches on the error's type three ways to choose a message.

**Widget identifiers as literals (MEMB-3):** `("channels-sidebar", "thread-sidebar")` is written twice.

**Three god classes grew in the fork (AGENT-4):** `CommsSidebar` 1,083 lines, `CommsChatView` 870, `TranscriptHistory` 680.

---

## Target

### Rows are a family

```python
class SidebarRow(DeclaredFamily, affix="Row"):
    def activate(self, sidebar: CommsSidebar) -> None: ...        # was an arm of on_click
    def menu_actions(self) -> tuple[RowAction, ...]: ...           # declared by the row
    def target(self) -> NavigationTarget: ...                      # replaces decode(name, kind)

class ChannelLike:
    """Capability: rows that behave as channels. Each of the four ("channel", "irc") checks becomes a method here."""

class ChannelRow(SidebarRow, ChannelLike): ...
class IrcRow(SidebarRow, ChannelLike): ...
class DirectMessageRow(SidebarRow): ...
class SessionRow(SidebarRow): ...
class ThreadRow(SidebarRow): ...
```

- Channel, direct-message and IRC rows carry T6's `ConversationKind` (`channel`, `dm`, `irc`), which replaces both the bare strings here and T6's `HistoryKind`: one concept, one family.
- `on_click` becomes `row.activate(self)`; the context menu's choices are members too (`NewSessionChoice`).
- Menu actions are a small `RowAction` family (`CloseView`, `Copy`, `Pin`) declared by the rows that offer them; the raw dict is deleted.
- `NavigationTarget` is produced by the row, so `decode(name, kind)` and every `kind: str` parameter are deleted. (Reassigned here from T6, which lists it among NRA's findings.)
- Thread actions shown in these widgets come from T3's `ThreadAction` family; T5 converts `comms_sidebar.py` and `comms_menu.py` to use it.

### The transcript's lifecycle is explicit

```python
class TranscriptState(LifecycleState): ...

class Detached(TranscriptState): ...
class Live(TranscriptState):
    def accepts_publication(self) -> bool: return True
class Pruning(TranscriptState): ...
class Closing(TranscriptState): ...
```

- Each decision asks the current state (`self.state.accepts_publication()`), so the flags and the chains that recombine them are deleted.
- The filter overlay is a component with its own state (`NoFilter`, `Filtered(source, has_older)`), not four fields on the widget.
- Transcript events own `merge(other) -> TranscriptEvent | None`, so the type comparisons go.

### The goal display is one state

`NoGoal`, `ShowingGoal(goal)`, `GoalUnavailable`: each owns whether it displays and what it shows, decoded from T2's `GoalChanged` record. The illegal fourth combination cannot be constructed.

### The rest

- Delivery errors come from T2's `DeliveryFailure` family, which owns its message; `submit_input`'s type switch is deleted.
- The two sidebars are queried by widget class (`query_one(ChannelsSidebar)`), which Textual supports, so the identifier literals are deleted.

---

## Crossings

T2 lands first (this surface consumes its records), and T6 (step 2) builds `ConversationKind`, which the rows adopt. T3 runs in parallel and owns the `ThreadAction` family; T5 adopts it in its own widgets. T4 runs after both, against classes this surface has already shrunk.

## Guards

In `src/toad/`: no `kind: str` for rows or targets; no comparison of a row kind; no `("channel", "irc")` literal; no `_closing`, `_pruning` or `_committed` flags in `TranscriptHistory`; no `unavailable` flag beside an optional goal; no sidebar identifier literals.

## Tests

- **One family test:** each row kind activates, offers its menu actions and produces its target.
- **One state test:** each transcript state's permissions, and each goal display state's presentation.
- **One new-case test:** a test-only row kind works with one class.
- **Delete** tests of the flag combinations and the kind dispatch.

## New-case experiment

**A new kind of sidebar row.** *Today:* a string at construction, an arm in `on_click`, an arm in the context menu, perhaps an entry in some of the four literal pairs, and a case in `NavigationTarget.decode`: about five places. *After:* one class, plus `ChannelLike` if it behaves as a channel.

## Done when

Rows, row actions, transcript lifecycle and goal display are families and states owning their behaviour; the guards pass; the three classes have shed the logic that moved into them.

## Dispatch

> **`toad-t5`:** Complete T5 per `docs/refactor/T5-comms-interface.md`. Read `00-RULES.md` first. Start after T2 merges; adopt T3's `ThreadAction` family in `comms_sidebar.py` and `comms_menu.py`. `NavigationTarget` is yours (reassigned from T6). Replace the transcript's flags with explicit states before touching its chains: the chains disappear with the flags.
