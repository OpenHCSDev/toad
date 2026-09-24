"""Real ACP/Pi-RPC queue controls: Enter waits, Ctrl+Enter steers, no duplicate input."""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from agent_comms import wire
from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.prompt import QueueSummary, SendNow
from toad.widgets.user_input import UserInput


async def until(predicate):
    async with asyncio.timeout(20):
        while not predicate():
            await asyncio.sleep(0.05)


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-queue-") as directory:
        root = Path(directory)
        project = root / "project"
        project.mkdir()
        gate = root / "gate"
        gate.touch()
        delivery_gate = root / "delivery-gate"
        stub = root / "pi-queue"
        stub.write_text(f"#!{sys.executable}\n" + """
import json, os, queue, sys, threading
from pathlib import Path
from agent_comms import wire
commands = queue.Queue()
def reader():
    for line in sys.stdin:
        commands.put(json.loads(line))
    commands.put(None)
threading.Thread(target=reader, daemon=True).start()
def emit(value):
    print(json.dumps(value), flush=True)
def text(value):
    emit({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": value}})
def consume(command):
    emit({"type": "message_start", "message": {"role": "user", "content": [{"type": "text", "text": command["message"]}]}})
    text("Processed: " + command["message"].splitlines()[-1])
while True:
    command = commands.get()
    if command is None: break
    kind = command["type"]
    if kind == "prompt":
        comms = wire()
        thread = comms.registry.require(os.environ["PI_AGENT_ID"])
        if thread.auto_title_pending:
            comms.rename_self("queue-behavior")
            emit({"type": "tool_execution_end", "toolCallId": "title", "toolName": "comms_rename_self", "isError": False, "result": {"content": [{"type": "text", "text": "named"}]}})
        text("Original response begins")
        pending = []
        while Path(os.environ["TEST_QUEUE_GATE"]).exists():
            if pending and not Path(os.environ["TEST_QUEUE_DELIVERY_GATE"]).exists():
                for followup in pending: consume(followup)
                pending = []
            try: followup = commands.get(timeout=0.03)
            except queue.Empty: continue
            if followup is None: sys.exit(0)
            if followup.get("streamingBehavior") == "steer" and not Path(os.environ["TEST_QUEUE_DELIVERY_GATE"]).exists(): consume(followup)
            else: pending.append(followup)
        text(" Original response finished")
        for followup in pending: consume(followup)
        emit({"type": "agent_settled"})
    else:
        emit({"type": "response", "command": kind, "success": True, "data": {}})
""")
        stub.chmod(0o755)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
            AGENT_COMMS_AGENT_BIN=str(stub),
            AGENT_COMMS_AGENT_ARGS="--model test/base",
            AGENT_COMMS_AGENT_MODELS="test/base",
            TEST_QUEUE_GATE=str(gate),
            TEST_QUEUE_DELIVERY_GATE=str(delivery_gate),
        )
        agent = {
            "name": "Agent Comms",
            "identity": "queue-test",
            "short_name": "queue-test",
            "run_command": {"*": f"{sys.executable} -m agent_comms.acp"},
            "protocol": "acp",
        }
        app = ToadApp(agent_data=agent, project_dir=str(project))
        async with app.run_test(size=(120, 40)) as pilot:
            await until(
                lambda: getattr(app.screen, "conversation", None) is not None
                and app.screen.conversation.agent_ready
            )
            conversation = app.screen.conversation

            async def submit(text, key="enter"):
                conversation.prompt.text = text
                conversation.prompt.focus()
                await pilot.pause()
                await pilot.press(key)

            await submit(
                "Hey can you please help with message queue behavior in this harness?"
            )
            await until(
                lambda: any(
                    "Original response begins" in b.source
                    for b in conversation.query(AgentResponse)
                )
            )
            await until(
                lambda: app.session_tracker.get_session(app.current_mode).title
                == "queue behavior"
            )
            assert (
                wire(root / "wire").registry.require("project").name == "queue-behavior"
            )
            delivery_gate.touch()
            await submit("queued follow-up")
            await until(lambda: conversation.queued_prompts == ["queued follow-up"])
            assert "Queued (1): queued follow-up" in conversation.query_one(QueueSummary).render().plain
            await pilot.click(SendNow)
            await pilot.pause()
            frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "Sending next: queued follow-up" in frame
            assert "Queued (1): queued follow-up" not in frame
            assert not any("Processed: queued follow-up" in b.source for b in conversation.query(AgentResponse))
            await pilot.click(SendNow)
            delivery_gate.unlink()
            # Enter now steers at the next boundary instead of waiting for the
            # whole run; it must still be delivered exactly once.
            await until(
                lambda: any(
                    "Processed: queued follow-up" in b.source
                    for b in conversation.query(AgentResponse)
                )
            )
            assert conversation.delivering_prompt == ""
            assert conversation.sending_queued_prompt == ""
            assert "Sending next: queued follow-up" not in conversation.query_one(
                QueueSummary
            ).render().plain
            assert (
                sum(
                    "queued follow-up" in b.source
                    for b in conversation.query(AgentResponse)
                )
                == 1
            )
            await submit("urgent steering", "ctrl+enter")
            await until(
                lambda: any(
                    "Processed: urgent steering" in b.source
                    for b in conversation.query(AgentResponse)
                )
            )
            await submit("terminal steering", "ctrl+y")
            await until(
                lambda: any(
                    "Processed: terminal steering" in b.source
                    for b in conversation.query(AgentResponse)
                )
            )
            conversation.prompt.text = "line-feed draft"
            conversation.prompt.focus()
            await pilot.press("ctrl+j")
            await pilot.pause()
            assert conversation.prompt.text == "line-feed draft\n"
            conversation.prompt.text = ""
            gate.unlink()
            await until(
                lambda: not conversation.queued_prompts
                and conversation.turn == "client"
            )
            assert conversation.delivering_prompt == ""
            assert (
                sum(
                    "queued follow-up" in b.content
                    for b in conversation.query(UserInput)
                )
                == 1
            )
            assert (
                sum(
                    "urgent steering" in b.content
                    for b in conversation.query(UserInput)
                )
                == 1
            )
            assert (
                sum(
                    "terminal steering" in b.content
                    for b in conversation.query(UserInput)
                )
                == 1
            )
            assert not any("line-feed draft" in b.content for b in conversation.query(UserInput))
            assert wire(root / "wire").full_history() == []
            gate.touch()
            await submit("another running turn")
            await until(lambda: conversation.turn == "agent")
            await submit("delivered while running")
            await until(
                lambda: any(
                    "Processed: delivered while running" in b.source
                    for b in conversation.query(AgentResponse)
                )
            )
            # Steering delivers once; cancellation must not duplicate or queue it.
            assert (
                sum(
                    "delivered while running" in b.source
                    for b in conversation.query(AgentResponse)
                )
                == 1
            )
            await conversation.agent.cancel()
            await until(lambda: conversation.turn == "client")
            assert not conversation.queued_prompts
    print(
        "prompt queue: concise title, next-boundary steering, single delivery and clean cancellation passed"
    )


if __name__ == "__main__":
    asyncio.run(main())
