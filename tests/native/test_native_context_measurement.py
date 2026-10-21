"""Context use reported by a real native turn reaches the status line, and is restored from the saved session."""

from support.native import native_session
from toad.core import input_events


async def test_measured_usage_is_shown_and_restored_without_asking_the_model(workspace, native_package):
    async with native_session(workspace) as native:
        ui, agent, provider = native.ui, native.agent, native.provider
        view = ui.conversation
        await ui.until_agent_ready()
        assert not agent.context_measurement.available
        assert "Native owner has not reported" in ui.status()
        await view.submit_input(input_events.UserInputSubmitted("CONTEXT_MEASUREMENT_NATIVE"))
        await ui.until(lambda: "NATIVE_RESPONSE_1" in ui.painted(view.window), seconds=30, why="the answer")
        await ui.until(lambda: agent.context_measurement.available, seconds=20, why="a context measurement")
        measured = agent.context_measurement
        assert measured.used > 0 and measured.size == 32768
        await ui.until_shows(measured.percentage_display)
        assert len(provider.requests) == 1
        await ui.until(lambda: not native.executing, seconds=20, why="the turn to finish")

        await agent.session.reconnect()
        await ui.until(agent.session.settled.is_set, seconds=30, why="the reconnect to settle")
        await ui.until(lambda: agent.context_measurement.available
                       and agent.context_measurement.source_label == "last response", seconds=20,
                       why="the measurement restored from the saved session")
        assert len(provider.requests) == 1, "Restoring the measurement asked the model"
        restored = agent.context_measurement
        assert (restored.used, restored.size) == (measured.used, measured.size)
        await ui.until_shows("last response")
