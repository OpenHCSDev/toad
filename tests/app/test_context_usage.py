"""The status line shows context use as reported; a zero after compaction means unknown, not empty."""

from agent_comms.acp_extension import ContextUsage

from support.agents import deliver, detached, peer, script
from support.coordination import carrying, coordination_fact


def usage(used, **more):
    return {"sessionUpdate": "usage_update", "used": used, "size": 272000, **more}


async def test_usage_updates_reach_the_status_line(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        agent = detached(workspace.project, "fixture")
        ui.attach_agent(agent)
        await deliver(agent, usage(120000, cost={"amount": .5, "currency": "USD"}))
        await ui.until(lambda: "120.0K" in ui.status(), why="reported usage in the status line")
        await ui.until(lambda: ui.shows("120.0K") and ui.shows("44.1%"), why="usage and percentage on screen")

        await deliver(agent, usage(0))
        await ui.until(lambda: "Context unavailable" in ui.status(), why="zero usage shown as unavailable")
        assert "0.0K" not in ui.status()
        assert not agent.context_measurement.available

        await deliver(agent, usage(27000))
        await ui.until(lambda: "27.0K" in ui.status(), why="the next valid estimate")

        saved = coordination_fact("fixture", workspace.roots.wire, worktree=str(workspace.project),
                                  context_usage=ContextUsage(38723, 272000))
        await deliver(agent, carrying(saved))
        await ui.until(lambda: "38.7K" in ui.status() and "last response" in ui.status(),
                       why="the saved measurement labelled as the last response")
        await agent.stop()


async def test_usage_measured_while_another_tab_is_shown_appears_on_return(workspace):
    async with workspace.app(size=(100, 35), agent=peer("scripted")) as ui:
        await ui.until_agent_ready()
        first = ui.selected_tab
        late = {"update": usage(40000)}
        await ui.write_draft(script({"update": usage(27000)}, {"wait": "hidden"}, late))
        await ui.press("enter")
        await ui.until(lambda: "27.0K" in ui.status(), why="the first measurement")
        await ui.new_session()
        workspace.release("hidden")
        await ui.until(lambda: late in workspace.steps_done(), why="the agent to report usage while hidden")
        assert not ui.shows("40.0K")
        await ui.select_tab(first)
        await ui.until(lambda: ui.shows("40.0K"), why="the measurement taken while the tab was hidden")
