"""An app test's comms observer, forked warm from the test template instead of spawned cold.

The product observes a local route in a spawned process (LocalRouteObservation): a fresh
interpreter that imports the observer's module graph and walks RootFile.load_declarations,
about 3.7 s before the first sidebar answer. The test template has already paid both, so beside
each test it forks an ObserverSpawner that has become that test's process; the test's
connection hands the spawner one end of a socket pair, and the spawner forks the service
(serve_encoded, the same declared wire a connector viewer speaks) from warm memory.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import os
import pickle
import select
import socket
import traceback
from typing import ClassVar

from agent_comms.active_route import CommsRoute
from agent_comms.launch_root import LaunchRoot
from agent_comms.ui_model.observation import (
    ObservationPeer,
    ObservationSource,
    ObserverDied,
    ViewerEnd,
    serve_encoded,
)
from toad.comms_root import CoreConnection, LocalCoreConnection


class ObserverChannel(ABC):
    """How this process's app tests reach an observer: a test forked by the template holds
    the socket to its spawner; any other process spawns observers as the product does."""

    current: ClassVar[ObserverChannel]

    @abstractmethod
    def connection(self, root: LaunchRoot) -> CoreConnection: ...


class SpawnedObservers(ObserverChannel):
    """A test that was not forked by the template: the product's own local connection."""

    def connection(self, root: LaunchRoot) -> CoreConnection:
        return LocalCoreConnection.from_launch(root)


@dataclass(frozen=True)
class ForkedObservers(ObserverChannel):
    """A test forked by the template: its spawner sits at the other end of ``spawner``."""

    spawner: socket.socket

    def connection(self, root: LaunchRoot) -> CoreConnection:
        return TemplateCoreConnection(root.path, self)

    def request(self, route: CommsRoute, service: socket.socket, ended: int) -> None:
        """One service for ``route`` on ``service``; it holds ``ended`` open until it exits."""
        socket.send_fds(self.spawner, [pickle.dumps(route)], [service.fileno(), ended])


ObserverChannel.current = SpawnedObservers()


@dataclass(frozen=True)
class TemplateCoreConnection(LocalCoreConnection):
    """The workspace's local Core, observed by a service the template forks warm."""

    observers: ForkedObservers

    def observation_source(self, route: CommsRoute) -> ObservationSource:
        return TemplateRouteObservation(route, self.observers)


@dataclass(frozen=True)
class TemplateRouteObservation(ObservationSource):
    route: CommsRoute
    observers: ForkedObservers

    def observation_peer(self) -> ObservationPeer:
        return TemplateObservationPeer(self.route, self.observers)


class TemplateObserverDied(ObserverDied):
    """The forked observation service ended; there is no process handle to describe."""

    def __init__(self, error: str = ""):
        super().__init__("The forked comms observer ended" + (f":\n{error}" if error else ""))


class TemplateObservationPeer(ObservationPeer):
    """The UI's end of a forked service. The service holds the write end of ``ended`` until it
    exits, so joining it is reading that pipe to its end."""

    def __init__(self, route: CommsRoute, channel: ForkedObservers) -> None:
        viewer, service = socket.socketpair()
        self.ended, held = os.pipe()
        with service:
            channel.request(route, service, held)
        os.close(held)
        self.connection = ViewerEnd(viewer.detach())

    def join(self) -> None:
        self.await_end(None)

    def await_end(self, seconds: float | None) -> None:
        if select.select([self.ended], [], [], seconds)[0]:
            os.read(self.ended, 1)

    def service_failed(self, traceback: str) -> ObserverDied:
        return TemplateObserverDied(traceback)

    def connection_closed(self) -> ObserverDied:
        return TemplateObserverDied()


@dataclass(frozen=True)
class ObserverSpawner:
    """Forked from the template beside one test, after becoming that test's process: forks one
    observation service per request until the test closes its end, then reaps them."""

    test: socket.socket

    def serve(self) -> None:
        while message := self.receive():
            route, (service, ended) = message
            if os.fork() == 0:
                self.test.close()
                self.run(route, socket.socket(fileno=service))
            os.close(service)
            os.close(ended)
        self.reap()

    def receive(self) -> tuple[CommsRoute, list[int]] | None:
        data, fds, _, _ = socket.recv_fds(self.test, 1 << 20, 2)
        return (pickle.loads(data), fds) if data else None

    @staticmethod
    def run(route: CommsRoute, service: socket.socket) -> None:
        code = 0
        try:
            serve_encoded(route, service)
        except BaseException:
            traceback.print_exc()
            code = 70
        finally:
            os._exit(code)

    @staticmethod
    def reap() -> None:
        while True:
            try:
                os.wait()
            except ChildProcessError:
                return
