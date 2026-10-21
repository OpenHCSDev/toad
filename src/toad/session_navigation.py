"""Opening and closing sessions use the existing workspace's declared factories."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import partial
from itertools import count
from pathlib import Path
from typing import TYPE_CHECKING, cast

from agent_comms.errors import (
    RelationViolationError,
    RouteChangedError,
    UnknownChannelError,
    UnregisteredThreadError,
)
from agent_comms.presentation import NoRevision, ReadState
from agent_comms.revision_views import RegistrationsView
from agent_comms.route_selection import root_is_current
from agent_comms.thread_identity import ThreadIncarnation

from toad.core import events as core_events
from toad.core.events import CoreEventStream
from toad.navigation_preparation import CommsNavigationRequest
from toad.session_entry import (
    HistorySessionEntry,
    NativeSessionEntry,
    PreviewSessionEntry,
    SessionEntry,
)
from toad.session_scope import AgentAttached, AgentBinding, AgentSession
from toad.session_tracker import OpenTab, SessionDetails

if TYPE_CHECKING:
    from agent_comms.ui_model.sidebar import ThreadRowModel

    from toad.agent_schema import AgentDefinition
    from toad.app import ToadApp
    from toad.navigation_target import HistoryRouted
    from toad.screens.main import MainScreen


class SessionNavigation:
    def __init__(self, app: ToadApp) -> None:
        self.app = app
        self.events = CoreEventStream(self)
        self.identities = count(1)
        self.entries: dict[str, dict[str, SessionEntry]] = {}
        self._retire_task: asyncio.Task[None] | None = None
        self._retire_requested = False
        # The Core revision the last retirement pass started from.
        self._retired_at: ReadState = NoRevision()
        self._closing_retired: set[asyncio.Future] = set()

    def direct_messages(self, target: str | None = None):
        """Capture the original view once; all DM entry points require it."""
        from toad.navigation_target import DirectTarget

        source = self.app.selected_session
        if source is None:
            raise ValueError("Direct messages require an open session")
        operation = (
            source.open_direct_messages()
            if target is None
            else source.open_sidebar_target(DirectTarget(target))
        )
        return self.app.run_worker(operation, group="direct-messages")

    def bind_events(self) -> None:
        self.app.subscribe_core(self.events)
        self.app.observe_core_callback(
            self.app.coordination_access.events,
            core_events.CoordinationObserved,
            self.observed,
        )

    async def reveal(self) -> None:
        from toad.widgets.comms_sidebar import CommsSidebar
        from toad.widgets.side_bar import SideBar, SideBarCollapsible

        app = self.app
        sidebar = app.screen.query_one_optional(CommsSidebar)
        if sidebar is None:
            sessions = app.session_tracker.ordered_sessions
            if not sessions:
                app.notify("No sessions are open", title="Sessions")
                return
            await app.select_session(sessions[-1].mode_name)
            sidebar = app.screen.query_one_optional(CommsSidebar)
        if sidebar is not None:
            sidebar.query_ancestor(SideBar).reveal()
            sidebar.query_ancestor(SideBarCollapsible).collapsed = False
            await sidebar.navigation.focus_current()

    @property
    def members(self) -> tuple[SessionEntry, ...]:
        return tuple(
            entry for group in self.entries.values() for entry in group.values()
        )

    @property
    def processes(self):
        """Borrow connections from actual native sources; keep no second roster."""
        return tuple(
            process
            for member in self.members
            if (source := member.source(self)) is not None
            for process in source.presentation.operational_binding.borrowed_processes()
        )

    def get(self, mode: str) -> SessionEntry | None:
        return next(
            (group[mode] for group in self.entries.values() if mode in group), None
        )

    def find(self, address: object) -> SessionEntry | None:
        return next((entry for entry in self.members if entry.address == address), None)

    def source(self, mode: str) -> MainScreen | None:
        entry = self.get(mode)
        return entry.source(self) if entry else None

    def thread_row(self, row: ThreadRowModel) -> ThreadRowModel:
        """A thread's row as this app shows it, with the state of each open session of it."""
        for entry in self.members:
            row = entry.thread_row(self, row)
        return row

    async def reconnect(self, selected, targets: tuple[str, ...]) -> None:
        if not targets:
            return
        originals = self.members
        snapshot = await self.app.preparation.run_thread(
            lambda: self.app.coordination_access.require(
                selected
            ).service.registry.snapshot()
        )
        for member in originals:
            await member.reconnect(self, selected, snapshot, targets)

    def bind_opened(
        self,
        view: MainScreen,
        *,
        original: tuple[str, ThreadIncarnation],
        name: str,
        project: Path,
    ) -> None:
        """Bind the accepted source facts before preparing its native resources."""
        entry = cast(NativeSessionEntry, self.get(view.id))
        view.bind_project(project)
        root, owner = original
        view.bind_thread(owner, root)
        entry.details.bind_initial_identity(name)
        self.publish()

    def publish(self) -> None:
        self.app.events.publish(core_events.OpenTabsChanged())
        self.app.update_show_sessions()

    def views_retired(self, root, retired) -> None:
        """Close the open views on ``root`` whose sources the observation service found retired."""
        root = str(root)
        removed = tuple(
            member.mode
            for member in self.members
            if (
                any(
                    owner == root and identity in retired.threads
                    for owner, identity in member.original_threads(self)
                )
                or any(
                    owner == root and target in retired.channels
                    for owner, target in member.original_channels()
                )
            )
        )
        if removed:
            task = asyncio.ensure_future(self.close_many(removed))
            self._closing_retired.add(task)
            task.add_done_callback(self._closing_retired.discard)

    async def open(self, entry: SessionEntry, *, after: str | None = None) -> str:
        app = self.app
        if self.get(entry.mode) is not None:
            raise ValueError(f"Logical session already registered: {entry.mode}")
        self.entries.setdefault(entry.owner_mode, {})[entry.mode] = entry
        app.tab_order.open(entry.mode, after=after)
        self.publish()
        await app.select_session(entry.mode)
        await entry.ready(self)
        return entry.mode

    async def new(
        self,
        factory: Callable[[], MainScreen],
        *,
        title: str = "New Session",
        original=None,
    ) -> SessionDetails:
        details = self.app.session_tracker.new_session(title=title)
        await self.open(NativeSessionEntry(details, factory, original))
        return details

    async def launch(
        self,
        agent_identity: str,
        *,
        agent_session_id: str | None = None,
        session_pk: int | None = None,
        project_path: Path | None = None,
        initial_prompt: str | None = None,
    ) -> None:
        from toad.agents import read_agents
        from toad.db import DB
        from toad.screens.main import MainScreen

        app = self.app
        make_binding: Callable[[AgentDefinition], AgentBinding] = AgentAttached
        if agent_session_id is not None:
            make_binding = partial(AgentSession, session_id=agent_session_id)
            existing = next(
                (
                    identity
                    for identity, origin in app.workspace_sessions.native_origins.items()
                    if origin.matches_launch(agent_identity, agent_session_id)
                ),
                None,
            )
            if existing is not None:
                await app.select_session(existing)
                return
        agent, title = None, None
        if session_pk is not None:
            saved = await DB().session_get(session_pk)
            if saved is not None:
                title, agent = saved.title, saved.meta_json.agent_data
        if agent is None:
            agents = await read_agents()
            try:
                agent = agents[agent_identity]
            except KeyError:
                app.show_error("Agent not found", "Launch agent")
                return
        project = project_path if project_path is not None else app.project_dir
        await self.new(
            lambda: MainScreen(
                project,
                make_binding(agent),
                session_pk=session_pk,
                initial_prompt=initial_prompt,
            ),
            title=title or "New Session",
        )

    async def history(
        self,
        *,
        owner_mode: str,
        project_path: Path,
        me: str,
        route: HistoryRouted,
    ) -> str:
        from toad.thread_navigation import ThreadOrigin

        app = self.app
        try:
            source = app.workspace_sessions.origin(owner_mode).require()
        except RelationViolationError:
            app.show_error(
                "The owning agent tab was closed", "Comms target unavailable"
            )
            return app.selected_mode
        origin = ThreadOrigin.capture(app, source)
        try:
            comms = await app.preparation.run_thread(
                lambda: app.coordination_access.observation.observed().service
            )
            requested_root = str(comms.root)
            if not origin.current(app.thread_navigation, owner_mode):
                return app.selected_mode
            prepared = await app.navigation_reader.read(
                CommsNavigationRequest(
                    comms, owner_mode, me, route, source.coordination_root
                )
            )
        except (UnknownChannelError, UnregisteredThreadError, RouteChangedError) as error:
            app.show_error(error, "Comms target unavailable")
            return app.selected_mode
        if prepared is None:
            return app.selected_mode
        if not origin.current(app.thread_navigation, owner_mode):
            return app.selected_mode
        if not await app.preparation.run_thread(root_is_current, requested_root):
            return app.selected_mode
        if not origin.current(app.thread_navigation, owner_mode):
            return app.selected_mode
        # The history entry is the only owner of this typed key. Workspace
        # factories carry its identity, so no key-to-mode mirror can go stale.
        entry = self.find(prepared.key.conversation.view_identity(prepared.key))
        if entry is None:
            entry = HistorySessionEntry(
                f"comms-{next(self.identities)}",
                prepared.key,
                project_path,
                prepared.owner_root,
                prepared.participants,
                source,
            )
            await self.open(entry)
        else:
            await app.select_session(entry.mode)
            await entry.ready(self)
        return entry.mode

    async def preview(self, path: Path, *, position=None) -> str:
        path = path.expanduser().resolve()
        entry = self.find(path)
        if entry is None:
            entry = PreviewSessionEntry.of(
                f"preview-{next(self.identities)}", path, self.app.selected_mode
            )
            await self.open(entry, after=self.app.selected_mode)
        else:
            await self.app.select_session(entry.mode)
        if position is not None:
            view = self.app.workspace_sessions.views[entry.mode]
            await view.preview.reveal(position)
        return entry.mode

    def entered(self, mode: str, previous: str) -> None:
        if entry := self.get(mode):
            entry.entered(previous)

    async def return_from(self, mode: str) -> None:
        if entry := self.get(mode):
            await entry.return_to(self)

    @property
    def tabs(self) -> tuple[OpenTab, ...]:
        observed = self.app.coordination_access.observation
        return self.app.tab_order.project(observed.tabs(self))

    def sync_owner_root(self, owner: str, root: str | None) -> None:
        for entry in self.entries.get(owner, {}).values():
            entry.sync_owner_root(self, owner, root)

    def sync_project(self, owner: str, project: Path) -> None:
        for entry in self.entries.get(owner, {}).values():
            entry.sync_project(self, owner, project)

    async def close(self, mode: str) -> None:
        await self.close_many((mode,))

    async def close_many(self, modes: tuple[str, ...]) -> None:
        entries = tuple(
            entry for mode in modes if (entry := self.get(mode)) is not None
        )
        if not entries:
            return
        closing = tuple(
            member
            for member in self.members
            if any(member.depends_on(entry.mode) for entry in entries)
        )
        returning = next(
            (member for member in closing if member.mode == self.app.selected_mode),
            None,
        )
        for member in closing:
            member.forget(self)
        self.app.tab_order.close({member.mode for member in closing})
        # Retire membership before publication and slow widget exits. Delayed
        # opening metadata cannot revive a closed owner during teardown.
        for member in closing:
            group = self.entries[member.owner_mode]
            del group[member.mode]
            if not group:
                del self.entries[member.owner_mode]
        self.publish()
        try:
            # Closed entries cannot reopen. Show the surviving workspace
            # before joining hydration, native sessions and widget removal.
            if returning is not None:
                await returning.return_to(self)
        finally:
            for member in closing:
                await self.app.workspace_sessions.close(member.mode)

    def observed(self, event: core_events.CoordinationObserved) -> None:
        # Views on the observed root retire through the observation service
        # (views_retired). Views on another root are read here, only when a
        # registration or channel changed.
        observed = self.app.coordination_access.observation.observed()
        if not any(
            not observed.observes(owner)
            for member in self.members
            for owner, _ in (
                *member.original_threads(self),
                *member.original_channels(),
            )
        ):
            return
        revision = event.revision
        if not revision.changed_since(RegistrationsView(), self._retired_at):
            return
        self._retired_at = revision
        # The registry read takes hundreds of milliseconds; awaiting it here held
        # every input queued behind the App's message pump. One pass runs at a
        # time and observations arriving during it fold into one more pass.
        self._retire_requested = True
        if self._retire_task is None or self._retire_task.done():
            self._retire_task = asyncio.create_task(self._retire_requested_views())

    async def _retire_requested_views(self) -> None:
        while self._retire_requested:
            self._retire_requested = False
            await self.retire_missing()

    async def retire_missing(self) -> None:
        from agent_comms.route_selection import RouteSelection

        # Borrow each open entry, including hidden views. Core decides
        # which of their sources no longer exist; Toad only closes the views.
        originals = tuple(
            (member, member.original_threads(self), member.original_channels())
            for member in self.members
        )
        asked: dict[str, tuple[set, set]] = {}
        # The observation service retires views on its own root.
        observed = self.app.coordination_access.observation.observed()
        for _member, threads, channels in originals:
            for root, identity in threads:
                if not observed.observes(root):
                    asked.setdefault(root, (set(), set()))[0].add(identity)
            for root, target in channels:
                if not observed.observes(root):
                    asked.setdefault(root, (set(), set()))[1].add(target)
        if not asked:
            return

        def read():
            answers = {}
            for root, (threads, channels) in asked.items():
                try:
                    selected = RouteSelection.capture(root)
                    service = self.app.coordination_access.require(selected).service
                    retired = service.views.retired_views(threads, channels)
                    if RouteSelection.capture(root) != selected:
                        continue  # Replaced while reading; the next observation reads it.
                except RouteChangedError:
                    continue  # The next observation reads the replacement route.
                answers[root] = service, retired
            return answers

        answers = await self.app.preparation.run_thread(read)
        # A service replaced while the read joined revokes its answer.
        observed = self.app.coordination_access.observation.observed()
        retired = {
            root: answer
            for root, (service, answer) in answers.items()
            if observed.uses(service)
        }
        removed = tuple(
            member.mode
            for member, threads, channels in originals
            if self.get(member.mode) is member
            and (
                any(
                    root in retired and identity in retired[root].threads
                    for root, identity in threads
                )
                or any(
                    root in retired and target in retired[root].channels
                    for root, target in channels
                )
            )
        )
        await self.close_many(removed)
