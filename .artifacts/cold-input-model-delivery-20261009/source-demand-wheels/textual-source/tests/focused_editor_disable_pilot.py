"""Measure the real focused compose-disable boundary without submitting input.

Uses the existing loaded sidebar App fixture and original PromptTextArea. This
is source App confirmation, not installed channel delivery or terminal latency.
"""
import asyncio
import cProfile
import json
import os
from pathlib import Path
import pstats
import tempfile
from time import perf_counter

from agent_comms.comms import wire
from agent_comms.threads import Thread
from sidebar_collapse_latency_pilot import FrameApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.prompt import Prompt


async def main(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="focus-editor-disable-", dir=output) as folder:
        root = Path(folder)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        comms = wire(root / "wire")
        comms.registry.declare(Thread(root.name, frozenset(), str(root)))
        for index in range(24):
            comms.registry.declare(Thread(f"worker-{index:02}", frozenset(), str(root)))
        app = FrameApp(project_dir=str(root))
        async with app.run_test(size=(120, 42)) as pilot:
            await pilot.pause()
            for _ in range(9):
                await app.session_navigation.new(app.session_navigation.default_source)
            conversation = app.selected_session.conversation
            await conversation.contents.mount(*[
                AgentResponse(f"## Loaded response {index}\n\n" + "paragraph and line\n\n" * 10)
                for index in range(12)
            ])
            await pilot.pause()
            editor = app.selected_session.query_one(Prompt).prompt_text_area
            editor.text = "original unsent draft"
            editor.focus(scroll_visible=False)
            await pilot.pause()
            assert app.screen.focused is editor
            profile = cProfile.Profile()
            started = perf_counter()
            profile.enable()
            editor.disabled = True
            profile.disable()
            elapsed = perf_counter() - started
            profile.dump_stats(str(output / "disable.pstats"))
            assert editor.disabled and app.screen.focused is not editor
            assert editor.text == "original unsent draft"
            calls = {
                name: sum(values[1] for (_, _, function), values in pstats.Stats(profile).stats.items()
                          if function == name)
                for name in ("_reset_focus", "_focus_sort_key", "acquire_geometry",
                             "reflow_visible", "_arrange_root")
            }
            await pilot.pause()
            assert app._exception is None
            result = dict(boundary="source synchronous focused PromptTextArea.disabled watcher",
                          disabled_seconds=elapsed, calls=calls, tabs=10,
                          active_widgets=len(app.screen.query("*")),
                          inputs_submitted=0, provider_calls=0, draft_preserved=True)
            print(json.dumps(result, indent=2), flush=True)
            (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    import sys
    asyncio.run(main(Path(sys.argv[1])))
