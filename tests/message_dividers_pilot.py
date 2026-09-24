"""Full-width timed headers stay inside text blocks across native and wire views."""

import asyncio
import os
import tempfile
import time
from pathlib import Path

from agent_comms import MessageRoute, Thread, wire
from runtime_fixture import ToadApp

from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from toad.widgets.comms_chat import CommsChatView, session_thread_name
from toad.widgets.incoming_message import IncomingMessage
from toad.widgets.irc_message import IRCMessage, WireMarkdownMessage
from toad.widgets.message_divider import MessageDivider
from toad.widgets.tool_call import ToolCall
from toad.widgets.user_input import UserInput


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-message-dividers-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"),
                          AGENT_COMMS_ROOT=str(root / "wire"))
        comms = wire(root / "wire")
        comms.register(Thread("peer", frozenset(), str(root)))
        me = session_thread_name(root)
        comms.register(Thread(me, frozenset(), str(root)))
        sent = comms.send_message("peer", "#all", "incoming wire")
        outbound = comms.send_message(me, "#all", "outbound wire")
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            owner = app.current_mode
            native = app.screen.conversation
            user = await native.post(UserInput("human text"))
            reply = await native.post_agent_response("agent text")
            assert reply is not None
            incoming = await native.post(IncomingMessage("peer", "hello", "#all"))
            thought = await native.post(AgentThought("not a displayed message"))
            tool = await native.post(ToolCall({"toolCallId": "tool-one", "title": "Read source"}))
            await pilot.pause()
            assert len(user.query(MessageDivider)) == 1
            assert "User" in user.query_one(MessageDivider).render().plain
            assert len(reply.query(MessageDivider)) == 1
            assert len(incoming.query(MessageDivider)) == 1
            assert not thought.query(MessageDivider)
            assert not tool.query(MessageDivider)
            routed = await native.post(AgentResponse(
                "routed answer", route=MessageRoute(me, ("#all",)),
            ))
            await pilot.pause()
            assert "Outbound" in routed.query_one(MessageDivider).render().plain
            for block in (user, reply, incoming):
                divider = block.query_one(MessageDivider)
                assert divider.render().plain.startswith("─")
                assert divider.render().plain.endswith("─")
                assert divider.render().plain.count("─") > 4
                assert divider.render().cell_length == divider.size.width
                assert ":" in divider.render().plain

            for theme in ("ansi-dark", "textual-dark"):
                app.theme = theme
                user.scroll_visible(animate=False, immediate=True, top=True)
                await pilot.pause()
                divider = user.query_one(MessageDivider)
                rows = app.screen._compositor.render_strips()
                assert divider.region.x == user.region.x, "User divider is inset by an outer border"
                assert rows[divider.region.y].text[user.region.x] == "─"
                assert all(rows[y].text[user.region.x].isspace()
                           for y in range(user.region.y, divider.region.y)), (
                    "User accent must not extend above the divider", theme,
                )
                assert user.get_block_content("clipboard") == "human text"

            await app.open_comms_session(owner_mode=owner, project_path=root,
                                         me=app._main_session_screen(owner)._comms_thread,
                                         target="#all", kind="channel")
            chat = app.screen.query_one(CommsChatView)
            async with asyncio.timeout(5):
                while not any(message.seq == sent.seq for message, _ in chat._history):
                    await pilot.pause(.05)
            wire_block = next(widget for message, widget in chat._history
                              if message.seq == sent.seq)
            assert isinstance(wire_block, IRCMessage)
            assert len(wire_block.query(MessageDivider)) == 1
            expected_time = time.strftime("%H:%M:%S", time.localtime(sent.timestamp))
            inbound_divider = wire_block.query_one(MessageDivider)
            wire_block.scroll_visible(animate=False, immediate=True)
            await pilot.pause()
            assert expected_time in inbound_divider.render().plain, (
                expected_time, inbound_divider.clock, inbound_divider.size.width,
                inbound_divider.render().plain,
            )
            assert "Inbound" in wire_block.query_one(MessageDivider).render().plain
            outgoing_block = next(widget for message, widget in chat._history
                                  if message.seq == outbound.seq)
            assert "Outbound" in outgoing_block.query_one(MessageDivider).render().plain
            await chat.toggle_message_style()
            await pilot.pause()
            wire_block = next(widget for message, widget in chat._history
                              if message.seq == sent.seq)
            assert isinstance(wire_block, WireMarkdownMessage)
            assert len(wire_block.query(MessageDivider)) == 1
            assert len(wire_block.query(AgentResponse)) == 1
            assert len(wire_block.query(AgentResponse).first().query(MessageDivider)) == 0
            assert expected_time in wire_block.query_one(MessageDivider).render().plain
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("timestamped full-width user, inbound, agent and IRC/Markdown dividers; no thought divider")


if __name__ == "__main__":
    asyncio.run(main())
