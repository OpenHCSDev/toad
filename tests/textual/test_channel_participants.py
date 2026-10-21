"""Textual-facing: the participants line above a channel composer is prepared off the UI thread (a Textual widget's paint input)."""

import asyncio
from collections import Counter
import os
import sys
from threading import get_ident

from agent_comms.child_process import ProcessIdentity
from agent_comms.thread_execution import ExternalThreadExecution

PARTICIPANTS = 24


async def test_private_channel_update_changes_participants_without_blocking_the_ui(workspace):
    from toad.widgets.channel_participants import ChannelParticipants

    service = workspace.comms
    service.messaging.initialize_private_initial_protocol()
    leases = []
    for index in range(PARTICIPANTS):
        owner = service.registry.declare(service.registry.new_thread(
            f"participant-{index:02}", frozenset({"team"}), str(workspace.project),
            process_identity=ProcessIdentity.capture(os.getpid()), execution=ExternalThreadExecution))
        leased, _ = service.registry.lease_local_turn(owner.name, f"private-turn-{index}")
        leases.append(leased.require_turn_lease())

    loop_thread = get_ident()
    calls = Counter()
    monitor = sys.monitoring
    monitor.use_tool_id(monitor.PROFILER_ID, "channel-participants")
    code = ChannelParticipants.prepare_participants.__code__
    monitor.register_callback(monitor.PROFILER_ID, monitor.events.PY_START, lambda *_: calls.update(
        ("UI" if get_ident() == loop_thread else "worker",)))
    monitor.set_local_events(monitor.PROFILER_ID, code, monitor.events.PY_START)
    try:
        async with workspace.app(size=(110, 38)) as ui:
            await ui.open_channel("#team", actor="participant-00")
            names = ui.textual[0].screen.query_one(ChannelParticipants).names
            await ui.until(lambda: "participant-23" in names.content.plain, why="every participant listed")
            assert all(f"participant-{index:02}" in names.content.plain for index in range(PARTICIPANTS))

            await ui.write_draft("Retained draft")
            sent = await asyncio.to_thread(
                service.messaging.send,
                "participant-00", "#team", "Private update")
            message = sent.message
            await ui.until_shows("Private update")
            await ui.press("x")
            assert ui.draft() == "Retained draftx"

            for lease in leases:
                await asyncio.to_thread(service.registry.release_turn, lease)
            leases.clear()
            await ui.until(lambda: names.content.plain == "No active turns", why="participants to retire")
            assert message.message_id
            await ui.write_draft("@participant-23")
            await ui.until_shows("Mention a thread")  # Idle members remain mentionable.
            assert calls["worker"] > 0
            assert calls["UI"] == 0
    finally:
        for lease in leases:
            await asyncio.to_thread(service.registry.release_turn, lease)
        monitor.set_local_events(monitor.PROFILER_ID, code, 0)
        monitor.free_tool_id(monitor.PROFILER_ID)
