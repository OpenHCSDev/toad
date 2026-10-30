"""ConversationSubmissions.send_now reaches the agent through the view's queue source."""

from acp.exceptions import RequestError

from toad.submission_queue import NativeQueueSource


async def send_now(view) -> None:
    await view.submissions.send_now().wait()


async def test_send_now_asks_the_views_queue_source(workspace, monkeypatch):
    async with workspace.app(size=(115, 38)) as ui:
        agent = ui.detached_agent("queue-session")
        ui.attach_agent(agent)
        await ui.step()
        view = ui.conversation
        sent = []

        async def controller_send_now() -> bool:
            sent.append(agent)
            return True

        monkeypatch.setattr(agent.controller, "send_now", controller_send_now)
        assert isinstance(view.queue_source, NativeQueueSource)
        await send_now(view)
        assert sent == [agent]


async def test_refused_send_now_reports_its_error(workspace, monkeypatch):
    async with workspace.app(size=(115, 38)) as ui:
        agent = ui.detached_agent("queue-session")
        ui.attach_agent(agent)
        await ui.step()
        view = ui.conversation
        flashed = []

        async def refused() -> bool:
            raise RequestError(-32000, "refused")

        monkeypatch.setattr(agent.controller, "send_now", refused)
        monkeypatch.setattr(view.feedback, "flash", lambda text, **_: flashed.append(text))
        await send_now(view)
        assert [text for text in flashed if text.startswith("Send now failed:")]


async def test_send_now_without_a_bound_agent_does_nothing(workspace):
    async with workspace.app(size=(115, 38)) as ui:
        await ui.step()
        assert ui.conversation.submissions.send_now() is None
