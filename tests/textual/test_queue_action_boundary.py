"""Queue actions keep stale sources and deliberate refusals apart from bugs.

Use the actual app, source retirement, agent binding and ACP transport. The
unexpected-error callback exercises the inspection's public action boundary;
it neither patches a product owner nor submits input to a model.
"""

import pytest
from agent_comms.acp_extension import ClearQueueRequest, QueueScope, encode_request
from textual.widgets import Static

from support.agents import peer
from support.workspace import Workspace
from toad.acp.client_session import ClientSessionRequest
from toad.conversation_submission import ConversationSubmissions
from toad.session_scope import AgentAttached
from toad.widgets.comms_chat import CommsChatView


async def unexpected_value_error(owner: ConversationSubmissions, scope: QueueScope) -> None:
    raise ValueError("Unexpected action defect")


async def test_stale_source_stops_before_the_action_and_closed_source_identity_is_stable(
    workspace: Workspace,
) -> None:
    workspace.thread("peer", "team")
    async with workspace.app(size=(115, 38)) as ui:
        await ui.open_channel("#team", actor=workspace.viewer)
        view = ui.app.selected_session.query_one(CommsChatView)
        owner = view.submissions
        await ui.write_draft("kept across source retirement")
        inspection = owner.inspect_queue()
        await ui.until(lambda: ui.app.screen is inspection, why="queue inspection mounted")
        await view.message_history.retire_source()
        view.message_history.close()
        replacement = view.message_history.page_source
        assert owner.queue_source is replacement
        assert owner.queue_source is owner.queue_source
        assert owner.queue_source is not inspection.source
        # If stale checks reach this action, ValueError must fail the control.
        await inspection.apply_action(unexpected_value_error)
        assert ui.app.screen is inspection
        assert inspection.query_one("#queue-error", Static).content
        inspection.dismiss()
        await ui.until(lambda: ui.app.screen is not inspection, why="inspection closed")
        assert ui.draft() == "kept across source retirement"


async def test_stale_agent_stops_before_inspection_or_send_now_action(workspace: Workspace) -> None:
    async with workspace.app(size=(115, 38)) as ui:
        owner = ui.conversation.submissions
        await ui.write_draft("kept across agent replacement")
        source, previous = owner.queue_source, owner.view.agent_binding
        scope = source.queue_scope(owner)
        inspection = owner.inspect_queue()
        await ui.until(lambda: ui.app.screen is inspection, why="queue inspection mounted")
        replacement = ui.detached_agent("replacement")
        ui.attach_agent(replacement)
        assert owner.queue_source is source
        assert owner.view.agent_binding is not previous
        await inspection.apply_action(unexpected_value_error)
        assert ui.app.screen is inspection
        assert inspection.query_one("#queue-error", Static).content
        await owner._send_now(source, previous, scope)
        assert owner.view.feedback.display
        assert owner.view.feedback.content
        inspection.dismiss()
        await ui.until(lambda: ui.app.screen is not inspection, why="inspection closed")
        assert ui.draft() == "kept across agent replacement"
        await replacement.stop()


async def test_unsupported_action_stays_visible_and_unrelated_value_error_escapes(workspace: Workspace) -> None:
    async with workspace.app(size=(115, 38)) as ui:
        owner = ui.conversation.submissions
        await ui.write_draft("kept after refusal")
        inspection = owner.inspect_queue()
        await ui.until(lambda: ui.app.screen is inspection, why="queue inspection mounted")
        await inspection.apply_action(inspection.source.queue_clear)
        assert ui.app.screen is inspection
        assert inspection.query_one("#queue-error", Static).content
        with pytest.raises(ValueError, match="Unexpected action defect"):
            await inspection.apply_action(unexpected_value_error)
        assert ui.app.screen is inspection
        inspection.dismiss()
        await ui.until(lambda: ui.app.screen is not inspection, why="inspection closed")
        assert ui.draft() == "kept after refusal"


async def test_real_acp_refusal_keeps_inspection_open_without_retry(workspace: Workspace) -> None:
    async with workspace.app(size=(115, 38), binding=AgentAttached(peer("refuses_queue"))) as ui:
        await ui.until(ui.agent_ready, why="external ACP peer ready")
        owner = ui.conversation.submissions
        agent = owner.view.agent_binding
        authority = ClientSessionRequest(agent, agent.session_id)
        await ui.write_draft("kept after ACP refusal")
        inspection = owner.inspect_queue()
        await ui.until(lambda: ui.app.screen is inspection, why="queue inspection mounted")

        async def refused_at_acp(submissions: ConversationSubmissions, scope: QueueScope) -> None:
            # The official SDK returns RequestError from an actual child process.
            await agent.process.prompt(
                agent, [{"type": "text", "text": " "}], encode_request(ClearQueueRequest()), authority.require,
            )

        await inspection.apply_action(refused_at_acp)
        assert ui.app.screen is inspection
        assert inspection.query_one("#queue-error", Static).content
        assert authority.current
        assert workspace.prompts_received() == [" "]
        inspection.dismiss()
        await ui.until(lambda: ui.app.screen is not inspection, why="inspection closed")
        assert ui.draft() == "kept after ACP refusal"
