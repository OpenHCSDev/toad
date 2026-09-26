"""Filter changes during either mount await must retire the old publication."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_comms import Message, MessageType, TranscriptCursor, TranscriptEvent, TranscriptPage, TurnRouting
from runtime_fixture import ToadApp
from textual.await_complete import AwaitComplete
from textual.containers import VerticalGroup

from toad.widgets.message_filter import ALL_CATEGORIES, MessageCategory
from toad.widgets.transcript_history import TranscriptHistory


async def exercise(app, pilot, stage):
    view = app.screen.conversation
    view.visible_categories = ALL_CATEGORIES
    message = Message("peer", "owner", "OLD_INBOUND", MessageType.INFO, timestamp=0)
    incoming = TranscriptEvent("user", message.body, routing=TurnRouting((message,), None))
    thinking = TranscriptEvent("thinking", "NEW_THINKING")
    events = (incoming, thinking) * 4 + tuple(TranscriptEvent("assistant", f"tail {i}") for i in range(4))
    cursor = TranscriptCursor("mount-fixture", 0)
    pager = TranscriptHistory(TranscriptPage(events, cursor, TranscriptCursor("mount-fixture", 12), False, False))
    entered, release = asyncio.Event(), asyncio.Event()
    original_mount = VerticalGroup.mount
    held = False

    def mounted(parent, *widgets, **kwargs):
        nonlocal held
        result = original_mount(parent, *widgets, **kwargs)
        target = parent is pager if stage == "container" else parent.has_class("filtered-history-results")
        if target and not held:
            held = True

            async def wait():
                await result
                entered.set()
                await release.wait()

            return AwaitComplete(wait())
        return result

    with patch.object(pager, "_scroll_changed"), patch.object(pager, "_check_edges"):
        await view.contents.mount(pager)
        await pilot.pause()
        view.visible_categories = frozenset((MessageCategory.INBOUND,))
        scan = None
        try:
            with patch.object(VerticalGroup, "mount", mounted):
                pager._filter_scanning = True
                scan = asyncio.create_task(pager._scan_filtered_older())
                await asyncio.wait_for(entered.wait(), 5)
                view.visible_categories = frozenset((MessageCategory.THINKING,))
                view.prompt.focus()
                await pilot.press("x")
                assert view.prompt.text.endswith("x"), "Typing blocked behind filter mount"
                owner_mode = app.current_mode
                other = await app.new_session_screen(app.get_main_screen)
                await pilot.pause()
                other_view = app.screen.conversation
                assert other_view.visible_categories == ALL_CATEGORIES
                other_view.prompt.focus()
                await pilot.press("y")
                assert other_view.prompt.text == "y", "Another thread froze behind the old filter"
                await app.switch_mode(owner_mode)
                await pilot.pause()
                assert view.visible_categories == frozenset((MessageCategory.THINKING,))
                release.set()
                await asyncio.wait_for(scan, 5)
                assert pager._filter_before is None, "Stale filter advanced the new filter cursor"
            await pilot.pause()
            pager._filter_scanning = True
            await pager._scan_filtered_older()
            await pilot.pause()
            assert pager._filter_overlay is not None
            assert all(child.fragment.events[0].kind == "thinking" for child in pager._filter_overlay.children)
            await app.close_session_mode(other.mode_name)
            assert app._exception is None
        finally:
            release.set()
            if scan is not None:
                await asyncio.gather(scan, return_exceptions=True)
            await pager.remove()


async def main():
    with TemporaryDirectory(prefix="toad-filter-mount-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            for stage in ("container", "children"):
                await exercise(app, pilot, stage)
            view = app.screen.conversation
            view.visible_categories = frozenset()
            cursor = TranscriptCursor("empty-filter", 10)
            calls = []
            message = Message("peer", "owner", "SELECTED_INBOUND", MessageType.INFO, timestamp=0)
            incoming = TranscriptEvent("user", message.body, routing=TurnRouting((message,), None))

            async def earlier(**kwargs):
                calls.append(kwargs)
                return TranscriptPage((incoming,), TranscriptCursor("empty-filter", 0), cursor, False, True)

            pager = TranscriptHistory(TranscriptPage((TranscriptEvent("thinking", "TAIL"),),
                cursor, TranscriptCursor("empty-filter", 20), True, False), loader=earlier)
            await view.contents.mount(pager)
            await pilot.pause()
            assert not calls, "Empty filter speculatively read history that cannot match"
            assert not pager.older.display and not pager.newer.display
            view.visible_categories = frozenset((MessageCategory.INBOUND,))
            async with asyncio.timeout(5):
                while pager._filter_overlay is None or pager._filter_scanning:
                    await pilot.pause(.01)
            assert calls and any(child.fragment.events[0].text == "SELECTED_INBOUND"
                                 for child in pager._filter_overlay.children)
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("filter mount supersession: typing and thread switches remain live; stale container/child mounts cannot publish or advance cursors")


if __name__ == "__main__":
    asyncio.run(main())
