"""Agent processes a test starts in place of a real model."""

from __future__ import annotations

from pathlib import Path
import shlex
import sys
from typing import TYPE_CHECKING

from toad.session_scope import NoAgent
from toad.core.events import CoreEvent

if TYPE_CHECKING:
    from toad.acp.agent import Agent
    from toad.agent_schema import AgentDefinition
    from toad.app import ToadApp

PEERS = Path(__file__).with_name("peers")


class RecordedEvents(list[CoreEvent]):
    """A retained receiver for the event stream's weak subscription."""

    def receive(self, event: CoreEvent, subscription) -> None:
        self.append(event)


def peer(script: str, *, name: str = "Test peer", identity: str = "test-peer"):
    """An agent definition that runs one of the scripted ACP peers in ``support/peers``."""
    from toad.agent_schema import AgentDefinition

    return AgentDefinition.decode({
        "name": name, "identity": identity, "short_name": identity, "protocol": "acp",
        "run_command": {"*": shlex.join((sys.executable, str(PEERS / f"{script}.py")))},
    })


def command(*argv: str, name: str = "Test command", identity: str = "test-command"):
    """An agent definition whose process is an arbitrary command (one that exits, hangs, ...)."""
    from toad.agent_schema import AgentDefinition

    return AgentDefinition.decode({
        "name": name, "identity": identity, "short_name": identity, "protocol": "acp",
        "run_command": {"*": shlex.join(argv)},
    })


class AppAgents:
    """Agents attached to the app that owns them: its project, events and transcripts."""

    def __init__(self, app: ToadApp) -> None:
        self.app = app

    @classmethod
    def unrun(cls, project: Path) -> AppAgents:
        """For a test with no app running: agents of an app built on ``project`` and never run."""
        from toad.app import ToadApp

        return cls(ToadApp(agent_binding=NoAgent(), project_dir=str(project)))

    def agent[A: Agent](self, kind: type[A], definition: AgentDefinition, session_id: str | None = None,
                        **fields: object) -> A:
        """An agent of ``kind`` built through the app's own Agent constructor; ``fields`` are the subclass's own."""
        return kind(self.app.project_dir.path, definition, session_id, app_events=self.app.events,
                    transcripts=self.app.coordination_access.transcripts, **fields)

    def detached_agent(self, session_id: str | None = None, *, identity: str = "test-agent") -> Agent:
        """A Toad agent object with no process behind it; the test delivers its updates by hand."""
        from toad.acp.agent import Agent
        from toad.agent_schema import AgentDefinition

        return self.agent(Agent, AgentDefinition(identity, identity, {"*": "true"}), session_id)


async def deliver(agent, update: dict, *, session_id: str | None = None):
    """Hand the agent one ACP ``session/update`` exactly as its process would send it."""
    from acp import schema

    notification = schema.SessionNotification.model_validate({
        "sessionId": session_id or agent.session_id, "update": update})
    await agent.updates.receive(notification, update)


def script(*steps: dict) -> str:
    """A prompt for ``peer("scripted")``: steps of {"update": ...}, {"say": ...} or {"wait": name}."""
    import json

    return json.dumps(list(steps))


class PendingAnswer:
    """One SDK request whose answer the test supplies later."""

    def __init__(self):
        import asyncio

        self.started = asyncio.Event()
        self.result = asyncio.get_running_loop().create_future()

    async def wait(self):
        self.started.set()
        return await self.result


class PendingConnection:
    """The SDK connection seen by an agent, answering session requests from ``PendingAnswer``s."""

    def __init__(self, new=(), load=None):
        self.new, self.load, self.loaded_sessions = list(new), load, []

    async def new_session(self, cwd, mcp_servers):
        return await self.new.pop(0).wait()

    async def load_session(self, cwd, session_id, mcp_servers, **metadata):
        self.loaded_sessions.append(session_id)
        return await self.load.wait()

    async def close(self):
        pass
