"""A private project with its own comms wire, and Toad started on it."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from functools import cached_property
from pathlib import Path
from typing import ClassVar

from agent_comms.comms import Comms
from agent_comms.execution.launch_root import LaunchRoot
from agent_comms.nominal.field_codec import AcpSessionId, FieldCodec, NoAcpSessionId
from agent_comms.projects.checkouts import Checkout
from agent_comms.projects.repo import Repo
from agent_comms.registry.threads import NativeThread

from support.agents import AppAgents
from support.roots import Roots, installed_wire
from support.ui import TextualUi
from toad.app import ToadApp
from toad.comms_root import LocalCoreConnection
from toad.launch_binding import AgentBinding, NoAgent
from toad.screens.main import MainScreen


class Workspace:
    """Everything a test of the running app starts from."""

    # The Core connection an app gets unless its test names one. A test the template forked
    # gets support.warm_helpers.WarmCoreConnection, whose helpers fork from the warm template.
    local_connection: ClassVar[type[LocalCoreConnection]] = LocalCoreConnection

    def __init__(self, roots: Roots) -> None:
        self.roots = roots
        self.project = roots.project
        self.project.mkdir(parents=True, exist_ok=True)
        Repo.git(self.project, "init", "-q")
        self.launch_root = LaunchRoot.from_path(roots.wire)
        self.launch_root.install()
        self.comms = installed_wire(roots.wire)

    @property
    def viewer(self) -> str:
        """The name the user of this project sends as."""
        return self.comms.messaging.user_identity(Checkout(self.project)).name

    def thread(self, name: str, *tags: str, running: bool = False, title: str | None = None,
               root: Path | None = None):
        """Declare a thread on the wire; a running thread is owned by this process."""
        from agent_comms.execution.child_process import (
            NoProcess,
            ProcessIdentity,
        )
        from agent_comms.registry.thread_text import ThreadText

        comms = self.comms if root is None else installed_wire(root)
        identity = ProcessIdentity.capture(os.getpid()) if running else NoProcess()
        comms.registry.declare(NativeThread(
            name, frozenset(tags), Checkout(self.project), title=ThreadText.external(title), process_identity=identity))
        return comms.registry.require(name)

    async def bind(self, screen: MainScreen, name: str, *, root: Path | None = None) -> None:
        """Bind the declared thread through the view's source and identity owners."""
        comms = self.comms if root is None else installed_wire(root)
        async with screen.presentation.transcript.changing_source(screen):
            screen.bind_thread(comms.registry.require(name).incarnation, str(comms.root))
        screen.link_context_changed()

    def child_processes(self, marker: str) -> list:
        """This test's live child processes whose command line mentions `marker`."""
        import psutil

        found = []
        for process in psutil.Process().children(recursive=True):
            try:
                if process.status() != psutil.STATUS_ZOMBIE and any(marker in part for part in process.cmdline()):
                    found.append(process)
            except psutil.NoSuchProcess:
                continue
        return found

    def received(self) -> list[dict]:
        """Everything the scripted agent recorded, oldest first (see ``support/peers/base.py``)."""
        import json

        record = self.project / "peer-received.jsonl"
        return [json.loads(line) for line in record.read_text().splitlines()] if record.exists() else []

    def release(self, name: str) -> None:
        """Let the scripted agent past its ``{"wait": name}`` step."""
        (self.project / f"released-{name}").touch()

    def steps_done(self) -> list[dict]:
        """The steps the scripted agent has finished, in order."""
        return [fact["done"] for fact in self.received() if "done" in fact]

    def prompts_received(self) -> list[str]:
        return [fact["prompt"] for fact in self.received() if "prompt" in fact]

    @cached_property
    def agents(self) -> AppAgents:
        return AppAgents.unrun(self.project, self.launch_root)

    @asynccontextmanager
    async def app(self, *, size: tuple[int, int] = (120, 40), binding: AgentBinding = NoAgent(),
                  application: type | None = None, session: bool = True, resume: str | None = None,
                  notifications: bool = False, connect=None):
        """Start Toad headless on this project; yields once its first session is shown.

        Toad itself starts with no tab open unless the launch names a session
        to resume (``resume``); ``session=False`` yields what it started with.
        ``connection`` selects the Core; by default the workspace's own local root.
        """
        app = (application or ToadApp)(agent_binding=binding, project_dir=Checkout(self.project),
                                      connection=(connect or self.local_connection.from_launch)(self.launch_root),
                                      agent_session_id=FieldCodec.decode(AcpSessionId | NoAcpSessionId, resume))
        async with app.run_test(size=size, notifications=notifications) as pilot:
            await app.application.start_worker.wait()
            ui = TextualUi(app, pilot)
            if session:
                if not app.session_navigation.members:
                    await ui.new_session()
                await app.selected_session.wait_content_ready()
            await ui.step()
            yield ui
            if (error := ui.failure()) is not None:
                raise error
