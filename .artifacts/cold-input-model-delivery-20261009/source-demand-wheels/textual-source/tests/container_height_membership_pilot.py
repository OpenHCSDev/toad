"""Measure native relative-height queries on the existing loaded Toad App."""

import asyncio
import cProfile
import json
import os
from pathlib import Path
import pstats
import statistics
import tempfile
from time import perf_counter

from agent_comms.comms import wire
from agent_comms.threads import Thread
from sidebar_collapse_latency_pilot import FrameApp
from textual.widget import Widget
from toad.widgets.agent_response import AgentResponse


async def main(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    current = Widget.is_container
    # The original property differs only in short-circuit order. Both versions
    # use the same actual native NodeList and RenderStyles on this acquired App.
    original = property(lambda self: self.styles.layout is not None or bool(self._nodes))
    with tempfile.TemporaryDirectory(prefix="height-membership-", dir=output) as folder:
        root = Path(folder)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        comms = wire(root / "wire")
        comms.registry.declare(Thread(root.name, frozenset(), str(root)))
        for index in range(24):
            comms.registry.declare(Thread(f"worker-{index:02}", frozenset(), str(root)))
        app = FrameApp(project_dir=str(root))
        try:
            async with app.run_test(size=(120, 42)) as pilot:
                for _ in range(9):
                    await app.session_navigation.new(app.session_navigation.default_source)
                await app.selected_session.conversation.contents.mount(*[
                    AgentResponse(f"## Response {index}\n\n" + "paragraph\n\n" * 10)
                    for index in range(12)
                ])
                await pilot.pause()
                widgets = tuple(app.screen.walk_children())
                expected = tuple(widget._has_relative_children_height for widget in widgets)
                geometry = tuple(widget.region for widget in widgets)
                timings = {"original": [], "membership_first": []}
                profiles = {}
                for trial in range(6):
                    for name, declaration in (("original", original), ("membership_first", current))[::1 if trial % 2 == 0 else -1]:
                        Widget.is_container = declaration
                        profile = cProfile.Profile() if trial == 0 else None
                        if profile:
                            profile.enable()
                        start = perf_counter()
                        for _ in range(20):
                            assert tuple(widget._has_relative_children_height for widget in widgets) == expected
                        elapsed = perf_counter() - start
                        if profile:
                            profile.disable()
                            profile.dump_stats(str(output / f"{name}.pstats"))
                            profiles[name] = {
                                "is_container_seconds": sum(value[2] for (_, _, function), value in pstats.Stats(profile).stats.items()
                                                            if function in {"is_container", "<lambda>"}),
                                "relative_height_seconds": sum(value[3] for (_, _, function), value in pstats.Stats(profile).stats.items()
                                                               if function == "_has_relative_children_height"),
                            }
                        else:
                            timings[name].append(elapsed)
                Widget.is_container = current
                await pilot.pause()
                assert tuple(widget.region for widget in widgets) == geometry
                assert app._exception is None
                result = {"scope": "source Toad App recursive height queries, not burst/frame latency",
                          "widgets": len(widgets), "tabs": 10, "sweeps_per_trial": 20,
                          "seconds": timings,
                          "median_seconds": {name: statistics.median(values) for name, values in timings.items()},
                          "profiles": profiles, "all_relative_answers_equal": True,
                          "geometry_unchanged": True, "inputs": 0, "providers": 0}
                (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
                print(json.dumps(result, indent=2), flush=True)
        finally:
            Widget.is_container = current


if __name__ == "__main__":
    import sys
    asyncio.run(main(Path(sys.argv[1])))
