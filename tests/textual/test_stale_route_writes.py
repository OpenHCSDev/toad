"""A retired source refuses input; an ambient default cannot retarget an app."""

import asyncio

from agent_comms.launch_root import LaunchRoot

from support.roots import installed_wire
from toad.core.input_events import UserInputSubmitted
from toad.conversation_submission import OrdinaryInputSubmission
from toad.widgets.comms_chat import CommsChatView


async def test_a_view_that_changed_during_send_preflight_keeps_the_draft_editable(workspace):
    workspace.thread("peer", "team")
    workspace.comms.messaging.send("peer", "#team", "CURRENT_HISTORY")
    async with workspace.app() as ui:
        await ui.open_channel("#team", actor=workspace.viewer)
        await ui.until_shows("CURRENT_HISTORY")
        view = ui.app.selected_session.query_one(CommsChatView)
        messaging = view.message_history.page_source.loader.comms.messaging
        before = messaging.bus.bus.revision()
        worker = await view.submissions.start_message(
            OrdinaryInputSubmission("STALE_DRAFT"), workspace.roots.wire,
            view.conversation, lambda: False, view._show_sent,
        ).prepare()
        await asyncio.wait_for(worker.wait(), 10)
        assert not view.send_block_reason
        assert view.prompt.text == "STALE_DRAFT"
        assert not view.prompt.prompt_text_area.disabled
        assert messaging.bus.bus.revision() == before


async def test_an_ambient_root_change_does_not_retarget_the_captured_app_namespace(workspace):
    workspace.thread("peer", "team")
    second = installed_wire(workspace.roots.attempt / "second")
    async with workspace.app() as ui:
        await ui.open_channel("#team", actor=workspace.viewer)
        view = ui.app.selected_session.query_one(CommsChatView)
        first = view.message_history.page_source.loader.comms
        before = first.bus.bus.revision(), second.bus.bus.revision()
        body = "CAPTURED_ORIGINAL_NAMESPACE"
        with LaunchRoot.from_path(second.root).selected():
            worker = await view.submissions.submit(UserInputSubmitted(body))
            await asyncio.wait_for(worker.wait(), 10)
        await ui.until(lambda: not view.send_block_reason, why="the original publication acknowledged by its source")
        assert ui.app.coordination_access.launch_root is workspace.launch_root
        assert ui.app.coordination_access.selection.root == first.root
        assert (first.bus.bus.revision(), second.bus.bus.revision()) == (before[0] + 1, before[1])
        (sent,) = first.bus.bus.latest_addressed(frozenset((workspace.viewer,)), frozenset(("#team",)))
        assert sent.body == body
        assert view.contains_user_message(sent)
        assert not view.prompt.prompt_text_area.disabled
        assert ui.failure() is None
