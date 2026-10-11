"""Textual-facing: live agent output merges into blocks that the conversation window paints and retires."""

from agent_comms.routing import MessageRoute

from support.agents import detached
from toad.core.events import Update
from toad.core_event_carrier import CoreEventMessage
from toad.live_output import OutputStream, ResponseStream, ThoughtStream
from toad.response_delivery import RoutedResponse, UnroutedResponse
from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought


class DiagnosticStream(OutputStream):
    def matches(self, incoming):
        return True

    def create(self, fragment):
        return AgentThought(fragment)


def painted_window(ui):
    window = ui.conversation.window.region
    return "\n".join(strip.crop(window.x, window.right).text
                     for strip in ui.textual[0].screen._compositor.render_strips()[window.y:window.bottom])


async def test_fragments_of_one_stream_merge_and_different_streams_split(workspace):
    async with workspace.app() as ui:
        output = ui.conversation.output
        assert await output.append(ThoughtStream(), "   ") is None
        thought = await output.append(ThoughtStream(), "Thinking first")
        assert await output.append(ThoughtStream(), " and next") is thought
        response = await output.append(ResponseStream(), "Visible answer")
        assert await output.append(ResponseStream(), " continued") is response
        routed = await output.append(ResponseStream(RoutedResponse(MessageRoute("worker", ("#test",)))), "Routed answer")
        assert routed is not response
        assert thought.body.text == "Thinking first and next"
        assert response.body.text == "Visible answer continued"


async def test_a_boundary_clears_streams_and_the_blocks_stay_painted(workspace):
    async with workspace.app() as ui:
        view = ui.conversation
        await view.output.append(ThoughtStream(), "Thinking first")
        response = await view.output.append(ResponseStream(), "Visible answer")
        diagnostic = await view.output.append(DiagnosticStream(), "New declared case")
        view.output.boundary()
        await ui.until(lambda: not view.output.streams, why="the boundary to clear the live streams")
        await ui.until(lambda: "Visible answer" in painted_window(ui) and "New declared case" in painted_window(ui),
                       why="both blocks painted inside the conversation window")
        assert diagnostic.region.overlaps(view.window.region)
        assert response.body.text == "Visible answer"


async def test_queued_client_replies_of_one_local_turn_form_one_reply(workspace):
    """A generic ACP request can settle before its queued updates drain; its local turn still owns one reply."""
    async with workspace.app() as ui:
        view = ui.conversation
        agent = detached(workspace.project, None)
        ui.attach_agent(agent)
        subscription = agent.controller.surface.subscription
        view.turns.start_client()
        first = view.turns.owner.response_stream(UnroutedResponse())
        second = view.turns.owner.response_stream(UnroutedResponse())
        view.turns.finish_client()
        await view.on_acp_agent_message(CoreEventMessage(Update("text", "Local queued", first), subscription))
        await view.on_acp_agent_message(CoreEventMessage(Update("text", " response", second), subscription))
        local = view.output.streams[ResponseStream].block
        await view.output.finish(ResponseStream)
        assert local.body.text == "Local queued response"


async def test_a_different_turn_id_or_owner_notice_starts_a_new_block(workspace):
    async with workspace.app() as ui:
        view = ui.conversation
        one = await view.output.append(ResponseStream(turn_id="one"), "First turn")
        two = await view.output.append(ResponseStream(turn_id="two"), "Second turn")
        assert one is not two
        notice = await view.output.append(view.turns.owner.response_stream(UnroutedResponse()), "Owner notice")
        another = await view.output.append(view.turns.owner.response_stream(UnroutedResponse()), "Next owner notice")
        assert notice is not another


async def test_an_update_from_a_retired_source_adds_no_block(workspace):
    async with workspace.app() as ui:
        view = ui.conversation
        agent = detached(workspace.project, None)
        ui.attach_agent(agent)
        subscription = agent.controller.surface.subscription
        view.turns.start_client()
        queued = view.turns.owner.response_stream(UnroutedResponse())
        view.turns.finish_client()
        await view.on_acp_agent_message(CoreEventMessage(Update("text", "Local queued", queued), subscription))
        await view.output.finish(ResponseStream)
        count = len(view.query(AgentResponse))
        await view.on_acp_agent_message(CoreEventMessage(Update("text", "Retired source", ResponseStream()), subscription))
        assert len(view.query(AgentResponse)) == count


async def test_a_retired_output_refuses_appends(workspace):
    async with workspace.app() as ui:
        view = ui.conversation
        view.output.retire()
        assert await view.output.append(DiagnosticStream(), "Retired view must not reopen") is None
