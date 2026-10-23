"""Coordination facts as Core's ACP extension carries them, for tests that hand them to an agent."""

from __future__ import annotations

from dataclasses import replace

from agent_comms.acp_extension import CoordinationChangedUpdate, encode_updates
from agent_comms.child_process import ProcessIdentity
from agent_comms.context_reading import ContextReading, UnmeasuredContext
from agent_comms.thread_identity import RecordedThreadIncarnation


def coordination_fact(thread, wire_root, *, owner=ProcessIdentity(1, 1), model="fixture-model", thinking_level=None,
                      worktree=None, title=None,
                      context_usage: ContextReading = UnmeasuredContext()) -> CoordinationChangedUpdate:
    # Core declares model a str and context usage a ContextReading (7c5fdc279, 3e7aabe09).
    return CoordinationChangedUpdate(
        RecordedThreadIncarnation(thread, 1.0), str(wire_root), owner, str(worktree or wire_root),
        model, thinking_level, title or thread, context_usage)


def registered_coordination_fact(comms, thread, **facts) -> CoordinationChangedUpdate:
    """The fact for a thread declared on `comms`, with the registry's own incarnation."""
    return replace(coordination_fact(thread, comms.root, **facts),
                   thread=comms.registry.require(thread).incarnation)


def carrying(*facts) -> dict:
    """An otherwise empty agent message chunk whose metadata carries Core updates."""
    return {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": ""},
            "_meta": encode_updates(*facts)}
