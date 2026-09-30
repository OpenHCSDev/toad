"""Installed real saved-backend tabs and lazy PageDown; never submit or stop owners."""

import asyncio
from hashlib import sha256
from importlib.resources import files
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

import psutil
from agent_comms.comms import wire
from toad.app import ToadApp
from toad.agent_schema import AgentDefinition
from toad.widgets.transcript_history import TranscriptHistory
from toad.widgets.session_tabs import SessionLabel
from saved_state_user_journey_pilot import click_thread


class SavedReaderApp(ToadApp):
    CSS_PATH = [files("toad").joinpath("toad.tcss"), files("toad").joinpath("screens/comms.tcss")]
    phase = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.frames = []

    def checkpoint(self, label):
        evidence = Path(os.environ["READONLY_READER_EVIDENCE"])
        (evidence / "frames.json").write_text(json.dumps(self.frames, indent=2))
        print(label, len(self.frames), flush=True)

    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        if self.phase is None or renderable is None or self._batch_count:
            return
        view = self.selected_session.conversation
        window = view.window
        region = window.scrollable_content_region
        strips = screen._compositor.render_strips()
        body = "\n".join(strip.crop(region.x, region.right).text
                         for strip in strips[region.y:region.bottom])
        histories = tuple(window.histories)
        self.frames.append(dict(clock=monotonic(), phase=self.phase,
                                source=view.agent.session_id if view.agent else None,
                                y=window.scroll_y, maximum=window.max_scroll_y,
                                follows_tail=window.follows_tail,
                                body_hash=sha256(body.encode()).hexdigest(),
                                body_nonwhite=len("".join(body.split())),
                                has_newer=any(history.has_newer for history in histories),
                                loading=any(history._loading for history in histories)))


async def until(pilot, app, condition):
    async with asyncio.timeout(20):
        while not condition():
            if app._exception is not None:
                raise app._exception
            await pilot.pause(.03)


async def ready(pilot, app, source):
    await until(pilot, app, lambda: source.conversation.agent_ready
                and source.conversation.contents.query(TranscriptHistory))
    await pilot.pause()
    return source.conversation


async def select(app, pilot, source):
    label = app.screen.query_one(f"SessionLabel#{source.id}", SessionLabel)
    label.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(label)
    await until(pilot, app, lambda: app.selected_session is source)
    await ready(pilot, app, source)


async def main():
    evidence = Path(os.environ["READONLY_READER_EVIDENCE"])
    evidence.mkdir(parents=True, exist_ok=True)
    # Resolve the approved default route once. No owner start/stop or fixture
    # teardown: this app must never use runtime_fixture.ToadApp on the live root.
    comms = wire()
    names = ("agent-comms-ux", "nra-architecture")
    owners = {name: psutil.Process(comms.registry.require(name).pid) for name in names}
    identities = {name: (p.pid, p.create_time()) for name, p in owners.items()}
    assert all(p.is_running() for p in owners.values())
    print("READONLY_EXISTING_OWNERS_CONFIRMED", identities, flush=True)
    app = None
    try:
        with TemporaryDirectory(prefix="readonly-reader-", dir=os.environ["TMPDIR"]) as directory:
            root = Path(directory)
            os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                              XDG_STATE_HOME=str(root / "state"),
                              XDG_DATA_HOME=str(root / "data"))
            definition = AgentDefinition.decode(dict(
                name="Agent Comms", identity="saved-reader-check", short_name="agent",
                protocol="acp", run_command={"*": "/home/ts/.local/bin/agent-comms-acp"}))
            app = SavedReaderApp(agent_data=definition,
                                project_dir=comms.registry.require(names[0]).worktree,
                                agent_session_id=names[0])
            async with app.run_test(size=(140, 36)) as pilot:
                first = app.selected_session
                await ready(pilot, app, first)
                app.checkpoint("FIRST_ACTUAL_SAVED_READY")
                second = await click_thread(app, pilot, names[1], "#nra")
                view = await ready(pilot, app, second)
                app.checkpoint("SECOND_ACTUAL_SAVED_READY")
                window = view.window
                app.phase = "reader-input"
                window.focus(scroll_visible=False)
                await pilot.press("up", "up", "up", "up", "up")
                await pilot.wait_for_scheduled_animations()
                await pilot.pause()
                position = window.scroll_y
                assert not window.follows_tail
                reader_paint = app.frames[-1]["body_hash"]
                app.checkpoint("READER_OFFSET_ESTABLISHED")
                history = next(iter(window.histories))
                app.phase = "physical-A"
                await select(app, pilot, first)
                app.phase = "physical-B-return"
                await select(app, pilot, second)
                assert view is second.conversation and history in window.histories
                assert window.scroll_y == position and not window.follows_tail
                returned = [frame for frame in app.frames
                            if frame["phase"] == "physical-B-return"
                            and frame["source"] == names[1]]
                assert returned and all(frame["body_hash"] == reader_paint
                                        for frame in returned), "Warm return changed reader paint"
                app.checkpoint("PHYSICAL_ABA_RETAINED_READER")

                # Primary case: ordinary PageDown at lazy/not fully prepared
                # bottom. End is deliberately absent until after reverse/idle.
                app.phase = "repeated-pagedown-lazy-bottom"
                window.focus(scroll_visible=False)
                await pilot.press(*(["pageup"] * 5))
                for _ in range(30):
                    await pilot.press("pagedown")
                app.checkpoint("REPEATED_PAGEDOWN_LAZY_BOTTOM_SENT")
                await pilot.wait_for_scheduled_animations()
                app.phase = "reverse"
                await pilot.press(*(["pageup"] * 8))
                await pilot.wait_for_scheduled_animations()
                app.phase = "idle"
                await pilot.pause(.4)
                app.checkpoint("REVERSE_IDLE_COMPLETE")
                app.phase = "separate-End"
                await pilot.press("end")
                await pilot.pause(.3)
                assert window.follows_tail
                assert app._exception is None
                observed = app.frames
                app.checkpoint("SEPARATE_END_COMPLETE")
                assert observed and all(frame["body_nonwhite"] for frame in observed), "Blank destination frame"
                assert all(0 <= frame["y"] <= frame["maximum"] for frame in observed), "Scroll beyond canonical extent"
                assert any(frame["phase"] == "repeated-pagedown-lazy-bottom"
                           and (frame["loading"] or frame["has_newer"])
                           for frame in observed), "Lazy bottom was not exercised"
            await asyncio.get_running_loop().shutdown_default_executor()
    finally:
        if app is not None:
            (evidence / "frames.json").write_text(json.dumps(app.frames, indent=2))
        final = {name: (p.pid, p.create_time()) for name, p in owners.items() if p.is_running()}
        (evidence / "owners.json").write_text(json.dumps(dict(before=identities, after=final), indent=2))
        assert identities == final, "Live owner identity changed during read-only UI journey"
    print("INSTALLED_READONLY_SAVED_ABA_PAGEDOWN_REVERSE_IDLE_END_PASS")


if __name__ == "__main__":
    asyncio.run(main())
