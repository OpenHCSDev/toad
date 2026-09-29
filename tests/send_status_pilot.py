from toad.conversation_turn import AgentTurn, ClientTurn
"""Mounted sending feedback uses current queue IDs and preserves local drafts."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_comms.acp_extension import (
    AvailableQueueProjection,
    InputStartedUpdate,
    QueueChangedUpdate,
    QueueItem,
    QueueScope,
    encode_updates,
)
from agent_comms.thread_identity import OwnerIdentity, ThreadIncarnation
from runtime_fixture import ToadApp

AGENT = {
    "name": "Queue",
    "identity": "queue",
    "run_command": {"*": "true"},
    "protocol": "acp",
}


def update(fact):
    return {
        "sessionUpdate": "agent_message_chunk",
        "content": {"type": "text", "text": ""},
        "_meta": encode_updates(fact),
    }


from toad.acp.agent import Agent
from toad.widgets.prompt import QueueSummary, SendNow
from toad.widgets.user_input import UserInput


async def main():
    with TemporaryDirectory(prefix="toad-send-status-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(190, 40)) as pilot:
            await pilot.pause()
            view = app.selected_session.conversation
            agent = Agent(root, AGENT, "beta")
            agent.attach_surface(view)
            view.agent = agent
            await pilot.pause()
            view.agent_ready = True
            view.queue_supported = True
            entered, release = asyncio.Event(), asyncio.Event()

            async def send(*args, **kwargs):
                entered.set()
                await release.wait()

            # Pending local submission is visible before the transport returns.
            with patch.object(agent, "send_prompt", side_effect=send):
                for key in ("ctrl+enter", "ctrl+y"):
                    entered.clear()
                    release.clear()
                    view.turns.owner = AgentTurn()
                    view.prompt.text = "urgent follow-up"
                    view.prompt.focus()
                    await pilot.press(key)
                    await asyncio.wait_for(entered.wait(), 3)
                    await pilot.pause()
                    frame = "\n".join(
                        strip.text for strip in app.screen._compositor.render_strips()
                    )
                    assert "Sending next: urgent follow-up" in frame, frame
                    release.set()
                    async with asyncio.timeout(3):
                        while view.delivering_prompt:
                            await pilot.pause()
                    assert (
                        "Sending next"
                        not in view.query_one(QueueSummary).render().plain
                    )

            scope = QueueScope(
                "beta", OwnerIdentity(ThreadIncarnation("beta", 1.0), 1), 123
            )
            items = (QueueItem("a" * 32, "same text"), QueueItem("b" * 32, "same text"))
            token = agent.queue_attachment.begin("beta")
            agent.queue_attachment.bind(
                QueueChangedUpdate(scope, 1, AvailableQueueProjection(items)),
                "beta",
                token,
            )
            agent._post_queue_view()
            view.turns.owner = AgentTurn()
            view.agent_ready = True
            view.prompt.text = ""
            await pilot.pause()
            before = len(view.query(UserInput))
            # Scheduling acknowledges no consumption. Both equal-text rows stay
            # until a current inputStarted receipt identifies one exact input.
            with (
                patch.object(agent, "send_now", return_value=True),
                patch.object(agent, "send_prompt") as submit,
            ):
                for key in (None, "ctrl+enter", "ctrl+y"):
                    if key is None:
                        assert await pilot.click(SendNow)
                    else:
                        view.prompt.focus()
                        await pilot.press(key)
                    await pilot.pause()
                    assert (
                        "Send requested: same text"
                        in view.query_one(QueueSummary).render().plain
                    ), (
                        key,
                        view.query_one(QueueSummary).render().plain,
                        view.queue_projection,
                        view.queued_prompts,
                        view.queue_supported,
                        view.prompt.text,
                    )
                    assert len(view.queue_projection.items) == 2
                    submit.assert_not_called()
            agent.updates.accept(
                "beta", update(InputStartedUpdate("a" * 32, "same text", scope, 2))
            )
            agent.updates.accept(
                "beta",
                update(
                    QueueChangedUpdate(scope, 3, AvailableQueueProjection((items[1],)))
                ),
            )
            await pilot.pause()
            assert not view.sending_queued_prompt
            assert len(view.query(UserInput)) == before + 1
            assert [row.input_id for row in view.queue_projection.items] == ["b" * 32]
            view.prompt.text = "my unsent draft"
            for _ in range(2):
                agent.updates.accept(
                    "beta",
                    update(
                        QueueChangedUpdate(
                            scope, 4, AvailableQueueProjection((), (items[1],))
                        )
                    ),
                )
                await pilot.pause()
            assert view.prompt.text == "my unsent draft"
            assert (
                "Restored (1, read-only): same text"
                in view.query_one(QueueSummary).render().plain
            )
            assert app._exception is None
            await agent.stop()
    print(
        "PASS: shortcuts paint before transport, scheduling preserves exact rows, restoration preserves local draft"
    )


if __name__ == "__main__":
    asyncio.run(main())
