"""Cold document bodies release native trees and restore source/selection safely."""

import asyncio
from importlib.resources import files
import json
import os
from pathlib import Path
import sys
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
            if manager._worker is None and manager.visible_bodies_ready:
                return


async def worker_custody(output: Path):
    """One mounted original worker journey, without the body churn scenario."""
    from textual.worker import get_current_worker

    class InstalledApp(ToadApp):
        CSS_PATH = files("toad").joinpath("toad.tcss")

    output.mkdir(parents=True, exist_ok=True)
    receipt = {"scope": "Mounted viewport pre-entry cancellation/resume/coalescing/close"}
    with TemporaryDirectory(prefix="viewport-worker-", dir=output) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"))
        app = InstalledApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            assert await app.selected_session.wait_presented()
            view = app.selected_session.conversation
            assert view.agent is None
            window = view.window
            manager = window.document_viewport
            source, membership = app.workspace_sessions.source, manager.membership
            assert window.is_attached and view.is_current
            await manager.suspend_source()

            # Observe entry into the original method, without replacing its
            # worker, scheduling or body work. Native startup can cancel before
            # calling this method; its finally cannot certify that cancellation.
            entered = set()
            code = manager._reconcile.__func__.__code__
            previous_profile = sys.getprofile()

            def observe(frame, event, argument):
                if previous_profile is not None:
                    previous_profile(frame, event, argument)
                if event == "call" and frame.f_code is code and frame.f_locals["self"] is manager:
                    entered.add(get_current_worker())

            sys.setprofile(observe)
            try:
                manager.resume_source()
                manager.request()
                cancelled = manager._worker
                assert cancelled is not None and cancelled not in entered
                await manager.suspend_source()
                assert cancelled.is_cancelled and cancelled.is_finished
                assert cancelled not in entered
                assert manager._worker is None and not manager._pending

                manager.resume_source()
                manager.request()
                resumed = manager._worker
                assert resumed is not None and resumed is not cancelled
                for _ in range(3):
                    manager.request()
                    assert manager._worker is resumed
                await resumed.wait()
                assert resumed in entered and resumed.is_finished
                # A later native frame may already admit another request.
                # This worker's completion must release its own custody,
                # without discarding that independently admitted demand.
                assert manager._worker is not resumed
                assert manager.visible_bodies_ready
                assert app.workspace_sessions.source is source
                assert view.window is window and manager.membership is membership

                manager.request()
                closing = manager._worker
                assert closing is not None and closing is not resumed
                await manager.close()
                assert closing.is_cancelled and closing.is_finished
                assert manager._worker is None and not manager._pending
                assert not manager.accepts_frame()
                assert not manager.owners and not manager._warm and not manager.admitted_bodies
                assert not any(worker.node is window and worker.group == "viewport-bodies"
                               for worker in app.workers)
            finally:
                sys.setprofile(previous_profile)
            assert app._exception is None
            receipt.update(pre_entry_cancelled=cancelled.state.name,
                           resumed=resumed.state.name, coalesced_requests=3,
                           close_cancelled=closing.state.name,
                           same_source_and_window=True, viewport_workers=[])
        await asyncio.get_running_loop().shutdown_default_executor()
        assert app.preparation._closed and not app.preparation._pending
        assert app._exception is None
    receipt["state"] = "PASS"
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)


async def main():
    with TemporaryDirectory(prefix="toad-viewport-body-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            view = app.selected_session.conversation
            source = lambda i: f"## Document {i}\n\n" + "A measured paragraph with selectable source. " * 12 + "\n\nAnother paragraph."
            docs = [AgentResponse(source(i)) for i in range(32)]
            await view.contents.mount(*docs)
            view.window.anchor()
            await settled(view, pilot)
            assert sum(doc.body_dormant for doc in docs) >= 20
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
            assert sum(doc.body_dormant for doc in docs) >= 18
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

            owner_mode = app.selected_mode
            other = await app.session_navigation.new(app.session_navigation.default_source)
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
            await app.session_navigation.close(other.mode_name)
            for node in app._registry:
                for watchers in vars(node).get("__watchers", {}).values():
                    assert all(not subscriber._closed for subscriber, _ in watchers)
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("viewport bodies: source and selected text preserved, trees bounded across scroll/resize/live-update churn")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker-custody-only":
        asyncio.run(worker_custody(Path(sys.argv[2]).resolve()))
    elif len(sys.argv) == 1:
        asyncio.run(main())
    else:
        raise SystemExit("usage: viewport_body_lifetime_pilot.py [--worker-custody-only OUTPUT]")
