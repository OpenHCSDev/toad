"""Input typed in Toad is recorded by Core as the registered human's, for the first input and a queued one alike."""

from pathlib import Path

from agent_comms.acp_extension import QueuePromptRequest
from agent_comms.input_disposition import InputDispositions
from agent_comms.native_entries import NativeEntry
from agent_comms.retained_task_facts import CurrentHumanInputTaskFact

from support.native import ControlledProvider, native_session


async def test_typed_and_queued_inputs_carry_the_same_registered_human_origin(workspace, native_package):
    provider = ControlledProvider(
        reply=lambda request, number: ({"role": "assistant", "content": f"ORIGIN_ANSWER_{number}"}, "stop"),
        request_budget=2)
    async with native_session(workspace, native_package, provider=provider) as native:
        ui, agent, comms = native.ui, native.agent, native.comms
        await ui.until(lambda: agent.queue_attachment.scope.matches_session(agent.session_id), seconds=20, why="the queue attachment")
        provider.hold_next_request()
        first_text = "FIRST_HUMAN_INPUT: keep the project and the unknown state."
        await ui.write_draft(first_text)
        await ui.press("enter")
        await ui.until(provider.entered.is_set, seconds=30, why="the input at the provider")
        inputs = InputDispositions(comms.root / InputDispositions.filename)
        await ui.until(lambda: len(inputs.read().rows) == 1, seconds=20, why="one recorded input")
        first, = inputs.read().rows.values()
        origin = first.origin.require_human()
        assert origin.root_id == comms.bus.log.read_metadata_unlocked().wire_root_id
        assert first.source_text == first_text
        origin.author.require_registered(comms.registry.snapshot())

        command = QueuePromptRequest("FOLLOWING_HUMAN_INPUT: never replay the first.", True)
        await agent.send_prompt(command.user_text, request=command)
        await ui.until(lambda: len(inputs.read().rows) == 2, seconds=20, why="two recorded inputs")
        following = inputs.read().lookup("acp:" + command.input_id)
        assert following.origin == origin and following.source_text == command.user_text

        provider.release()
        await ui.until(lambda: all(row.has_started for row in inputs.read().rows.values()), seconds=30,
                       why="both inputs to start")
        await ui.until(lambda: not native.executing, seconds=30, why="both turns to finish")
        assert len(provider.requests) == 2
        finished = InputDispositions(inputs.path).read()
        assert len(finished.rows) == 2
        assert all(row.origin == origin for row in finished.rows.values())
        owner = comms.registry.require("beta")
        snapshot = comms.registry.snapshot()
        assert all(isinstance(row.origin.retained_fact(row).for_owner(owner, snapshot), CurrentHumanInputTaskFact)
                   for row in finished.rows.values())
        with NativeEntry.open_evidence(Path(owner.require_saved_session())) as saved:
            _header, entries = saved.observe()
        assert {row.native_id for row in finished.rows.values()} <= {
            entry.message.input_id for entry in entries if entry.is_message and entry.message.user}
