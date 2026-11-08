"""Coordination facts as Core's ACP extension carries them, for tests that hand them to an agent."""

from __future__ import annotations

from pathlib import Path
from agent_comms.projects.checkouts import Checkout

from agent_comms.acp_extension import CoordinationChangedUpdate, encode_updates
from agent_comms.child_process import ProcessIdentity
from agent_comms.context_reading import ContextReading, UnmeasuredContext


def coordination_fact(comms, thread, *, owner=ProcessIdentity(1, 1), model="fixture-model", thinking_level=None,
                      worktree=None, title=None,
                      context_usage: ContextReading = UnmeasuredContext()) -> CoordinationChangedUpdate:
    """The fact Core carries for a thread declared on `comms`, with the registry's own incarnation:
    an invented one names a thread Core never declared, and every source check refuses it."""
    # Core declares model a str and context usage a ContextReading (7c5fdc279, 3e7aabe09).
    return CoordinationChangedUpdate(
        comms.registry.require(thread).incarnation, str(comms.root), owner,
        Checkout(Path(worktree or comms.root)), model, thinking_level, title or thread, context_usage)


def carrying(*facts) -> dict:
    """An otherwise empty agent message chunk whose metadata carries Core updates."""
    return {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": ""},
            "_meta": encode_updates(*facts)}
