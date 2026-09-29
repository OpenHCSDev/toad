"""Current shared records for UI fixture setup; not a compatibility decoder."""

from agent_comms.acp_extension import (
    CoordinationChangedUpdate,
)
from agent_comms.thread_identity import ThreadIncarnation


def coordination_fact(
    thread,
    wire_root,
    *,
    owner_pid=1,
    model=None,
    thinking_level=None,
    worktree=None,
    title=None,
    context_usage=None,
):
    return CoordinationChangedUpdate(
        ThreadIncarnation(thread, 1.0),
        str(wire_root),
        owner_pid,
        str(worktree or wire_root),
        model,
        thinking_level,
        title or thread,
        context_usage,
    )



def attach_coordination(agent, wire_root, thread):
    """Bind the actual Agent-owned typed coordination fact, without a fake UI."""
    agent.coordination = coordination_fact(
        thread, wire_root, worktree=str(agent.project_root_path)
    )


def attach_registered_coordination(agent, wire_root, thread):
    """Use the real registry identity when a fixture actually registers an owner."""
    from dataclasses import replace
    from agent_comms.comms import wire
    agent.coordination = replace(
        coordination_fact(thread, wire_root, worktree=str(agent.project_root_path)),
        thread=wire(wire_root).registry.require(thread).incarnation,
    )
