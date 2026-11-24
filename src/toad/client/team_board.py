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
from agent_comms.team.team_hud import TeamBoardCut, TeamBoardSelection, TeamHud
from agent_comms.team.team_hud_records import HudRecord, HudSection
from agent_comms.ui_model.hud_groups import HudGroup


@dataclass
class TeamBoardState:
    """Toolkit-neutral owner of the selected live board value."""

    team_name_filter: str = ""
    huds: tuple[TeamHud, ...] = ()
    last_error: Exception | None = None
    _observers: list[Callable[[TeamBoardCut | None], None]] = field(default_factory=list)

    @property
    def selection(self) -> TeamBoardSelection:
        return TeamBoardSelection.named(self.team_name_filter)

    def observe(self, callback: Callable[[TeamBoardCut | None], None]) -> None:
        self._observers.append(callback)

    def apply_update(self, cut: TeamBoardCut) -> TeamBoardCut:
        selection = self.selection
        selected = TeamBoardCut(
            tuple(hud for hud in cut.huds if selection.includes(hud.teammate)),
            frozenset(owner for owner in cut.changed if selection.includes(owner)),
        )
        self.huds = selected.huds
        self.last_error = None
        self._notify(selected)
        return selected

    def apply_hud_failure(self, error: Exception) -> None:
        self.last_error = error
        self._notify(None)

    def filter_hud_sections(self, hud: TeamHud, text: str,
                            needs_hand_only: bool) -> dict[type[HudGroup], HudSection]:
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

    def _notify(self, cut: TeamBoardCut | None) -> None:
        for observer in self._observers:
            observer(cut)


class TeamMemberBoard:
    """Shared per-teammate board view state inherited by Textual's `TeamFrameView` and Qt's
    `QtTeamMemberView`."""

    state: TeamBoardState
    hud: TeamHud

    def filtered_sections_for(self, text: str, needs_hand_only: bool) -> dict[type[HudGroup], HudSection]:
        return self.state.filter_hud_sections(self.hud, text, needs_hand_only)
