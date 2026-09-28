"""Cold document bodies release native trees and restore source/selection safely."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from textual.selection import SELECT_ALL
from textual.widgets._markdown import MarkdownParagraph

from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse


async def settled(view, pilot):
    async with asyncio.timeout(12):
        while True:
            await pilot.pause(.02)
            manager = view.window.document_viewport
            if not manager._running and manager.visible_bodies_ready:
                return


def assert_bounded_bodies(view, docs):
    window = view.window
    visible = view.screen._compositor.visible_widgets
    live = sum(not doc.body_dormant for doc in docs)
    bound = (window.document_viewport.max_warm_bodies
             + sum(doc in visible for doc in docs) + len(view.screen.selections))
    assert live <= bound, (live, bound)


async def main():
    with TemporaryDirectory(prefix="toad-viewport-body-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            source = lambda i: f"## Document {i}\n\n" + "A measured paragraph with selectable source. " * 12 + "\n\nAnother paragraph."
            docs = [AgentResponse(source(i)) for i in range(32)]
            await view.contents.mount(*docs)
            view.window.anchor()
            await settled(view, pilot)
            assert_bounded_bodies(view, docs)
            assert all(doc.source == source(i) for i, doc in enumerate(docs))
            dormant = next(doc for doc in docs if doc.body_dormant)
            assert not dormant.query(MarkdownParagraph), "Cold body retained its native message pumps"
            before = len(app._registry)
            view.window.release_anchor()
            view.window.scroll_to_widget(dormant, animate=False, immediate=True)
            await settled(view, pilot)
            assert dormant.body_ready and dormant.query(MarkdownParagraph)
            text = dormant.query_one(MarkdownParagraph)
            expected = text.render().plain
            app.screen.selections = {text: SELECT_ALL}
            view.window.scroll_end(animate=False, immediate=True)
            await settled(view, pilot)
            assert text.is_attached and expected in app.screen.get_selected_text()
            assert_bounded_bodies(view, docs)
            app.screen.clear_selection()
            for index in (0, 31, 4, 29, 0, 31):
                view.window.release_anchor()
                view.window.scroll_to_widget(docs[index], animate=False, immediate=True)
                await settled(view, pilot)
                assert docs[index].query(MarkdownParagraph), "Visible source was not restored"
            assert len(app._registry) <= before + 40, "Repeated visibility accumulated presentation trees"
            await pilot.resize_terminal(90, 40)
            await settled(view, pilot)
            view.window.scroll_to_widget(docs[0], animate=False, immediate=True)
            await settled(view, pilot)
            assert docs[0].body_ready and docs[0].source == source(0)
            cold = next(doc for doc in docs if doc.body_dormant)
            await cold.append("\n\nA later live update.")
            view.window.scroll_to_widget(cold, animate=False, immediate=True)
            await settled(view, pilot)
            assert cold.source.endswith("A later live update.")
            assert any("A later live update." in child.source for child in cold.query(MarkdownParagraph))
            anchor = AgentResponse("A transient anchor")
            await view.contents.mount(anchor)
            await settled(view, pilot)

            async def transaction():
                async with view.window.history_lock:
                    async with view.window.preserve_history(anchor):
                        pass

            # The anchor can retire after a transaction requests its frame.
            # A completed layout must release it even though compensation no
            # longer has a live target; otherwise every future load deadlocks.
            with patch.object(app.screen, "_refresh_layout", lambda *args, **kwargs: None):
                pending = asyncio.create_task(transaction())
                async with asyncio.timeout(2):
                    while view.window.history_layout_ready is None:
                        await asyncio.sleep(.001)
                await anchor.remove()
            app.screen._refresh_layout()
            await asyncio.wait_for(pending, 2)

            owner_mode = app.current_mode
            other = await app.new_session_screen(app.get_main_screen)
            await app.switch_mode(owner_mode)
            await settled(view, pilot)

            async def switch_during_transaction():
                async with view.window.history_lock:
                    async with view.window.preserve_history(docs[0]):
                        await app.switch_mode(other.mode_name)

            # Suspension may occur inside the mutation, before __aexit__ has
            # created any frame waiter for the suspend hook to release.
            await asyncio.wait_for(switch_during_transaction(), 3)
            assert not view.window.history_lock.locked()
            assert view.window.history_layout_ready is None
            await app.close_session_mode(other.mode_name)
            for node in app._registry:
                for watchers in vars(node).get("__watchers", {}).values():
                    assert all(not subscriber._closed for subscriber, _ in watchers)
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("viewport bodies: source and selected text preserved, trees bounded across scroll/resize/live-update churn")


if __name__ == "__main__":
    asyncio.run(main())
