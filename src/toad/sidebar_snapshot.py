"""Canonical wire snapshot and current workspace view routes."""
from __future__ import annotations
from dataclasses import dataclass, replace
from collections.abc import Mapping
from typing import TYPE_CHECKING
from pathlib import Path
from agent_comms.presentation import CoordinationSnapshot, ThreadView, WireRevision
from toad.sidebar_preparation import ThreadRowInput, ThreadRowsWork

if TYPE_CHECKING:
    from agent_comms.comms import Comms

@dataclass(frozen=True)
class SidebarSnapshot:
    wire: CoordinationSnapshot
    session_threads: Mapping[str, str]
    all_people: Mapping[str, ThreadView]
    row_inputs: ThreadRowsWork
    revision: WireRevision
    service: Comms
    worktree: Path

    @classmethod
    async def capture(cls, app, comms, state: CoordinationSnapshot,
                      revision: WireRevision) -> SidebarSnapshot:
        all_people = {person.thread.name: person for person in state.threads}
        rows = await ThreadRowsWork.capture(
            app.preparation, tuple(ThreadRowInput(person) for person in all_people.values()))
        return cls(state, {}, all_people, rows, revision, comms, app.project_dir).project(app, comms)

    def matches(self, service: Comms, revision: WireRevision, worktree: Path,
                filters: tuple[bool, bool]) -> bool:
        return (self.service is service and self.revision == revision
                and self.worktree == worktree
                and (self.wire.show_stopped, self.wire.show_archived) == filters)

    def same_rows(self, other: SidebarSnapshot) -> bool:
        """Compare native roster answers, independently of read-cut custody.

        Activity timestamps already determine the acquired member ordering;
        they aren't another row output. Revision and process observations must
        still advance even when their captured presentation is unchanged.
        Targets remain independent of labels: an inactive native owner routes
        to history even when its text happens to match an active owner.
        """
        from toad.navigation_target import person_target

        return (
            self.service is other.service and self.worktree == other.worktree
            and self.session_threads == other.session_threads
            and self.row_inputs == other.row_inputs
            and self.wire.channel_order == other.wire.channel_order
            and self.wire.channel_unread == other.wire.channel_unread
            and self.wire.unread == other.wire.unread
            and self.wire.thread_unread == other.wire.thread_unread
            and self.wire.thread_unread_pending == other.wire.thread_unread_pending
            and (self.wire.show_stopped, self.wire.show_archived)
                == (other.wire.show_stopped, other.wire.show_archived)
            and tuple((view.channel, view.members, view.pinned_members)
                      for view in self.wire.channels)
                == tuple((view.channel, view.members, view.pinned_members)
                         for view in other.wire.channels)
            and tuple(person_target(person) for person in self.all_people.values())
                == tuple(person_target(person) for person in other.all_people.values())
        )

    def project(self, app, comms) -> SidebarSnapshot:
        """Local admissions change routes, not this acquired wire or its paint inputs."""
        if comms is not self.service:
            raise ValueError("Sidebar publication belongs to another acquired service")
        session_threads: dict[str, str] = {}
        claimed_threads: set[str] = set()
        for details in app.session_tracker.ordered_sessions:
            screen = app.session_navigation.source(details.mode_name)
            if screen is None:
                continue
            if not screen.belongs_to_wire(comms.root):
                continue  # A same-named thread on another wire is not this open view.
            name = screen._comms_thread
            if name not in self.all_people and screen._agent_session_id in self.all_people:
                name = screen._agent_session_id
            if name in self.all_people and name not in claimed_threads:
                session_threads[details.mode_name] = name
                claimed_threads.add(name)
        return replace(self, session_threads=session_threads)
