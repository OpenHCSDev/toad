"""A private send paints the same original outbound resource live and on replay."""

import asyncio
import json
import os
from pathlib import Path

from acp import schema
from agent_comms.comms import Comms
from agent_comms.pi_payloads import PiToolResult, ToolResultMessage
from agent_comms.threads import Thread
from agent_comms.tools import invoke_tool
from agent_comms.tool_results import tool_result_content
from runtime_fixture import ToadApp
from toad.acp.status import ToolCallStatus
from toad.widgets.outgoing_message import OutgoingMessage
from toad.widgets.route_header import RouteHeader
from toad.widgets.tool_call import ToolCall
from toad.widgets.transcript_history import transcript_blocks
from textual.style import Style


async def main():
    root = Path(os.environ['SENT_TOOL_ARTIFACTS']).resolve()
    root.mkdir(parents=True, exist_ok=False)
    os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'),
                      XDG_CONFIG_HOME=str(root / 'config'),
                      XDG_STATE_HOME=str(root / 'state'),
                      XDG_DATA_HOME=str(root / 'data'))
    comms = Comms(root / 'wire')
    comms.messaging.initialize_private_initial_protocol()
    for name in ('sender', 'recipient'):
        comms.registry.declare(Thread(name, frozenset(), str(root)))
    original = invoke_tool(comms, 'comms_send', {
        'from': 'sender', 'to': 'recipient', 'body': 'Original private **outgoing message**'})
    raw = dict(content=[dict(type='text', text=json.dumps(original))], details=original)
    result = PiToolResult.from_wire(raw)
    content = tool_result_content('private-send', result.text(), sent_message=result.sent_message(True))
    call = schema.ToolCall.model_validate(dict(toolCallId='private-send', title='Comms Send',
                                              status='completed', kind='other', content=content))
    live = ToolCall(ToolCallStatus.from_acp(call))
    saved = ToolResultMessage.from_wire(dict(role='toolResult', toolCallId='saved-send',
                                            toolName='comms_send', isError=False, **raw))
    replay, = transcript_blocks(tuple(saved.transcript_events(None)))
    app = ToadApp(project_dir=str(root))
    async with app.run_test(size=(120, 45)) as pilot:
        await app.selected_session.wait_content_ready()
        await app.selected_session.conversation.contents.mount(live, replay)
        live.set_expanded(True)
        replay.set_expanded(True)
        async with asyncio.timeout(15):
            while not (live.query(OutgoingMessage) and replay.query(OutgoingMessage)):
                await pilot.pause(.02)
        for tool in (live, replay):
            outgoing = tool.query_one(OutgoingMessage)
            assert outgoing.event == result.sent_message(True)
            assert outgoing.message_reference.message_id == original['id']
            header = outgoing.query_one(RouteHeader)
            assert header.route.sender == 'sender' and header.route.targets == ('recipient',)
            assert any(isinstance(span.style, Style)
                       and span.style.meta.get('@click') == ('open_target', ('recipient',))
                       for span in header.content.spans)
        assert app._exception is None
        print('Private send: original message/body/reference and clickable recipient '
              'paint in both live tool output and transcript replay; no provider input.', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
