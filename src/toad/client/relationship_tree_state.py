"""Toolkit-neutral per-session UI state the thread-comms sidebar keeps between view binds.

Both Textual's `ThreadCommsSidebar` and Qt's `QtThreadCommsPanel` keep this across tab
switches so a conversation reopens with its last-selected row and its group-expansion state,
rather than resetting each time.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from toad.client.panel_source import PanelSource


@dataclass
class RelationshipTreeState:
    expanded: dict[type, bool] = field(default_factory=dict)
    selected: tuple[type, tuple[str, str]] | None = None
    selected_targets: tuple[tuple[type, tuple[str, str]], ...] = ()


class RelationshipPanel(PanelSource):
    """The thread sidebar's Comms panel as both frontends hold it: Textual's
    `ThreadCommsSidebar` and Qt's `QtThreadCommsPanel` inherit this. It keeps each thread's
    tree state across binds, says whose relationships these are, and decides which entries
    the sidebar's search keeps."""

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
        return f"{snapshot.incoming_basis}\nLatest {snapshot.history_messages} wire messages"
