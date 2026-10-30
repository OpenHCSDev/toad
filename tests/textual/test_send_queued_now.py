"""Send now reaches the agent's process through the real controller."""

from acp import schema
from acp.exceptions import RequestError

from agent_comms.acp_extension import SendNowRequest, encode_request

from toad.core.events import LogAgentFail


async def send_now(view) -> None:
    await view.submissions.send_now().wait()


async def test_send_now_dispatches_through_the_controller(workspace, monkeypatch):
    async with workspace.app(size=(115, 38)) as ui:
        agent = ui.detached_agent("queue-session")
        ui.attach_agent(agent)
        await ui.step()
        dispatched = []

        async def process_prompt(agent, content, metadata, require):
            require()
            dispatched.append(metadata)
            return schema.PromptResponse(stopReason="end_turn")

        monkeypatch.setattr(agent.process, "prompt", process_prompt)
        await send_now(ui.conversation)
        assert dispatched == [encode_request(SendNowRequest())]


async def test_refused_send_now_reports_the_agent_failure(workspace, monkeypatch):
    async with workspace.app(size=(115, 38)) as ui:
        agent = ui.detached_agent("queue-session")
        ui.attach_agent(agent)
        await ui.step()
        published = []
        publish = agent.events.publish

        def recording_publish(event):
            published.append(event)
            return publish(event)

        async def refused(agent, content, metadata, require):
            raise RequestError(-32000, "refused")

        monkeypatch.setattr(agent.process, "prompt", refused)
        monkeypatch.setattr(agent.events, "publish", recording_publish)
        await send_now(ui.conversation)
        assert [event for event in published if isinstance(event, LogAgentFail)]


async def test_send_now_without_a_bound_agent_does_nothing(workspace):
    async with workspace.app(size=(115, 38)) as ui:
        await ui.step()
        assert ui.conversation.submissions.send_now() is None
