"""Toolkit-neutral per-session UI state the thread-comms sidebar keeps between view binds.

Both Textual's `ThreadCommsSidebar` and Qt's `QtThreadCommsPanel` keep this across tab
switches so a conversation reopens with its last-selected row and its group-expansion state,
rather than resetting each time.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from toad.client.panel_source import PanelSource
from toad.client.relationship_row_menu import entry_target


@dataclass
class RelationshipTreeState:
    expanded: dict[type, bool] = field(default_factory=dict)
    selected: tuple[type, tuple[str, str]] | None = None
    selected_targets: tuple[tuple[type, tuple[str, str]], ...] = ()


class RelationshipPanel(PanelSource):
    """The thread sidebar's Comms panel as both frontends hold it: Textual's
    `ThreadCommsSidebar` and Qt's `QtThreadCommsPanel` inherit this. It keeps each thread's
    tree state across binds, says whose relationships these are, re-reads relationships before
    opening a row, and warns on a stale entry or wrong bus."""

    wrong_bus_warning = "This view is on a different bus — switch to that bus to open it."
    changed_entry_warning = "This item changed — refreshed the list."

    _states: dict

    @property
    def view_state(self) -> RelationshipTreeState:
        return self._states.setdefault(self.thread_identity, RelationshipTreeState())

    @staticmethod
    def context_title(snapshot) -> str:
        return f"For @{snapshot.owner}"

    @staticmethod
    def context_note(snapshot) -> str:
        return " · recent window" if snapshot.history_limited else ""

    @staticmethod
    def context_tooltip(snapshot) -> str:
        return f"{snapshot.incoming_basis}\nLatest {snapshot.history_messages} messages"

    def notify_comms_warning(self, message: str) -> None:
        raise NotImplementedError

    def refresh_after_changed_entry(self) -> None:
        raise NotImplementedError

    def select_relationship_target(self, target) -> None:
        raise NotImplementedError

    def open_relationship_target(self, access, target) -> None:
        if not self.thread_identity.belongs_to_wire(access.observation.observed().root):
            self.notify_comms_warning(self.wrong_bus_warning)
            return
        self.select_relationship_target(target)

    async def open_current_relationship(
        self,
        access,
        preparation,
        group,
        entry,
        *,
        still_current: Callable[[], bool] | None = None,
    ) -> None:
        """Open the relationship as it stands now: the list read again, and a relationship
        that changed since it was drawn is not opened."""
        if not entry.available:
            return
        is_current = (lambda: True) if still_current is None else still_current

        async def _open(identity) -> None:
            if not is_current():
                return
            service = await self.observed_source(access, preparation, identity.root_path)
            if service is None or not is_current():
                return
            snapshot = await preparation.run_thread(
                service.relationships, identity.thread_name()
            )
            if not is_current():
                return
            current = snapshot.current_entry(group, entry)
            if current is None:
                self.notify_comms_warning(self.changed_entry_warning)
                self.refresh_after_changed_entry()
                return
            self.open_relationship_target(access, entry_target(current))

        await self.thread_identity.inspect_owner(_open, lambda _text: None)
