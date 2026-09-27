"""Provider-free ACP generic permission prompt retirement and stale-event fence."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from runtime_fixture import ToadApp

from toad.answer import Answer
from toad.screens.main import MainScreen
from toad.screens.permissions import PermissionsScreen
from toad.widgets.question import Ask, Question


async def main() -> None:
    with TemporaryDirectory(prefix="toad-mcp-permission-ui-") as temp:
        root = Path(temp)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(140, 36)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            view = app.screen.conversation
            prompt = view.prompt
            option = Answer("Allow once", "yes", "allow_once")
            first = asyncio.get_running_loop().create_future()
            second = asyncio.get_running_loop().create_future()
            tool = {"toolCallId": "fixture", "kind": "execute", "title": "Fixture"}
            view.request_permissions(first, [option], tool)
            view.request_permissions(second, [option], tool)
            await pilot.pause(0.1)
            old_ask = prompt._ask
            assert old_ask is not None and len(prompt.ask_queue) == 1
            first.cancel()
            await pilot.pause(0.1)
            assert prompt._ask is not None and prompt._ask is not old_ask
            assert not prompt.ask_queue
            prompt.on_question_answer(Question.Answer(0, option, old_ask))
            assert not second.done(), (
                "Stale queued option must never select the next ask"
            )
            second.set_result(None)
            await pilot.pause(0.1)
            assert prompt._ask is None and not prompt.ask_queue
            chosen: list[str] = []
            original = Ask(
                "old", [option], callback=lambda answer: chosen.append(answer.id)
            )
            successor = Ask(
                "successor", [option], callback=lambda answer: chosen.append("WRONG")
            )
            prompt.ask(original)
            prompt.on_question_answer(Question.Answer(0, option, original))
            prompt.remove_ask(original)
            prompt.ask(successor)
            await pilot.pause(0.35)
            assert chosen == ["yes"] and prompt._ask is successor, (
                "Delayed timer removed a successor"
            )
            prompt.remove_ask(successor)

            # A diff permissions screen must also close when its controller times out.
            diff = asyncio.get_running_loop().create_future()
            diff_tool = {
                "toolCallId": "edit",
                "kind": "edit",
                "title": "Edit",
                "content": [
                    {
                        "type": "diff",
                        "path": str(root / "file.txt"),
                        "oldText": "old",
                        "newText": "new",
                    },
                ],
            }
            view.request_permissions(diff, [option], diff_tool)
            await pilot.pause(0.15)
            assert isinstance(app.screen, PermissionsScreen)
            diff.cancel()
            await pilot.pause(0.15)
            assert not isinstance(app.screen, PermissionsScreen)
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print(
        "ACP permission UI: cancelled requests retire and stale answers cannot select successors"
    )


if __name__ == "__main__":
    asyncio.run(main())
