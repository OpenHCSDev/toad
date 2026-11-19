"""Toolkit-neutral owner for the live team-board view.

Both frontends (Textual's `TeamPage` and Qt's `QtTeamBoardScreen`) hold one
`TeamBoardState` and route their Core events through it instead of filtering
and projecting huds in each widget's own handler. The state owns:

- `team_name_filter` — optional single-teammate filter
- `huds` — the latest frame after the filter
- `last_error` — the last `TeamHudFailed` if present
- `filter_hud_sections(hud, text, needs_hand_only)` — the per-member
  filtering (free-text match + needs-hand gate) that Textual's
  `TeamFrameView.filtered_sections` previously held

Writes go through `apply_hud_change` / `apply_hud_failure`; observers
subscribed via `observe` are notified after each transition.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from agent_comms.task_attachments.disclosure_text import ViewTable
from agent_comms.team.team_hud import TeamBoardSelection, TeamHud
from agent_comms.team.team_hud_records import HudRecord, HudSection
from agent_comms.ui_model.hud_groups import HudGroup


@dataclass
class TeamBoardState:
    """Shared owner of the live team heartbeat view.

    `team_name_filter` is the optional single-teammate restriction passed at
    screen open (empty = show all). The state is updated in-place through
    `apply_hud_change` / `apply_hud_failure`, which the frontend's own Core
    subscription routes to; observers added via `observe` fire after each
    transition so the widget can re-render.
    """

    team_name_filter: str = ""
    huds: tuple[TeamHud, ...] = ()
    last_error: Exception | None = None
    _observers: list[Callable[[], None]] = field(default_factory=list)

    @property
    def selection(self) -> TeamBoardSelection:
        """Carry the page's user filter into Core's recipient-selection contract."""
        return TeamBoardSelection.named(self.team_name_filter)

    def observe(self, callback: Callable[[], None]) -> None:
        """Register a callback fired after each state transition."""
        self._observers.append(callback)

    def apply_hud_change(self, huds: tuple[TeamHud, ...]) -> None:
        """Replace the current frame, filtered by `team_name_filter`, clearing
        any prior error."""
        selection = self.selection
        self.huds = tuple(hud for hud in huds if selection.includes(hud.teammate))
        self.last_error = None
        self._notify()

    def apply_hud_failure(self, error: Exception) -> None:
        """Record that the latest frame failed to arrive; the frontend shows
        the error and keeps the last good `huds`."""
        self.last_error = error
        self._notify()

    def filter_hud_sections(self, hud: TeamHud, text: str,
                            needs_hand_only: bool) -> dict[type[HudGroup], HudSection]:
        """The per-member filter Textual's `TeamFrameView.filtered_sections`
        previously held, hoisted so Qt applies the same gates.

        For each `HudSection` in `hud.groups`, keep only the records whose row
        text contains `text` (case-insensitive) and — when `needs_hand_only`
        is True — whose `.needs_hand()` is true."""
        folded = text.casefold()
        shown: dict[type[HudGroup], HudSection] = {}
        for section in hud.groups:
            tables: list[ViewTable[HudRecord]] = []
            for table in section.tables:
                records = tuple(record for record, cells in zip(table.records, table.texts)
                                if (not needs_hand_only or record.needs_hand())
                                and folded in "\n".join(cells).casefold())
                tables.append(table if records == table.records else replace(table, records=records))
            shown[section.group] = HudSection(section.group, tuple(tables))
        return shown

    def _notify(self) -> None:
        for obs in self._observers:
            obs()
