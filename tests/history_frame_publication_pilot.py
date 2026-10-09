"""Observe actual saved-page composition at native screen publication.

Provider-free source reproducer, not physical saved-live acceptance. The app,
native journal reader, page/body widgets, workers and key dispatch are real.
"""
import asyncio
from contextlib import nullcontext, asynccontextmanager
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import sys
from functools import partial
from tempfile import TemporaryDirectory
from time import monotonic
from unittest.mock import patch
import psutil

if os.environ.get("PUBLICATION_PHYSICAL") == "1":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_comms.comms import Comms
from agent_comms.threads import Thread
from toad.app import ToadApp
from toad.widgets.transcript_history import TranscriptHistory, TranscriptFragmentView
from textual.widget import Widget
from textual._compositor import ChopsUpdate, LayoutUpdate
from textual.geometry import Region


class PublicationApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")

    def __init__(self, **kwargs):
        self.observe = False
        self.frames = []
        self.held_window = None
        super().__init__(**kwargs)

    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        if not self.observe or renderable is None:
            return
        window = self.selected_session.conversation.window
        visible = screen._compositor.visible_widgets
        incomplete = [type(node).__name__ for node in visible
                      if isinstance(node, TranscriptFragmentView) and not node.is_mounted]
        region = window.scrollable_content_region
        # Observe the cells actually supplied to App._display. Re-rendering the
        # current DOM includes removed held subtrees which were NOT published.
        body_strips = []
        published_regions = []
        if isinstance(renderable, ChopsUpdate):
            for y, x1, x2 in renderable.spans:
                published_regions.append(Region(x1, y, x2 - x1, 1))
                if region.y <= y < region.bottom:
                    left, right = max(x1, region.x), min(x2, region.right)
                    if left < right:
                        body_strips.extend(strip for _, strip in
                                           renderable._get_line_chops(y, left, right))
        elif isinstance(renderable, LayoutUpdate):
            published_regions.append(renderable.region)
            for y, line in enumerate(renderable.strips, renderable.region.y):
                if region.y <= y < region.bottom:
                    x = renderable.region.x
                    for strip in line:
                        left, right = max(x, region.x), min(x + strip.cell_length, region.right)
                        if left < right:
                            body_strips.append(strip.crop(left - x, right - x))
                        x += strip.cell_length
        else:
            raise AssertionError(f"Unobserved native publication: {type(renderable).__name__}")
        text = "\n".join(strip.text for strip in body_strips)
        held_regions = (screen._compositor.deferred_regions((self.held_window,))
                        if self.held_window is not None else ())
        held_damage = [tuple(damage.intersection(held))
                       for damage in published_regions for held in held_regions
                       if damage.overlaps(held)]
        self.frames.append(dict(clock=monotonic(), incomplete=incomplete,
                                body_published=bool(body_strips),
                                held_damage=held_damage,
                                admissions=[dict(admitted=page.stop - page.start,
                                                 mounted=len(page.fragment_views),
                                                 native_children=len(page.children))
                                            for history in window.histories for page in history.pages
                                            if page.stop - page.start != len(page.fragment_views)],
                                composing=[type(node).__name__ for node in visible
                                           if isinstance(node, Widget) and not node.is_mounted
                                           and window in node.ancestors],
                                body_nonwhite=len("".join(text.split())),
                                anchor=(window.history_restoration is not None
                                        and window.history_restoration.position is not None),
                                layout_wait=window.history_restoration is not None,
                                y=window.scroll_y, maximum=window.max_scroll_y))


