"""Thread replies retain explicit channel scope in both live and replay rendering."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import MessageRoute, TurnRouting, TranscriptEvent
from toad.acp.messages import Update, IncomingMessage as IncomingUpdate
from toad.app import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.incoming_message import IncomingSender
from toad.widgets.route_header import RouteHeader
from toad.widgets.transcript_history import transcript_blocks


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-routes-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            route = MessageRoute("worker", ("#openhcs",))
            conversation.post_message(Update("text", "Channel answer", route))
            await pilot.pause()
            response = conversation.query(AgentResponse).last()
            assert response.route == route and "[TO] #openhcs" in response.query_one(RouteHeader).render().plain
            conversation.post_message(Update("text", "Private answer"))
            await pilot.pause()
            assert conversation.query(AgentResponse).last().route is None
            replay = transcript_blocks((TranscriptEvent("assistant", "Saved channel answer", routing=TurnRouting(reply=route)),))[0]
            await conversation.post(replay)
            await pilot.pause()
            assert "[TO] #openhcs" in replay.query_one(RouteHeader).render().plain
            sent = transcript_blocks((TranscriptEvent("sent", "Visible sent body", routing=TurnRouting(reply=route)),))[0]
            await conversation.post(sent)
            await pilot.pause()
            assert sent.source == "Visible sent body" and "[TO] #openhcs" in sent.query_one(RouteHeader).render().plain
            for sequence, target, label in ((1, "#experiment", "#experiment"), (2, "worker", "direct message")):
                conversation.post_message(IncomingUpdate("user", target, "Incoming body", sequence))
                await pilot.pause()
                for width in (120, 70, 90):
                    await pilot.resize_terminal(width, 40)
                    conversation.window.anchor()
                    await pilot.pause()
                    region = conversation.query(IncomingSender).last().content_region
                    strips = app.screen._compositor.render_strips()
                    painted = " ".join(
                        strip.text[region.x:region.right] for strip in strips[region.y:region.bottom]
                    )
                    assert label in " ".join(painted.split()), (label, width, painted)
    print("reply routing: live/replayed channel scope and separate private replies passed")


if __name__ == "__main__":
    asyncio.run(main())
