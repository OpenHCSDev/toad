"""Only a moving effect needs the target's live visibility."""

import pytest
from textual.app import App, ComposeResult
from textual.widget import Widget
from ui_theme.effects import NEW_TEXT, Mix

from toad.frame_presentation import ARRIVAL, AnimationEffects, EffectRunning
from toad.textual_colours import ThemedApp


class VisibilityProbe(AnimationEffects[Mix], Widget):
    visibility_reads = 0

    @property
    def animation_visible(self) -> bool:
        self.visibility_reads += 1
        return super().animation_visible


class EffectApp(ThemedApp, App):
    CSS = "VisibilityProbe { height: 1; }"

    def compose(self) -> ComposeResult:
        yield VisibilityProbe()


def test_unstarted_frame_does_not_read_visibility() -> None:
    owner = VisibilityProbe()
    assert owner.effect_frame(NEW_TEXT) == NEW_TEXT.final
    assert owner.visibility_reads == 0


@pytest.mark.parametrize("position", (0.0, 0.5, 1.0))
async def test_running_and_covered_frames_keep_clock_position(position: float) -> None:
    app = EffectApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        owner = app.query_one(VisibilityProbe)
        owner.run_effect(ARRIVAL)
        phase = owner.effect_phase(ARRIVAL)
        assert isinstance(phase, EffectRunning)
        clock = app.colours.clock
        clock.now = lambda: phase.animation.started + 0.2
        clock.tick()
        before = owner.visibility_reads
        assert owner.effect_frame(ARRIVAL, position) == phase.animation.at(position)
        assert owner.visibility_reads == before + 1

        app.app_focus = False
        before = owner.visibility_reads
        assert owner.effect_frame(ARRIVAL, position) == ARRIVAL.final
        assert owner.visibility_reads == before + 1


async def test_finished_running_frame_does_not_read_visibility() -> None:
    app = EffectApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        owner = app.query_one(VisibilityProbe)
        owner.run_effect(NEW_TEXT)
        phase = owner.effect_phase(NEW_TEXT)
        assert isinstance(phase, EffectRunning)
        remaining = NEW_TEXT.remaining(0)
        assert remaining is not None
        clock = app.colours.clock
        clock.now = lambda: phase.animation.started + remaining + 1
        clock.tick()
        assert not owner.effect_phase(NEW_TEXT).in_motion
        before = owner.visibility_reads
        assert owner.effect_frame(NEW_TEXT) == NEW_TEXT.final
        assert owner.visibility_reads == before
