"""Canonical wire snapshot and current workspace view routes."""
from __future__ import annotations
from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path
from agent_comms.presentation import CoordinationSnapshot, ThreadView

@dataclass(frozen=True)
class SidebarSnapshot:
    wire: CoordinationSnapshot
    session_threads: Mapping[str, str]
    all_people: Mapping[str, ThreadView]

    @classmethod
    def capture(cls, app, comms, state: CoordinationSnapshot) -> SidebarSnapshot:
        all_people = {person.thread.name: person for person in state.threads}
        session_threads: dict[str, str] = {}
        claimed_threads: set[str] = set()
        for details in app.session_tracker.ordered_sessions:
            screen = app.session_navigation.source(details.mode_name)
            if screen is None:
                continue
            if (
                screen.coordination_root is not None
                and Path(screen.coordination_root).expanduser().resolve() != comms.root
            ):
                continue  # A same-named thread on another wire is not this open view.
            name = screen._comms_thread
            if name not in all_people and screen._agent_session_id in all_people:
                name = screen._agent_session_id
            if name in all_people and name not in claimed_threads:
                session_threads[details.mode_name] = name
                claimed_threads.add(name)
        return cls(state, session_threads, all_people)
