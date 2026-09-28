"""Current shared records for UI fixture setup; not a compatibility decoder."""

from agent_comms.acp_extension import (
    CoordinationChangedUpdate,
    TranscriptSnapshotUpdate,
)
from agent_comms.thread_identity import ThreadIncarnation
from agent_comms.transcripts import TranscriptCursor, TranscriptPage


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


def snapshot_fact(events, page=None):
    return TranscriptSnapshotUpdate(
        page
        if page is not None
        else TranscriptPage(
            tuple(events),
            TranscriptCursor("fixture", 0),
            TranscriptCursor("fixture", len(events)),
            False,
            False,
        )
    )


class HeadlessScreen:
    """A weakly owned screen identity for headless reader fixtures."""


def attach_coordination(agent, wire_root, thread):
    """Headless reader tests still use the same app-owned typed fact contract."""
    from types import SimpleNamespace

    from runtime_fixture import ToadApp

    if agent._message_target is None:
        app = ToadApp(project_dir=str(agent.project_root_path))
        agent.attach_surface(SimpleNamespace()
            app=app, screen=HeadlessScreen(), post_message=lambda value: True
        )
    agent.coordination = coordination_fact(
        thread, wire_root, worktree=str(agent.project_root_path)
    )
