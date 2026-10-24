"""A private project with its own comms wire, and Toad started on it."""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import cached_property
import os
from pathlib import Path
from typing import TYPE_CHECKING

from support.agents import AppAgents
from support.roots import Roots, installed_wire
from support.ui import TextualUi
from agent_comms.threads import Thread
from toad.session_scope import AgentBinding, NoAgent

if TYPE_CHECKING:
    from agent_comms.comms import Comms
    from toad.screens.main import MainScreen


class Workspace:
    """Everything a test of the running app starts from."""

    def __init__(self, roots: Roots) -> None:
        from agent_comms.launch_root import LaunchRoot

        self.roots = roots
        self.project = roots.project
        self.project.mkdir(parents=True, exist_ok=True)
        LaunchRoot.from_path(roots.wire).install()
        self.comms = installed_wire(roots.wire)

    @property
    def viewer(self) -> str:
        """The name the user of this project sends as."""
        return self.comms.messaging.user_identity(str(self.project)).name

    def thread(self, name: str, *tags: str, running: bool = False, title: str | None = None,
               root: Path | None = None):
        """Declare a thread on the wire; a running thread is owned by this process."""
        from agent_comms.child_process import NoProcess, ProcessIdentity
        from agent_comms.thread_text import ThreadText

        comms = self.comms if root is None else installed_wire(root)
        identity = ProcessIdentity.capture(os.getpid()) if running else NoProcess()
        comms.registry.declare(Thread(
            name, frozenset(tags), str(self.project), title=ThreadText.external(title), process_identity=identity))
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
        return AppAgents.unrun(self.project)

    @asynccontextmanager
    async def app(self, *, size: tuple[int, int] = (120, 40), binding: AgentBinding = NoAgent(),
                  application: type | None = None, session: bool = True, resume: str | None = None):
        """Start Toad headless on this project; yields once its first session is shown.

        Toad itself starts with no tab open unless the launch names a session
        to resume (``resume``); ``session=False`` yields what it started with.
        """
        from toad.app import ToadApp

        launch = {} if resume is None else {"agent_session_id": resume}
        app = (application or ToadApp)(agent_binding=binding, project_dir=str(self.project), **launch)
        async with app.run_test(size=size) as pilot:
            await app.application.started.wait()
            ui = TextualUi(app, pilot)
            if session:
                if not app.session_navigation.members:
                    await ui.new_session()
                await app.selected_session.wait_content_ready()
            await ui.step()
            yield ui
            if (error := ui.failure()) is not None:
                raise error
