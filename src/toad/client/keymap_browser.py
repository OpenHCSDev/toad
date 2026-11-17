"""Toolkit-neutral UX state for the keymap browser.

Both Textual's `KeymapScreen` and Qt's `QtKeymapScreen` render this state; the
filter/select/apply/reset LOGIC lives here once. Per-frontend code only decides
how to lay the rows out and route widget events. No per-frontend branching on
what-does-a-row-mean / which-rows-are-visible / how-does-save-work.

Shape:
  - `KeymapBrowserState(app, focused_ids)` captures the catalog + modes + filter.
  - `set_search(term)` / `set_focus_filter(on)` mutate the filter, then the
    frontend re-asks `rows()`.
  - `rows()` yields `KeymapRow` views (title + per-mode cell tuples) that any
    table widget can render.
  - `select(row_index, column_index)` returns a `KeymapSelection | None`.
  - `summary(selection)` / `current_keys(selection)` / `conflicts(selection)`
    answer the per-selection display fields.
  - `apply_keys(selection, keys)` / `reset_keys(selection)` return `KeymapApply`
    outcomes (`KeymapApplied` / `KeymapRefused`); the frontend renders them.

Previously the whole thing lived inside `src/toad/screens/keymap.py`
(`KeymapScreen`), so Qt had no way to show the same UI; wiring was through
Textual widget queries (`query_ancestor`, `query_one(KeymapKeys)`).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from toad.key_modes import KeyMode
from toad.keymap import (
    KeyInvocationId,
    Keymap,
    KeymapCatalog,
    KeymapRefused,
    KeymapRow as KeymapCatalogRow,
    discover,
)
from toad.preferences import SETTINGS
from toad.setting_declarations import FamilyChoices

if TYPE_CHECKING:
    from toad.client.application import ClientApplication


@dataclass(frozen=True)
class KeymapCell:
    """One cell in the keymap table — the current keys bound for a (declaration,
    mode) pair plus whether that row participates in a conflict in that mode."""

    keys: str
    conflict: bool


@dataclass(frozen=True)
class KeymapRow:
    """One row in the keymap table — the action's title and one cell per mode.

    `dim` is True when the action is not visible for the current focus filter
    (used to render the title greyed-out when focus filter is OFF — it stays
    greyed to hint it would be hidden with the filter back on)."""

    title: str
    dim: bool
    cells: tuple[KeymapCell, ...]


@dataclass(frozen=True)
class KeymapSelection:
    """The cell the frontend's cursor is on. Both the declaration (which action)
    and the mode (which column) are needed; a title column alone has no mode."""

    declaration: KeyInvocationId
    mode: type[KeyMode]

    @property
    def catalog_row(self) -> KeymapCatalogRow:
        return KeymapCatalogRow(self.declaration, self.mode)


class KeymapResult:
    """Base for save outcomes — polymorphic so frontends never `isinstance` on it.

    `status_text()` returns what the status line should show (empty string if
    the frontend owns a different mechanism). `should_repopulate()` returns
    whether the table should re-read rows (true after a successful save,
    false after a refusal since nothing changed)."""

    def status_text(self) -> str:
        raise NotImplementedError

    def should_repopulate(self) -> bool:
        raise NotImplementedError


@dataclass(frozen=True)
class KeymapApplied(KeymapResult):
    """A save succeeded; `unsaved` tells whether more edits are still pending
    to disk ("Not saved" status) vs flushed ("Saved")."""

    unsaved: bool

    def status_text(self) -> str:
        return "Not saved" if self.unsaved else "Saved"

    def should_repopulate(self) -> bool:
        return True


@dataclass(frozen=True)
class KeymapRefusedResult(KeymapResult):
    """A save was refused by `Keymap.changed` / `Keymap.reset` (invalid keys,
    conflict with reserved sequence). The message is what the frontend shows."""

    message: str

    def status_text(self) -> str:
        return self.message

    def should_repopulate(self) -> bool:
        return False


class KeymapBrowserState:
    """UX state for the keymap browser. Instantiated once per browser-open."""

    def __init__(self, app: "ClientApplication", focused_ids: frozenset[KeyInvocationId]) -> None:
        discover()
        self.app = app
        self.focused_ids = focused_ids
        self.mode_choices = FamilyChoices(KeyMode)
        self.modes: tuple[type[KeyMode], ...] = self.mode_choices.choices()
        self.catalog = KeymapCatalog.capture(self.modes)
        self.declarations: tuple[KeyInvocationId, ...] = tuple(
            reference for reference, invocation in self.catalog.invocations.items()
            if not invocation.key_system()
        )
        self.visible_declarations: tuple[KeyInvocationId, ...] = self.declarations
        self._search_term: str = ""
        self._focus_filter: bool = True

    # ---- display ----

    def mode_labels(self) -> tuple[str, ...]:
        return tuple(self.mode_choices.label(mode) for mode in self.modes)

    # ---- filter mutation ----

    def set_search(self, term: str) -> None:
        self._search_term = term
        self._recompute_visible()

    def set_focus_filter(self, on: bool) -> None:
        self._focus_filter = on
        self._recompute_visible()

    def _recompute_visible(self) -> None:
        term = self._search_term
        focused_only = self._focus_filter
        self.visible_declarations = tuple(
            declaration for declaration in self.declarations
            if (not focused_only
                or self.catalog.require(declaration).visible_for_focus(declaration in self.focused_ids))
            and term.casefold() in (self.catalog.require(declaration).key_title() + " "
                                    + self.catalog.require(declaration).key_summary()).casefold()
        )

    # ---- row views ----

    def rows(self) -> tuple[KeymapRow, ...]:
        keymap = self.app.settings.ui.keymap
        conflicts = {
            row.binding_id
            for mode in self.modes
            for conflict in keymap.conflicts(mode)
            for row in (conflict.first, conflict.second)
        }
        return tuple(
            KeymapRow(
                title=self.catalog.require(declaration).key_title(),
                dim=not self.catalog.require(declaration).visible_for_focus(
                    declaration in self.focused_ids),
                cells=tuple(
                    KeymapCell(
                        keys=", ".join(self.catalog.effective(row, keymap)) or "—",
                        conflict=row.binding_id in conflicts,
                    )
                    for mode in self.modes
                    for row in (KeymapCatalogRow(declaration, mode),)
                ),
            )
            for declaration in self.visible_declarations
        )

    # ---- selection / per-cell display ----

    def select(self, row_index: int, column_index: int) -> KeymapSelection | None:
        """`row_index` indexes `visible_declarations`; `column_index` 0 is the
        title (no selection), 1..len(modes) are modes."""
        if column_index <= 0 or row_index >= len(self.visible_declarations):
            return None
        declaration = self.visible_declarations[row_index]
        mode = self.modes[column_index - 1]
        selection = KeymapSelection(declaration, mode)
        if not self.catalog.defaults(selection.catalog_row):
            return None
        return selection

    def summary(self, selection: KeymapSelection) -> str:
        return self.catalog.require(selection.declaration).key_summary()

    def current_keys(self, selection: KeymapSelection) -> str:
        return ", ".join(
            self.catalog.effective(selection.catalog_row, self.app.settings.ui.keymap))

    def conflicts(self, selection: KeymapSelection) -> tuple[str, ...]:
        row = selection.catalog_row
        return tuple(
            str(conflict) for conflict in self.app.settings.ui.keymap.conflicts(selection.mode)
            if row in (conflict.first, conflict.second)
        )

    # ---- save ----

    async def apply_keys(self, selection: KeymapSelection, keys: str) -> KeymapResult:
        row = selection.catalog_row
        normalized, = self.app._normalize_keymap({row.binding_id: keys}).values()
        return await self._save(
            partial(Keymap.changed, row=row,
                    keys=tuple(key for key in normalized.split(",") if key)))

    async def reset_keys(self, selection: KeymapSelection) -> KeymapResult:
        return await self._save(partial(Keymap.reset, row=selection.catalog_row))

    async def _save(self, edit) -> KeymapResult:
        try:
            keymap = edit(self.app.settings.ui.keymap)
        except KeymapRefused as error:
            return KeymapRefusedResult(message=str(error))
        self.app.saved_settings.set(SETTINGS.ui.keymap.bindings, keymap.bindings)
        await self.app.saved_settings.save()
        self._recompute_visible()
        return KeymapApplied(unsaved=self.app.saved_settings.unsaved)
