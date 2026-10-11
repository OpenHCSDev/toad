"""Agent processes a test starts in place of a real model."""

from __future__ import annotations

from pathlib import Path
import shlex
import sys

PEERS = Path(__file__).with_name("peers")


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


def detached(project: Path, session_id: str | None = None, *, identity: str = "test-agent"):
    """A Toad agent object with no process behind it; the test delivers its updates by hand."""
    from toad.acp.agent import Agent
    from toad.agent_schema import AgentDefinition

    return Agent(project, AgentDefinition(identity, identity, {"*": "true"}), session_id)


async def deliver(agent, update: dict, *, session_id: str | None = None):
    """Hand the agent one ACP ``session/update`` exactly as its process would send it."""
    result = await agent.server.call({"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": session_id or agent.session_id, "update": update}})
    assert result is None, result


def script(*steps: dict) -> str:
    """A prompt for ``peer("scripted")``: steps of {"update": ...}, {"say": ...} or {"wait": name}."""
    import json

    return json.dumps(list(steps))
