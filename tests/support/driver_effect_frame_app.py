"""Price effect getters on a real row in a normally launched native Toad.

This fixed-work experiment does not measure frame rate or input latency. The
before file is the actual prior source, loaded only in this diagnostic process.
"""

import argparse
import asyncio
from functools import partial
import json
from pathlib import Path
import runpy
from time import perf_counter, thread_time
import traceback

from textual.pilot import Pilot
from toad.application_lifetime import ApplicationLifetime
from toad.cli import main
from toad.constants import WELCOME
from toad.frame_presentation import AnimationEffects, EffectRunning
from toad.screens.welcome import WelcomeEntries
from toad.widgets.comms_sidebar import ThreadStatusRow
from ui_theme.effects import NAME_WAVE


async def exercise(options, lifetime: ApplicationLifetime) -> None:
    app = lifetime.app
    result = {"scope": "fixed-work effect getters; no cProfile; not frame rate or input latency"}
    original_shown = EffectRunning.shown
    code = 1
    try:
        async with asyncio.timeout(120):
            await lifetime.start_worker.wait()
            await app.select_session(WELCOME)
            pilot = Pilot(app)
            entries = app.selected_session.query_one(WelcomeEntries)
            while not entries.model_state.shows_model() or entries.model_state.shown.observation.shows_status():
                await pilot.pause()
            rows = tuple(app.selected_session.query(ThreadStatusRow))
            remaining = max((fade.remaining(0) for row in rows for fade in row.text_fades), default=0)
            assert remaining is not None
            await asyncio.sleep(remaining + 1)
            owner = next(row for row in rows
                         if row.animation_visible and row.busy and row.effect_phase(NAME_WAVE).in_motion
                         and all(not row.effect_phase(fade).in_motion for fade in row.text_fades))
            assert owner.text_fades
            before = runpy.run_path(str(options.before))
            paths = ((before["AnimationEffects"].effect_frame, before["EffectRunning"].shown),
                     (AnimationEffects.effect_frame, original_shown))
            result.update(target=owner.target_name, size=tuple(app.size),
                          endpoint=str(app.coordination_access.connection.endpoint.url), samples=[])
            app.notify("Fixed-work effect comparison starts in five seconds", timeout=5)
            await asyncio.sleep(5)

            def sample(path, effect, count: int):
                getter, shown = path
                assert owner.is_attached
                assert all(not owner.effect_phase(fade).in_motion for fade in owner.text_fades)
                expected = owner.effect_frame(effect)
                phase = owner.effect_phase(effect)
                moving = phase.in_motion
                EffectRunning.shown = shown
                try:
                    wall, cpu = perf_counter(), thread_time()
                    for _ in range(count):
                        frame = getter(owner, effect)
                    cpu, wall = thread_time() - cpu, perf_counter() - wall
                    assert frame == expected
                    return {"source": getter.__code__.co_filename, "calls": count,
                            "effect": type(effect).__qualname__, "phase": type(phase).__qualname__, "moving": moving,
                            "cpu_seconds": cpu, "wall_seconds": wall}
                finally:
                    # No event-loop turn ever paints through the old method signature.
                    EffectRunning.shown = original_shown

            for effect in (*owner.text_fades, NAME_WAVE):
                for path in paths:
                    sample(path, effect, max(1, options.iterations // 10))
                for path in (paths[0], paths[1], paths[1], paths[0]):
                    result["samples"].append(sample(path, effect, options.iterations))
                    await asyncio.sleep(0)
            assert app._exception is None, app._exception
            code = 0
    except BaseException:
        result["failure"] = traceback.format_exc()
    finally:
        EffectRunning.shown = original_shown
        result.update(exit=code, app_exception=repr(app._exception))
        options.output.mkdir(parents=True, exist_ok=True)
        (options.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        app.exit(return_code=code)


def observe(options, lifetime: ApplicationLifetime) -> None:
    lifetime.app.call_later(lambda: lifetime.app.run_worker(
        exercise(options, lifetime), name="Stopped-effect fixed-work comparison"))


def run() -> None:
    parser = argparse.ArgumentParser()
    for name in ("profile", "project", "before", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--iterations", type=int, required=True)
    options = parser.parse_args()
    assert options.iterations > 0
    ApplicationLifetime.observe_next_start(partial(observe, options))
    main(args=["--comms-profile", str(options.profile), str(options.project)])


if __name__ == "__main__":
    run()
