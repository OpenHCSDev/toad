"""Exercise participant paint metadata in the existing loaded source Toad App.

No participant/backend input is submitted. This measures native layout admission,
not installed terminal latency or provider delivery.
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
from textual.content import Content
from textual.style import Style
from toad.widgets.channel_participants import ChannelParticipants
from toad.widgets.prompt import Prompt


async def main(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="participant-content-", dir=output) as folder:
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
            for _ in range(9):
                await app.session_navigation.new(app.session_navigation.default_source)
            participants = ChannelParticipants()
            await app.selected_session.query_one(Prompt).mount(
                participants, before="#prompt-container"
            )
            names = participants.names
            names.update(Content("Active: worker-00"))
            await pilot.pause()
            revision = names._geometry_revision
            region = names.region
            replacement = Content.styled("Active: worker-00", "$warning").stylize(
                Style.from_meta({"@click": ("open_thread", ("worker-00",))})
            )
            profile = cProfile.Profile()
            start = perf_counter()
            profile.enable()
            names.update(replacement)
            profile.disable()
            elapsed = perf_counter() - start
            assert names._geometry_revision == revision
            assert not names._layout_required
            await pilot.pause()
            assert names.region == region and names.region.area
            assert names.visual.is_same(replacement)
            style = app.screen._compositor.get_style_at(region.x, region.y)
            assert style.meta["@click"] == ("open_thread", ("worker-00",))
            assert app._exception is None
            profile.dump_stats(str(output / "update.pstats"))
            calls = {name: sum(values[1] for (_, _, function), values in pstats.Stats(profile).stats.items()
                               if function == name)
                     for name in ("_invalidate_layout", "_request_layout", "_arrange_root")}
            result = dict(boundary="source Toad ParticipantNames Static.update paint-only admission",
                          update_seconds=elapsed, calls=calls, tabs=10,
                          active_widgets=len(app.screen.query("*")),
                          geometry_preserved=True, painted_action_metadata=True,
                          inputs_submitted=0, provider_calls=0)
            print(json.dumps(result, indent=2), flush=True)
            (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    import sys
    asyncio.run(main(Path(sys.argv[1])))
