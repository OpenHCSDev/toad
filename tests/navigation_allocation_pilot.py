"""Repeat the fixed many-tab workload and census retained measurements afterward."""

import argparse
from contextlib import asynccontextmanager
import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import many_tabs_return_pilot as workload
from textual.widget import Widget


async def main(output):
    original = workload.ReturnApp.run_test
    census = {}

    @asynccontextmanager
    async def observed(app, **kwargs):
        async with original(app, **kwargs) as pilot:
            yield pilot
            # All timed navigation has finished. Count keys directly instead of
            # walking the GC heap or forcing collection during measurements.
            counts = {"current": 0, "obsolete": 0}
            widgets = [node for node in app._registry if isinstance(node, Widget)]
            for widget in widgets:
                current = (widget._layout_updates, widget.styles._cache_key)
                for key in widget._box_model_cache.keys():
                    counts["current" if key[-2:] == current else "obsolete"] += 1
            census.update(tabs=len(app.open_tabs), widgets=len(widgets), measurements=counts)

    with patch.object(workload.ReturnApp, "run_test", observed):
        await workload.main(peers=40, channels=12, cycles=1, display_only=True, output=output)
    print(json.dumps({"measurement_census_after_workload": census}))
    result = json.loads(output.read_text())
    result["measurement_census_after_workload"] = census
    output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args().output))
