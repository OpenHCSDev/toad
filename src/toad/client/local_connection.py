"""Core in this process: this machine's own bus, opened from the launch root.

A launch that may select the local route chooses its connection here (`select_connection`):
the TUI's, and desktop Qt's entry (`toad.qt.main`) once its first frame is up. It is the one
connection agent processes start under (`agent_processes`). The Qt client's shared modules
never import it, and Android's start, always remote (``RemoteCoreConnection``), never loads it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar
from pathlib import Path

from agent_comms.comms import Comms
from agent_comms.errors import RouteChangedError
from agent_comms.execution.launch_root import LaunchRoot
from agent_comms.execution.launch_runtime import LaunchRuntime
from agent_comms.execution.root_runtime import RootRuntime
from agent_comms.installer.active_route import CommsRoute
from agent_comms.installer.route_selection import RouteSelection
from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.threads import Thread
from agent_comms.transport.core_access import LocalCoreAccess
from agent_comms.transport.request import CoreAccess
from agent_comms.ui_model.observation import (
    LocalRouteObservation,
    ObservationProcess,
    ObservationSource,
)
from agent_comms.ui_model.sidebar import SidebarModel

from toad.client.agent_processes import AgentProcesses, SpawnsAgentProcesses
from toad.client.db import UNSCOPED_TABS, TabScope
from toad.client.connection import (
    AnsweringReads,
    CoordinationAccess,
    CoreConnection,
    FailedObservation,
    Observing,
    ProcessRemoteCoreConnection,
    RemoteCoreConnection,
    SelectedRoute,
    UnselectedRoute,
)


def select_connection(arguments: list[str]) -> CoreConnection:
    """The connection launch ``arguments`` name: a UI profile selects the remote Core.

    A launch reads its own arguments here, and a running app reads a chosen bus's here
    too, so one parser decides which Core both open. A frontend-only install has no
    published agent runtime yet: the route owner supplies its normal local default when
    absent, while a broken route still refuses.
    """
    if RemoteCoreConnection.argument in arguments:
        return ProcessRemoteCoreConnection.startup(arguments)
    return LocalCoreConnection.from_launch(LaunchRoot.startup(
        arguments, lambda: LaunchRoot.from_path(CommsRoute.current().root)))


class LocalCoreConnection(LaunchRoot, CoreConnection):
    """A local connection inherits the selected root and its launch behavior."""

    agent_processes: ClassVar[AgentProcesses] = SpawnsAgentProcesses()

    @classmethod
    def from_launch(cls, root: LaunchRoot) -> LocalCoreConnection:
        return cls(root.path)

    @property
    def location(self) -> str:
        return str(self.path)

    def tab_scopes(self) -> tuple[TabScope, ...]:
        """Tabs saved before scopes existed were local sessions' tabs; this Core reads them as
        its own and rewrites them under its location."""
        return (*super().tab_scopes(), UNSCOPED_TABS)

    def route_selection(self) -> RouteSelection:
        return RouteSelection.of(self)

    def observation_source(self, route: CommsRoute) -> ObservationSource:
        """A local route is observed in a process this machine starts for it."""
        return LocalRouteObservation(route, self.helper_start)

    def capture(self, access: CoordinationAccess, source: str | Path) -> SelectedRoute:
        return SelectedRoute(self.route_selection().require_source(source))

    def holds(self, access: CoordinationAccess, source: str | Path) -> bool:
        """The held launch route's root."""
        return self.route_selection().root_is_current(source)

    def observing(self, access: CoordinationAccess, source: str | Path) -> Observing:
        """Select this app's route for ``source`` and open its observation."""
        return access.require(self.route_selection().require_source(source))

    def open_current(self, access: CoordinationAccess) -> Observing | FailedObservation:
        """Capture the current route and open its service, or expose the opening error."""
        selected: RouteSelection | UnselectedRoute = UnselectedRoute()
        try:
            selected = self.route_selection()
            return access.require(selected)
        except (OSError, ValueError, RuntimeError) as error:
            return access.observation.failed(error, selected)

    def open_selected(self, access: CoordinationAccess, selected: RouteSelection) -> Observing:
        """Open Core in this process for ``selected`` and observe it there."""
        def attach() -> Observing:
            previous = access.observation
            service = Comms(selected.route)
            if service.root.resolve() != selected.root:
                raise RouteChangedError("Comms route changed while opening the service")
            access.confirm_route(selected)
            return previous.adopt(LocalObserving(
                SidebarModel(access.app.schedule_ui), ObservationProcess(self.observation_source(service.route)),
                selection=selected, service=service, access=access))

        return RootRuntime.attachment(selected.root, LaunchRuntime.running()).proceed(
            attach, access.app.succeed_onto,
        )


@dataclass(frozen=True)
class LocalObserving(Observing):
    """Core in this process, opened for one validated route selection."""

    selection: RouteSelection = field(kw_only=True)
    service: Comms = field(kw_only=True)

    @property
    def root(self) -> Path:
        return self.selection.root

    def observes(self, root: str | Path) -> bool:
        return Path(root).expanduser().resolve() == self.root

    def opened_selection(self) -> RouteSelection:
        return self.selection

    def user_identity(self, project: Checkout) -> Thread:
        """In process, the user thread is read, or claimed for this project's checkout."""
        return self.service.messaging.user_identity(project)

    @property
    def core(self) -> CoreAccess:
        return LocalCoreAccess(self.service, self.process)

    def require(self, access: CoordinationAccess, selected: RouteSelection):
        return self if self.selection == selected else access.connection.open_selected(access, selected)


@dataclass(frozen=True)
class LocalAnsweringReads(AnsweringReads, LocalObserving, answers_for=LocalObserving):
    pass
