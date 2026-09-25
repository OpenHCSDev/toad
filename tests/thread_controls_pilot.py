"""Real ACP integration for models, goal lifecycle, and routed IRC tabs."""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from agent_comms import Thread
from agent_comms.operations import wire
from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.comms_sidebar import CommsRow
from toad.widgets.comms_menu import ContextMenu, ContextMenuItem
from toad.widgets.goal_bar import GoalBar
from toad.widgets.irc_message import IRCMessage, IRCMessageText
from toad.widgets.prompt import AgentInfo


async def until(predicate):
    async with asyncio.timeout(15):
        while not predicate():
            await asyncio.sleep(0.05)


async def click_target(app, pilot, target):
    """Click the rendered routing span, including when the header wraps."""
    for row in app.screen.query(IRCMessage):
        if target not in {row.message.sender, row.message.target}:
            continue
        row.scroll_visible(animate=False)
        await pilot.pause()
        text = row.query_one(IRCMessageText)
        for y in range(text.size.height):
            x = 0
            for segment in text.render_line(y):
                if segment.style and segment.style.meta.get("@click") == (
                    "open_target",
                    (target,),
                ):
                    assert await pilot.click(text, offset=(x, y))
                    return
                x += segment.cell_length
    raise AssertionError(f"No clickable routing span for {target}")


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-controls-") as directory:
        root = Path(directory)
        project = root / "project"
        project.mkdir()
        gate = root / "goal-gate"
        stub = root / "pi-controls"
        stub.write_text(f"#!{sys.executable}\n" + """
import json, os, re, sys, time
from pathlib import Path
from agent_comms.operations import wire
def emit(data):
    print(json.dumps(data), flush=True)
model = sys.argv[sys.argv.index("--model") + 1]
provider = sys.argv[sys.argv.index("--provider") + 1]
thinking = sys.argv[sys.argv.index("--thinking") + 1]
for line in sys.stdin:
    command = json.loads(line)
    kind = command["type"]
    data = {}
    if kind == "get_state":
        data = {"model": {"provider": provider, "id": model}, "thinkingLevel": thinking,
                "nativeInputProofCapability": "pi-native-input-v1-live-only"}
    elif kind == "set_model":
        provider, model = command["provider"], command["modelId"]
    elif kind == "prompt":
        emit({"type": "response", "id": command.get("id"), "command": kind, "success": True})
        emit({"type": "message_start", "message": {"role": "user",
              "content": command["message"], "inputId": command["inputId"]}})
        emit({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "ordinary assistant reply"}})
        goal = re.search(r"Persistent goal ([a-f0-9]+):", command["message"])
        if goal:
            while Path(os.environ["TEST_GOAL_GATE"]).exists():
                time.sleep(0.05)
            wire().update_goal(os.environ["AGENT_COMMS_THREAD"], "completed", goal_id=goal[1], progress="Verified the objective")
        emit({"type": "message_end", "message": {"role": "assistant", "stopReason": "stop"}})
        emit({"type": "agent_settled"})
        continue
    emit({"type": "response", "id": command.get("id"), "command": kind, "success": True, "data": data})
""")
        stub.chmod(0o755)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
            AGENT_COMMS_AGENT_BIN=str(stub),
            AGENT_COMMS_AGENT_ARGS="--provider test --model one",
            AGENT_COMMS_AGENT_MODELS="test/one,test/two",
            TEST_GOAL_GATE=str(gate),
        )
        comms = wire(root / "wire")
        transcript = root / "peer.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "message",
                    "message": {"role": "assistant", "content": "Saved peer response"},
                }
            )
            + "\n"
        )
        for name in ("alice", "bob"):
            comms.register(
                Thread(
                    name=name,
                    tags=frozenset(),
                    worktree=str(project),
                    session_file=str(transcript),
                )
            )
        comms.send("alice", "bob", "explicit private coordination")
        comms.send("bob", "#all", "explicit channel coordination")
        agent = {
            "name": "Agent Comms",
            "identity": "test-comms",
            "short_name": "test-comms",
            "run_command": {"*": f"{sys.executable} -m agent_comms.acp"},
            "protocol": "acp",
        }
        app = ToadApp(agent_data=agent, project_dir=str(project))
        async with app.run_test(size=(120, 40)) as pilot:
            await until(
                lambda: getattr(app.screen, "conversation", None) is not None
                and app.screen.conversation.agent_ready
            )
            parent_mode = app.current_mode
            conversation = app.screen.conversation
            await until(lambda: conversation.current_model is not None)
            assert (
                conversation.prompt.query_one(AgentInfo).render().plain
                == "test/one · medium"
            )
            assert await pilot.click(conversation.prompt.query_one(AgentInfo))
            await pilot.pause()
            assert conversation.prompt.model_switcher.search_input.has_focus
            await pilot.press("t", "w", "o", "enter")
            await until(lambda: conversation.current_model.id == "test/two")
            await until(lambda: isinstance(app.screen, ContextMenu))
            high = next(
                item
                for item in app.screen.query(ContextMenuItem)
                if item.action == "high"
            )
            assert await pilot.click(high)
            await until(lambda: conversation.thinking_level == "high")
            assert comms.registry.require("project").model == "test/two"
            assert comms.registry.require("project").thinking_level == "high"
            assert (
                conversation.prompt.query_one(AgentInfo).render().plain
                == "test/two · high"
            )
            conversation.prompt.text = "A regular prompt"
            conversation.prompt.focus()
            await pilot.pause()
            await pilot.press("enter")
            await until(
                lambda: any(
                    "ordinary assistant reply" in b.source
                    for b in conversation.query(AgentResponse)
                )
            )
            assert all(
                "ordinary assistant reply" not in m.body for m in comms.full_history()
            )
            await until(lambda: conversation.turn != "agent")
            gate.touch()
            assert await conversation.slash_command("/goal Complete the objective")
            await until(lambda: conversation.turn == "agent")
            await conversation.refresh_goal()
            assert conversation.query_one(GoalBar).display
            await conversation.slash_command("/goal pause")
            assert comms.registry.require("project").goal.status == "paused"
            gate.unlink()
            await conversation.slash_command("/goal resume")
            await until(
                lambda: comms.registry.require("project").goal.status == "completed"
            )
            await conversation.refresh_goal()
            assert conversation.goal.progress == "Verified the objective"
            any_row = next(
                row for row in app.screen.query(CommsRow) if row.target_name == "#any"
            )
            any_row.scroll_visible(animate=False)
            await pilot.pause()
            assert await pilot.click(any_row)
            await until(lambda: len(list(app.screen.query(IRCMessage))) == 2)
            irc_mode = app.current_mode
            assert app.screen.target == "#any" and app.screen.kind == "irc"
            assert next(
                row for row in app.screen.query(CommsRow) if row.target_name == "#any"
            ).selected
            assert not next(
                row for row in app.screen.query(CommsRow) if row.target_name == "#all"
            ).selected
            assert not app.screen.query(AgentResponse)
            chat = app.screen.query_one(CommsChatView)
            assert "explicit private coordination" in [
                m.source for m in chat.query(IRCMessage)
            ]
            await click_target(app, pilot, "alice")
            await until(
                lambda: app.current_mode != irc_mode
                and app.screen.conversation.agent_ready
            )
            alice_mode = app.current_mode
            await app.switch_mode(irc_mode)
            await pilot.pause()
            await click_target(app, pilot, "bob")
            await until(
                lambda: app.current_mode != irc_mode
                and app.screen.conversation.agent_ready
            )
            bob_mode = app.current_mode
            assert alice_mode != bob_mode
            await app.switch_mode(irc_mode)
            await pilot.pause()
            await click_target(app, pilot, "alice")
            await until(lambda: app.current_mode == alice_mode)
            assert app.session_tracker.session_count == 3
            assert {
                thread.name for thread in comms.registry.all_threads().values()
                if thread.role.executable
            } == {"alice", "bob", "project"}
            await app.switch_mode(irc_mode)
            await pilot.pause()
            await click_target(app, pilot, "#all")
            await until(
                lambda: app.current_mode != irc_mode
                and bool(app.screen.query(IRCMessage))
            )
            assert [row.source for row in app.screen.query(IRCMessage)] == [
                "explicit channel coordination"
            ]
            await pilot.press("ctrl+g")
            await until(lambda: app.current_mode == irc_mode)
            comms.send("bob", "alice", "live direct coordination")
            await until(
                lambda: any(
                    row.source == "live direct coordination"
                    for row in app.screen.query(IRCMessage)
                )
            )
            assert len(list(app.screen.query(IRCMessage))) == 3
            assert (
                "#all (broadcast)"
                in app.screen.query_one(CommsChatView).prompt.simple_placeholder
            )
            await app.switch_mode(parent_mode)
            await conversation.refresh_goal()
            assert conversation.goal.status == "completed"
            await conversation.slash_command("/goal clear")
            assert comms.registry.require("project").goal is None
    print(
        "thread controls: model selection, goal lifecycle, IRC routing and reuse passed"
    )


if __name__ == "__main__":
    asyncio.run(main())
