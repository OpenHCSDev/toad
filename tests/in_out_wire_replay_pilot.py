"""Saved native wire inputs must keep FROM attribution alongside send receipts."""

import asyncio
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import tempfile

from agent_comms import Thread, TurnRouting, wire
from agent_comms.declarations import ScheduledTurn
from runtime_fixture import ToadApp
from toad.acp.messages import TranscriptSnapshot
from toad.widgets.agent_response import AgentResponse
from toad.widgets.incoming_message import IncomingMessage
from toad.widgets.route_header import RouteHeader


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-in-out-replay-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"), AGENT_COMMS_ROOT=str(root / "wire"))
        comms = wire(root / "wire")
        transcript = root / "session.jsonl"
        comms.register(Thread("owner", frozenset(), str(root), session_file=str(transcript)))
        comms.register(Thread("peer", frozenset(), str(root)))
        incoming = comms.send_message("peer", "owner", "INBOUND_FROM_REAL_WIRE")
        outgoing = comms.send_message("owner", "peer", "OUTBOUND_FROM_REAL_RECEIPT")
        transcript.write_text("\n".join(json.dumps(record) for record in (
            {"type": "message", "id": "wire-user",
             "timestamp": datetime.fromtimestamp(incoming.timestamp + .001, UTC).isoformat(),
             "message": {
                "role": "user", "content": [{"type": "text", "text": ScheduledTurn.incoming(incoming).prompt}]}},
            {"type": "message", "id": "send-result", "message": {
                "role": "toolResult", "toolCallId": "send", "toolName": "comms_send", "isError": False,
                "content": [{"type": "text", "text": json.dumps({"id": outgoing.message_id,
                                                                         "message": outgoing.to_wire()})}]}},
        )) + "\n")
        if os.environ.get("TOAD_TEST_ANNOTATED") == "1":
            comms.transcript_routes.record(str(transcript), ("wire-user",), TurnRouting((incoming,), None))
        page = comms.thread_transcript_page("owner")
        assert any(event.kind == "sent" and event.routing and event.routing.reply for event in page.events)
        inbound = [event for event in page.events if event.kind == "user" and event.routing
                   and event.routing.requests]
        assert inbound, (
            "Saved wire input lost typed routing before the UI filter: "
            + repr([(event.kind, event.routing is not None) for event in page.events]))
        assert inbound[0].routing.requests[0].message_id == incoming.message_id
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            view.in_out_only = True
            view.post_message(TranscriptSnapshot(page.events, page))
            await pilot.pause()
            received = next(block for block in view.query(IncomingMessage)
                            if block.text == incoming.body)
            sent = next(block for block in view.query(AgentResponse)
                        if block.route is not None and block.source == outgoing.body)
            assert received.display and sent.display
            assert "[FROM]" in received.query_one(RouteHeader).render().plain
            assert "[TO]" in sent.query_one(RouteHeader).render().plain
            frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "[FROM]" in frame and "[TO]" in frame, frame
            assert incoming.body in frame and outgoing.body in frame, frame
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("in/out wire replay: committed incoming FROM and outgoing TO survive native-history normalization")


if __name__ == "__main__":
    asyncio.run(main())
