"""Measure a useful cold channel frame, not just its route/loading frame."""
from toad.navigation_target import NavigationContext

from toad.navigation_target import channel_target

import asyncio
import os
from pathlib import Path
import statistics
import tempfile
import time

from agent_comms.child_process import ProcessIdentity
from agent_comms.threads import Thread
from agent_comms.comms import wire
from runtime_fixture import ToadApp
from toad.widgets.comms_chat import CommsChatView, session_thread_name
from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.prompt import Prompt


class SceneProbe(ToadApp):
    pending = None
    target = None

    def _display(self, screen, renderable):
        result = super()._display(screen, renderable)
        if (self.pending is not None and not self.pending.done()
                and renderable is not None and not self._batch_count
                and screen is self.screen and getattr(screen, "target", None) == self.target):
            chat = screen.query_one_optional(CommsChatView)
            sidebar = screen.query_one_optional(CommsSidebar)
            if (chat is not None and chat.message_history.initialized and chat.message_history.rows
                    and sidebar is not None and sidebar.navigation_ready.is_set()
                    and chat.prompt.agent_ready):
                self.pending.set_result(time.perf_counter())
        return result


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-scene-latency-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_DATA_HOME=str(root / "data"), XDG_STATE_HOME=str(root / "state"))
        comms = wire(root / "wire")
        me = session_thread_name(root)
        comms.registry.declare(Thread(me, frozenset({"fixture"}), str(root), process_identity=ProcessIdentity.capture(os.getpid())))
        targets = [f"#scene-{index}" for index in range(6)]
        for target in targets:
            comms.channels.create_tag(target.removeprefix("#"))
            comms.messaging.send(me, target, "Scene history marker\n" + "message body " * 20)
        app = SceneProbe(project_dir=str(root))
        samples = []
        sizes = []
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            owner = app.selected_mode
            for target in targets:
                app.target = target
                app.pending = asyncio.get_running_loop().create_future()
                started = time.perf_counter()
                await channel_target(target).open(NavigationContext(app, owner, root, me))
                samples.append((await asyncio.wait_for(app.pending, 8) - started) * 1000)
                sizes.append(len(list(app.screen.query_one(Prompt).walk_children())))
                assert app.screen.query_one(CommsChatView).message_history.rows[0][0].body.startswith("Scene history marker")
                await app.switch_mode(owner)
                await pilot.pause()
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
        print({"boundary": "headless useful-frame post-_display, not terminal presentation",
               "channels": len(samples), "prompt_descendants": sizes,
               "median_ms": round(statistics.median(samples), 2),
               "worst_ms": round(max(samples), 2),
               "samples_ms": [round(sample, 2) for sample in samples]})


if __name__ == "__main__":
    asyncio.run(main())
