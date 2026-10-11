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
