"""Confirm native height answer reuse on the existing loaded Toad App."""

import ast
import asyncio
import cProfile
import json
import os
from pathlib import Path
import pstats
import statistics
import subprocess
import tempfile
from time import perf_counter

from agent_comms.comms import wire
from agent_comms.threads import Thread
from sidebar_collapse_latency_pilot import FrameApp
from textual.widget import Widget
from toad.widgets.agent_response import AgentResponse


def original_relative_property():
    source = subprocess.check_output(
        ["git", "show", "22f65423d:src/textual/widget.py"], text=True
    )
    owner = next(node for node in ast.parse(source).body
                 if isinstance(node, ast.ClassDef) and node.name == "Widget")
    function = next(node for node in owner.body
                    if isinstance(node, ast.FunctionDef) and node.name == "_has_relative_children_height")
    function.decorator_list = []
    module = ast.Module(body=[function], type_ignores=[])
    namespace = {}
    exec(compile(ast.fix_missing_locations(module), "original_widget.py", "exec"), namespace)
    return property(namespace[function.name])


async def main(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    current = Widget._has_relative_children_height
    original = original_relative_property()
    with tempfile.TemporaryDirectory(prefix="height-resource-", dir=output) as folder:
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
                responses = [AgentResponse(f"## Response {index}\n\n" + "paragraph\n\n" * 10)
                             for index in range(12)]
                await app.selected_session.conversation.contents.mount(*responses)
                await pilot.pause()
                results = {}
                for phase in ("loaded", "after_authored_response_burst"):
                    if phase == "after_authored_response_burst":
                        burst_start = perf_counter()
                        for index, response in enumerate(responses[-3:]):
                            await response.append(f"\n\nAuthored geometry continuation {index}.\n")
                        await pilot.pause()
                        burst_seconds = perf_counter() - burst_start
                        assert all("Authored geometry continuation" in response.source
                                   for response in responses[-3:])
                    widgets = tuple(app.screen.walk_children())
                    geometry = tuple(widget.region for widget in widgets)
                    Widget._has_relative_children_height = original
                    expected = tuple(widget._has_relative_children_height for widget in widgets)
                    timings = {"original": [], "retained": []}
                    profile_counts = {}
                    for trial in range(6):
                        for name, declaration in (("original", original), ("retained", current))[::1 if trial % 2 == 0 else -1]:
                            Widget._has_relative_children_height = declaration
                            profile = cProfile.Profile() if trial == 0 else None
                            if profile:
                                profile.enable()
                            start = perf_counter()
                            for _ in range(20):
                                assert tuple(widget._has_relative_children_height for widget in widgets) == expected
                            elapsed = perf_counter() - start
                            if profile:
                                profile.disable()
                                profile.dump_stats(str(output / f"{phase}-{name}.pstats"))
                                profile_counts[name] = {
                                    function: sum(value[1] for (_, _, entry), value in pstats.Stats(profile).stats.items()
                                                  if entry == function)
                                    for function in ("_has_relative_children_height", "_relative_children_height", "is_container")
                                }
                            else:
                                timings[name].append(elapsed)
                    Widget._has_relative_children_height = current
                    assert tuple(widget.region for widget in widgets) == geometry
                    results[phase] = {"widgets": len(widgets), "seconds": timings,
                                      "median_seconds": {name: statistics.median(values) for name, values in timings.items()},
                                      "profile_actual_calls": profile_counts,
                                      "answers_equal": True, "geometry_unchanged_during_queries": True}
                assert app._exception is None
                result = {"scope": "source App height queries and authored response geometry, not live frame latency",
                          "tabs": 10, "sweeps": 20, "phases": results,
                          "authored_burst_to_idle_seconds": burst_seconds,
                          "inputs": 0, "providers": 0}
                (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
                print(json.dumps(result, indent=2), flush=True)
        finally:
            Widget._has_relative_children_height = current


if __name__ == "__main__":
    import sys
    asyncio.run(main(Path(sys.argv[1])))