async def main():
    evidence = Path(os.environ["PUBLICATION_EVIDENCE"])
    evidence.mkdir(parents=True, exist_ok=True)
    original = Comms(Path(os.environ["READONLY_SOURCE_ROOT"])) if os.environ.get("READONLY_SOURCE_ROOT") else None
    before = None
    if original is not None:
        thread = original.registry.require("nra-architecture")
        owner = psutil.Process(thread.pid)
        assert owner.is_running()
        journal_stat = Path(thread.session_file).stat()
        before = dict(pid=owner.pid, created=owner.create_time(),
                      journal=[journal_stat.st_ino, journal_stat.st_size, journal_stat.st_mtime_ns])
    physical = os.environ.get("PUBLICATION_PHYSICAL") == "1"
    directory_owner = (nullcontext(os.environ["PUBLICATION_ROOT"]) if physical
                       else TemporaryDirectory(dir=evidence, prefix="saved-pages-"))
    with directory_owner as folder:
        root = Path(folder)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = Comms(root / "wire")
        if physical:
            from agent_comms.active_route import resolve_comms_route
            assert resolve_comms_route().observe_root() == comms.root
            journal = Path(os.environ["PUBLICATION_JOURNAL"]).resolve(strict=True)
            assert journal.is_relative_to(Path.home() / "wt")
            source_before = dict(path=str(journal), bytes=journal.stat().st_size,
                                 sha256=hashlib.sha256(journal.read_bytes()).hexdigest())
        else:
            comms.messaging.initialize_private_initial_protocol()
            journal = root / "saved-native.jsonl"
            journal.write_text("".join(json.dumps({"type": "message", "message": {
                "role": "assistant", "content": [{"type": "text", "text": f"## Saved record {number}\n\n"
                + "Actual prepared document paragraph, with native **body**.\n\n" * 8
                + "```python\n" + "value = 'saved native source'\n" * 8 + "```\n"}]
            }}) + "\n" for number in range(65)))
        comms.registry.declare(Thread("saved-pages", frozenset(), str(root), session_file=str(journal)))

        source_reads = []
        scroll_observations = []

        async def read(window, *, name="saved-pages", **kwargs):
            source, name = (original, "nra-architecture") if original is not None else (comms, name)
            if physical:
                lookahead = window.document_viewport.lookahead
                record = dict(clock=monotonic(), demand=type(lookahead.demand).__name__,
                              travel_rows=lookahead.travel_rows,
                              before=kwargs["before"].offset if kwargs.get("before") is not None else None,
                              after=kwargs["after"].offset if kwargs.get("after") is not None else None)
                source_reads.append(record)
            try:
                page = await asyncio.to_thread(source.transcripts.thread_transcript_page, name, **kwargs)
            except BaseException as error:
                if physical:
                    record.update(finished=monotonic(), failure=type(error).__name__)
                raise
            if physical:
                record.update(finished=monotonic(), returned_before=page.before.offset,
                              returned_after=page.after.offset, events=len(page.events))
            return page

        app = PublicationApp(project_dir=str(root))
        try:
            async with app.run_test(size=(120, 35), headless=not physical) as pilot:
                await app.selected_session.wait_content_ready()
                view = app.selected_session.conversation
                loader = partial(read, view.window)
                history = await view.post(TranscriptHistory(await loader(), loader))
                await pilot.pause(.3)
                if physical:
                    first = app.selected_session
                    if os.environ.get("PUBLICATION_WARM") == "1":
                        from toad.screens.main import MainScreen

                        peer_project = root / 'saved-peer'
                        peer_project.mkdir()
                        comms.registry.declare(Thread('saved-peer', frozenset(), str(peer_project),
                                                      session_file=str(journal)))
                        await app.session_navigation.new(
                            lambda: MainScreen(peer_project, app.agent_data), title='Saved peer')
                        await app.selected_session.wait_content_ready()
                        peer_view = app.selected_session.conversation
                        peer_loader = partial(read, peer_view.window, name='saved-peer')
                        await peer_view.post(TranscriptHistory(await peer_loader(), peer_loader))
                        await pilot.pause(.3)
                        await app.select_session(first.id)
                        await pilot.pause(.3)
                    window = view.window

                    def observe_scroll(y):
                        lookahead = window.document_viewport.lookahead
                        scroll_observations.append(dict(
                            clock=monotonic(), position=y, demand=type(lookahead.demand).__name__,
                            travel_rows=lookahead.travel_rows,
                        ))

                    window.watch(window, "scroll_y", observe_scroll, init=False)
                    async with asyncio.timeout(20):
                        while not view.window.document_viewport.visible_bodies_ready:
                            await pilot.pause(.02)
                    (evidence / "physical-ready.json").write_text(json.dumps(dict(
                        source=source_before, driver=type(app._driver).__name__,
                        history_source=str(history.through.session_file),
                        configured_buffer_viewports=app.settings.ui.history_buffer_viewports,
                        provider_inputs=0, native_owner_starts=0,
                        boundary="Source Toad and original native journal reader; not installed ACP acceptance",
                    ), indent=2) + "\n")
                    while app.is_running:
                        await asyncio.sleep(.05)
                    return
                app.observe = True
                view.window.focus(scroll_visible=False)
                for key, count in (("pageup", 12), ("pagedown", 18), ("pageup", 6)):
                    await pilot.press(*([key] * count))
                await pilot.pause(.3)
                # Native removal changes the scene synchronously; AwaitRemove
                # owns retirement completion. Hold the ORIGINAL history lock,
                # rather than mistaking that later cleanup for paint custody.
                window = history.window
                preserve_history = window.preserve_history
                entered, release = asyncio.Event(), asyncio.Event()

                @asynccontextmanager
                async def held_history(widget, *, root=None):
                    async with preserve_history(widget, root=root):
                        yield
                        app.held_window = window
                        try:
                            entered.set()
                            await release.wait()
                        finally:
                            app.held_window = None

                with patch.object(window, "preserve_history", held_history):
                    try:
                        # This source preview may retain the tail after reverse.
                        # Admit the pager's destination operation explicitly;
                        # the real End binding is covered by physical capture.
                        history.request_latest()
                        await asyncio.wait_for(entered.wait(), 5)
                        assert window.history_mutating()
                        held_frames = len(app.frames)
                        await pilot.pause(.25)
                        assert not any(frame["held_damage"] for frame in app.frames[held_frames:]), "End published held history cells"
                    finally:
                        release.set()
                await pilot.pause(.5)
                await pilot.press("end")
                assert app._exception is None
                print(json.dumps(dict(frames=len(app.frames),
                                      incomplete=sum(bool(frame["incomplete"]) for frame in app.frames),
                                      partial_admissions=sum(bool(frame["admissions"]) for frame in app.frames),
                                      blank_body_updates=sum(frame["body_published"] and not frame["body_nonwhite"]
                                                             for frame in app.frames),
                                      histories=len(history.pages))), flush=True)
                assert app.frames
                body_frames = [frame for frame in app.frames if frame["body_published"]]
                assert body_frames, "No native history paint observed"
                assert not any(frame["admissions"] for frame in body_frames), "Published a partial native page admission"
                assert not any(frame["incomplete"] for frame in body_frames), "Published an unmounted native page body"
                assert all(frame["body_nonwhite"] for frame in body_frames), "Published blank body"
        finally:
            (evidence / "frames.json").write_text(json.dumps(app.frames, indent=2))
            if physical:
                (evidence / "source-reads.json").write_text(json.dumps(source_reads, indent=2) + "\n")
                (evidence / "scroll-demand.json").write_text(json.dumps(scroll_observations, indent=2) + "\n")
                source_after = dict(path=str(journal), bytes=journal.stat().st_size,
                                    sha256=hashlib.sha256(journal.read_bytes()).hexdigest())
                (evidence / "retained-source.json").write_text(json.dumps(dict(
                    before=source_before, after=source_after,
                    unchanged=source_before == source_after,
                ), indent=2) + "\n")
                assert source_before == source_after, "Protected retained journal changed"
            if original is not None:
                assert owner.is_running()
                journal_stat = Path(thread.session_file).stat()
                after = dict(pid=owner.pid, created=owner.create_time(),
                             journal=[journal_stat.st_ino, journal_stat.st_size, journal_stat.st_mtime_ns])
                (evidence / "original-owner.json").write_text(json.dumps(dict(before=before, after=after), indent=2))
                assert before == after, "Original native owner/journal changed"


if __name__ == "__main__":
    asyncio.run(main())
