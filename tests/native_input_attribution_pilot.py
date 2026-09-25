"""Owner-bound native inputs keep the same FROM/TO presentation live and saved."""

import asyncio
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from agent_comms import MessageRoute, Thread, TurnRouting, wire
from agent_comms.declarations import ScheduledTurn
from agent_comms.input_disposition import InputDispositions
from runtime_fixture import ToadApp

from toad.acp.agent import Agent
from toad.acp.messages import TranscriptSnapshot
from toad.widgets.agent_response import AgentResponse
from toad.widgets.incoming_message import IncomingMessage
from toad.widgets.route_header import RouteHeader
from toad.widgets.user_input import UserInput


async def main(*, historical: bool) -> None:
    with tempfile.TemporaryDirectory(prefix="toad-native-attribution-") as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"), XDG_STATE_HOME=str(root / "state"),
        )
        comms = wire(root / "wire")
        session = root / "native.jsonl"
        for name in ("owner", "peer"):
            comms.register(Thread(name, frozenset(), str(root)))
        comms.attach_session("owner", str(session))
        incoming = comms.send_message("peer", "owner", "Incoming peer body")
        outgoing = comms.send_message("owner", "peer", "Outgoing peer body")
        prompt = ScheduledTurn.incoming(incoming).prompt
        human = "[agent-comms from example to owner]\nA human quoting a header"
        comms.record_input_display("a" * 32, human, sent_text=human)
        if historical:
            comms.record_input_display("b" * 32, prompt)
            ledger = InputDispositions(comms.root)
            key = f"bus:{incoming.seq}"
            ledger.record(key, seq=incoming.seq, owner="owner", admission=1,
                          target="owner", text=prompt)
            ledger.bind(key, admission=1, turn_id="old-turn", native_id="b" * 32, text=prompt)
            assert comms.repair_input_routing()["eligible"] == 1
            assert comms.repair_input_routing(dry_run=False)["repaired"] == 1
            assert ledger.status(key) == "unknown", "Display repair is not an input ACK"
        else:
            comms.record_input_display("b" * 32, prompt, sent_text=prompt,
                                       routing=TurnRouting((incoming,), None))
        records = [
            {"type": "message", "id": "human", "message": {
                "role": "user", "inputId": "a" * 32, "content": human}},
            {"type": "message", "id": "inbound", "message": {
                "role": "user", "inputId": "b" * 32, "content": prompt}},
            {"type": "message", "id": "outbound", "message": {
                "role": "toolResult", "toolName": "comms_send", "toolCallId": "send",
                "isError": False, "content": [{"type": "text", "text": json.dumps({
                    "id": outgoing.message_id, "message": outgoing.to_wire()})}]}},
        ]
        session.write_text("".join(json.dumps(record) + "\n" for record in records))
        page = wire(comms.root).thread_transcript_page("owner")
        pending = comms.pending_count("owner")
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            agent = Agent(root, {"name": "Fixture", "identity": "fixture",
                                 "run_command": {"*": "true"}}, "owner")
            agent._message_target = view
            agent.rpc_session_update("owner", {
                "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": ""},
                "_meta": {"agentComms": {"incoming": {
                    "sender": incoming.sender, "target": incoming.target,
                    "body": incoming.body, "sequence": incoming.seq,
                }}},
            })
            route = MessageRoute("owner", ("peer",))
            agent.rpc_session_update("owner", {
                "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": outgoing.body},
                "_meta": {"agentComms": {"route": asdict(route)}},
            })
            await pilot.pause()
            live_in = view.contents.query_one(IncomingMessage)
            live_out = next(block for block in view.contents.query(AgentResponse) if block.route is not None)
            live_headers = (live_in.query_one(RouteHeader).render().plain,
                            live_out.query_one(RouteHeader).render().plain)
            await view.contents.remove_children()
            view.post_message(TranscriptSnapshot(page.events, page))
            await pilot.pause()
            received = view.contents.query_one(IncomingMessage)
            sent = next(block for block in view.contents.query(AgentResponse) if block.route is not None)
            assert received.sender == "peer" and received.text == incoming.body
            assert sent.source == outgoing.body and sent.route == route
            assert (received.query_one(RouteHeader).render().plain,
                    sent.query_one(RouteHeader).render().plain) == live_headers
            assert [block.content for block in view.contents.query(UserInput)] == [human]
            copied = received.get_block_content("clipboard")
            assert "peer" in copied and incoming.body in copied
            assert "[agent-comms from" not in copied
            assert comms.pending_count("owner") == pending
            view.in_out_only = True
            await pilot.pause()
            frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "[FROM]" in frame and "[TO]" in frame
            assert incoming.body in frame and outgoing.body in frame
            assert "A human quoting" not in frame
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print(f"native attribution: live/saved FROM/TO agree, human quotes preserved, historical={historical}")


if __name__ == "__main__":
    asyncio.run(main(historical=False))
    asyncio.run(main(historical=True))
