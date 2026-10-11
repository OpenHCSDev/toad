"""Attaching to a saved native thread shows its recorded context use before any model is asked."""

from agent_comms.threads import Thread

from support.coordination import coordination_fact
from support.native import attached_app, start_private_native_wire, without_provider


async def test_saved_context_use_is_shown_on_attach_and_replaced_by_live_reports(workspace, native_package):
    without_provider()
    comms = start_private_native_wire(workspace.roots.wire, native_package)
    comms.registry.declare(Thread("saved", frozenset({"acp"}), str(workspace.project)))
    comms.agents.set_agent_info("saved", model="test/model", context_used=38723, context_size=272000)
    async with attached_app(workspace, comms, "saved", size=(120, 40)) as (ui, agent):
        await ui.until_agent_ready()
        await ui.until(lambda: "38.7K" in ui.status(), why="the saved context use")
        assert (agent.context_measurement.used, agent.context_measurement.size) == (38723, 272000)
        assert agent.context_measurement.source_label == "last response"
        assert "last response" in ui.status()

        agent.updates.accept("saved", {"sessionUpdate": "usage_update", "used": 40000, "size": 272000})
        await ui.until(lambda: "last response" not in ui.status(), why="a live report to replace the saved one")
        assert agent.context_measurement.used == 40000 and agent.context_measurement.source_label == ""

        agent.comms_consumer_class(agent, agent.session_id).dispatch_sync(
            coordination_fact("saved", str(workspace.roots.wire), context_usage=None))
        await ui.until(lambda: "unavailable" in ui.status(), why="context use reported as unavailable")
        assert not agent.context_measurement.available
