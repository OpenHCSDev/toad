"""Complete a thread mention while preserving shared-channel delivery and the draft."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import Thread, wire
from toad.app import ToadApp
from toad.widgets.channel_prompt import ChannelPrompt
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.irc_message import IRCMessage


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-mentions-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"),
        )
        comms = wire(root / "wire")
        for name in ("alpha", "beta"):
            comms.register(Thread(name, frozenset({"team"}), str(root)))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            owner = app.current_mode
            mode = await app.open_comms_session(
                owner_mode=owner, project_path=root, me="alpha", target="#team", kind="channel",
            )
            await pilot.pause()
            chat = app.screen.query_one(CommsChatView)
            prompt = chat.query_one(ChannelPrompt)
            prompt.text = "Can @al"
            prompt.focus()
            await pilot.pause()
            assert prompt.mention_list.display
            await pilot.press("tab")
            await pilot.pause()
            assert prompt.text == "Can @alpha "
            prompt.text += "review this?"
            await pilot.press("enter")
            await pilot.pause()
            history = comms.channel_history("#team")
            assert len(history) == 1 and history[0].target == "#team"
            assert history[0].mentions[0].thread == "alpha"
            assert len(comms.inbox("alpha")) == len(comms.inbox("beta")) == 1
            rendered = chat.query_one(IRCMessage).mentioned_body()
            assert "@alpha" in rendered.plain and rendered.spans
            prompt.text = "@"
            prompt.focus()
            await pilot.pause()
            await pilot.press("down", "tab")
            await pilot.pause()
            assert prompt.text == "@beta "
            prompt.text = "Keep @al"
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app.current_mode == mode and prompt.text == "Keep @al"
            assert not prompt.mention_list.display
    print("mentions: completion, keyboard choice, dismissal, highlighting, and shared delivery passed")


if __name__ == "__main__":
    asyncio.run(main())
