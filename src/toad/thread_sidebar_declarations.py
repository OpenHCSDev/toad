"""Toolkit-neutral roster of the panels the thread sidebar shows. Both Textual's
`SessionPanel` family (`widgets/session_thread_panels.py`) and Qt's `ThreadSettingsPane`
(`qt/placement.py`) read from this single declaration, so a new panel added here appears
on both frontends automatically — no hand-rolled mirror, no drift.

Each frontend supplies its own rendering for a given panel key: Textual's subclass links
back here through `spec_key`; Qt looks up the spec by key when composing its sidebar
sections. A Qt rendering is only available for keys whose Qt widget has been ported;
for the rest Qt shows a header + placeholder until the per-panel port follow-up lands.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThreadSidebarPanelSpec:
    """One panel's toolkit-neutral identity. Order in the roster is display order."""

    key: str
    heading: str
    panel_id: str | None = None
    collapsed: bool = False
    flex: bool = False
    # Visibility flags mirror Textual's `ThreadDetailsPanel` marker: a DM / conversation
    # view hides project / plan / context since those belong to a session, not a thread.
    in_dm_view: bool = True
    in_session_view: bool = True


THREAD_SIDEBAR_PANELS: tuple[ThreadSidebarPanelSpec, ...] = (
    ThreadSidebarPanelSpec(key="coordination", heading="Coordination",
                           panel_id="coordination-panel",
                           in_dm_view=True, in_session_view=True),
    ThreadSidebarPanelSpec(key="comms", heading="Comms",
                           in_dm_view=True, in_session_view=True),
    ThreadSidebarPanelSpec(key="plan", heading="Plan",
                           collapsed=True,
                           in_dm_view=False, in_session_view=True),
    ThreadSidebarPanelSpec(key="project", heading="Project",
                           collapsed=True, flex=True,
                           in_dm_view=False, in_session_view=True),
    ThreadSidebarPanelSpec(key="context", heading="Context",
                           in_dm_view=False, in_session_view=True),
)


def panel_specs_for_view(*, is_session: bool) -> tuple[ThreadSidebarPanelSpec, ...]:
    """The subset of the roster visible in a session view (True) or a DM / conversation
    view (False). Keeps the Textual `ThreadDetailsPanel` / `SessionPanel` split in one
    place instead of duplicating the roster."""
    if is_session:
        return tuple(spec for spec in THREAD_SIDEBAR_PANELS if spec.in_session_view)
    return tuple(spec for spec in THREAD_SIDEBAR_PANELS if spec.in_dm_view)


def spec_for(key: str) -> ThreadSidebarPanelSpec:
    for spec in THREAD_SIDEBAR_PANELS:
        if spec.key == key:
            return spec
    raise KeyError(f"No thread sidebar panel declared for key {key!r}")
