"""Observe actual saved-page composition at native screen publication.

Provider-free source reproducer, not physical saved-live acceptance. The app,
native journal reader, page/body widgets, workers and key dispatch are real.
"""
import asyncio
from importlib.resources import files
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
import psutil

from agent_comms.comms import Comms
from agent_comms.threads import Thread
from toad.app import ToadApp
from toad.widgets.transcript_history import TranscriptHistory, TranscriptFragmentView
from textual.widget import Widget


class PublicationApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")

    def __init__(self, **kwargs):
        self.observe = False
        self.frames = []
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
        strips = screen._compositor.render_strips()
        text = "\n".join(strip.crop(region.x, region.right).text
                         for strip in strips[region.y:region.bottom])
        self.frames.append(dict(clock=monotonic(), incomplete=incomplete,
                                admissions=[dict(admitted=page.stop - page.start,
                                                 mounted=len(page.children))
                                            for history in window.histories for page in history.pages
                                            if page.stop - page.start != len(page.children)],
                                composing=[type(node).__name__ for node in visible
                                           if isinstance(node, Widget) and not node.is_mounted
                                           and window in node.ancestors],
                                body_nonwhite=len("".join(text.split())),
                                anchor=window.history_anchor is not None,
                                layout_wait=window.history_layout_ready is not None,
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
    with TemporaryDirectory(dir=evidence, prefix="saved-pages-") as folder:
        root = Path(folder)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = Comms(root / "wire")
        comms.messaging.initialize_private_initial_protocol()
        journal = root / "saved-native.jsonl"
        journal.write_text("".join(json.dumps({"type": "message", "message": {
            "role": "assistant", "content": f"## Saved record {number}\n\n"
            + "Actual prepared document paragraph, with native **body**.\n\n" * 8
            + "```python\n" + "value = 'saved native source'\n" * 8 + "```\n"
        }}) + "\n" for number in range(65)))
        comms.registry.declare(Thread("saved-pages", frozenset(), str(root), session_file=str(journal)))

        async def read(**kwargs):
            source, name = (original, "nra-architecture") if original is not None else (comms, "saved-pages")
            return await asyncio.to_thread(source.transcripts.thread_transcript_page, name, **kwargs)

        app = PublicationApp(project_dir=str(root))
        try:
            async with app.run_test(size=(120, 35)) as pilot:
                await app.selected_session.wait_content_ready()
                view = app.selected_session.conversation
                history = await view.post(TranscriptHistory(await read(), read))
                await pilot.pause(.3)
                app.observe = True
                view.window.focus(scroll_visible=False)
                for key, count in (("pageup", 12), ("pagedown", 18), ("pageup", 6)):
                    await pilot.press(*([key] * count))
                await pilot.pause(.3)
                await pilot.press("end")
                await pilot.pause(.5)
                assert app._exception is None
                print(json.dumps(dict(frames=len(app.frames),
                                      incomplete=sum(bool(frame["incomplete"]) for frame in app.frames),
                                      partial_admissions=sum(bool(frame["admissions"]) for frame in app.frames),
                                      blanks=sum(not frame["body_nonwhite"] for frame in app.frames),
                                      histories=len(history.pages))), flush=True)
                assert app.frames
                assert not any(frame["admissions"] for frame in app.frames), "Published a partial native page admission"
                assert not any(frame["incomplete"] for frame in app.frames), "Published an unmounted native page body"
                assert all(frame["body_nonwhite"] for frame in app.frames), "Published blank body"
        finally:
            (evidence / "frames.json").write_text(json.dumps(app.frames, indent=2))
            if original is not None:
                assert owner.is_running()
                journal_stat = Path(thread.session_file).stat()
                after = dict(pid=owner.pid, created=owner.create_time(),
                             journal=[journal_stat.st_ino, journal_stat.st_size, journal_stat.st_mtime_ns])
                (evidence / "original-owner.json").write_text(json.dumps(dict(before=before, after=after), indent=2))
                assert before == after, "Original native owner/journal changed"


if __name__ == "__main__":
    asyncio.run(main())
