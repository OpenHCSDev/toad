"""A private project with its own comms wire, and Toad started on it."""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import cached_property
import os
from pathlib import Path
from typing import TYPE_CHECKING

from support.roots import Roots
from support.ui import TextualUi

if TYPE_CHECKING:
    from agent_comms.comms import Comms
    from toad.agent_schema import AgentDefinition


class Workspace:
    """Everything a test of the running app starts from."""

    def __init__(self, roots: Roots) -> None:
        self.roots = roots
        self.project = roots.project
        self.project.mkdir(parents=True, exist_ok=True)

    @cached_property
    def comms(self) -> Comms:
        """The test's own wire, as Core serves it."""
        from agent_comms.comms import wire

        return wire(self.roots.wire)

    @property
    def viewer(self) -> str:
        """The name the user of this project sends as."""
        return self.comms.messaging.user_identity(str(self.project)).name

    def thread(self, name: str, *tags: str, running: bool = False, title: str | None = None):
        """Declare a thread on the wire; a running thread is owned by this process."""
        from agent_comms.child_process import ProcessIdentity
        from agent_comms.threads import Thread

        identity = ProcessIdentity.capture(os.getpid()) if running else None
        self.comms.registry.declare(Thread(
            name, frozenset(tags), str(self.project), title=title, process_identity=identity))
        return self.comms.registry.require(name)

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

    @asynccontextmanager
    async def app(self, *, size: tuple[int, int] = (120, 40), agent: AgentDefinition | None = None,
                  application: type | None = None):
        """Start Toad headless on this project; yields once the first session is shown."""
        from toad.app import ToadApp

        app = (application or ToadApp)(agent_data=agent, project_dir=str(self.project))
        async with app.run_test(size=size) as pilot:
            ui = TextualUi(app, pilot)
            await app.selected_session.wait_content_ready()
            await ui.step()
            yield ui
            if (error := ui.failure()) is not None:
                raise error
