"""Category changes should target message owners, not restyle the whole view."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import statistics
import tempfile
import time
from unittest.mock import patch

from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from toad.widgets.message_filter import ALL_CATEGORIES, MessageCategory


async def main(baseline):
    with tempfile.TemporaryDirectory(prefix="toad-filter-latency-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(130, 43)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            await view.contents.mount(*[
                cls(f"## Record {index}\n\n" + "A paragraph of ordinary text.\n\n" * 5)
                for index in range(30) for cls in (AgentResponse, AgentThought)
            ])
            await pilot.pause()
            times = []
            with patch.object(app, "update_styles", wraps=app.update_styles) as styles:
                for _ in range(4):
                    for selected in (ALL_CATEGORIES - {MessageCategory.THINKING}, ALL_CATEGORIES):
                        before = time.thread_time()
                        view.visible_categories = selected
                        times.append((time.thread_time() - before) * 1000)
                        await pilot.pause()
                whole_view = sum(call.args == (view,) for call in styles.call_args_list)
            print(json.dumps({"boundary": "synchronous filter handler CPU, not frame latency",
                              "widgets": len(list(view.walk_children())),
                              "median_ms": round(statistics.median(times), 2), "max_ms": round(max(times), 2),
                              "whole_conversation_restyles": whole_view}))
            if not baseline:
                assert whole_view == 0, "Category change restyled unrelated descendants"
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true")
    asyncio.run(main(parser.parse_args().baseline))
