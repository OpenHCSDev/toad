"""Cold document bodies release native trees and restore source/selection safely."""

import asyncio
from importlib.resources import files
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_comms.comms import Comms

from textual.selection import SELECT_ALL
from textual.widgets._markdown import MarkdownParagraph

from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse


async def settled(view, pilot):
    manager = view.window.document_viewport
    try:
        async with asyncio.timeout(12):
            while True:
                await pilot.pause(.02)
                # Visible readiness alone is not completion of the admitted
                # offscreen retirement cohort; its extent callbacks may still run.
                if (manager._worker is None and manager.visible_bodies_ready
                        and all(owner.body_dormant or manager.requires_body(owner)
                                for owner in manager.body_roots())):
                    return
    except TimeoutError:
        output = os.environ.get("VIEWPORT_EVIDENCE")
        if output:
            roots = []
            for owner in manager.body_roots():
                sources = owner.prepared_paint_sources()
                roots.append(dict(
                    measurement=type(owner._body_measurement).__name__,
                    ready=owner.body_ready, required=manager.requires_body(owner),
                    admitted=owner in manager.admitted_bodies,
                    locked=owner.lock.is_locked,
                    missing=[dict(type=type(child).__name__, size=str(child.size),
                                  ready=child.prepared_content is not None,
                                  ready_signal=getattr(child, "_ready", None).is_set()
                                  if hasattr(child, "_ready") else None)
                             for child, resource in sources if resource is None]))
            (Path(output) / "settlement-timeout.json").write_text(json.dumps(dict(
                pending=manager._pending, accepts_frame=manager.accepts_frame(),
                awaiting_frame=view.window.screen.frame_presentation.awaits_publication(
                    view.window, manager.request), roots=roots), indent=2))
        raise


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
            session = app.selected_session
            await session.wait_content_ready()
            assert await session.wait_presented()
            view = session.conversation
            assert view.agent is None
            window = view.window
            manager = window.document_viewport
            source, membership = app.workspace_sessions.source, manager.membership
            assert window.is_attached and session.is_current
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


async def retirement_visibility(output: Path):
    """A captured offscreen body keeps its native tree after real exposure."""
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="retirement-visible-", dir=output) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            window, manager = view.window, view.window.document_viewport
            first = AgentResponse("Original body\n\nActual retained paragraph.")
            await view.contents.mount(first)
            async with asyncio.timeout(15):
                while not first.body_ready or not first.prepared_paint_is_current(first.prepared_paint_sources()):
                    await pilot.pause(.02)
            # Suspend original housekeeping so this check owns one retirement.
            await manager.suspend_source()
            second = AgentResponse("\n\n".join("Later original paragraph " * 8 for _ in range(30)))
            await view.contents.mount(second)
            window.scroll_end(animate=False, immediate=True)
            await pilot.pause()
            assert not manager.requires_body(first)
            children = first.reconstructible_children()
            assert children and first.prepared_paint_is_current(first.prepared_paint_sources())
            operation = first.retire_body()
            # Actual scrolling exposes the body after synchronous acquisition,
            # before the returned operation measures/commits its captured rows.
            window.release_anchor()
            window.scroll_to_widget(first, animate=False, immediate=True, top=True)
            await pilot.pause()
            assert manager.requires_body(first)
            assert await operation is False
            assert first.reconstructible_children() == children and not first.body_dormant
            assert all(child.is_attached for child in children)
            assert first.body_ready
            assert await first.retire_body() is False
            window.scroll_end(animate=False, immediate=True)
            await pilot.pause()
            assert not manager.requires_body(first)
            assert await first.retire_body() is True
            assert first.body_dormant and not any(child.is_attached for child in children)
            manager.resume_source()
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("PASS: real exposure revokes captured retirement; native body retained; offscreen retirement still completes")


async def main():
    with TemporaryDirectory(prefix="toad-viewport-body-", dir=os.environ.get("VIEWPORT_EVIDENCE")) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        Comms(root / "wire").messaging.initialize_private_initial_protocol()
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await app.selected_session.wait_content_ready()
            assert await app.selected_session.wait_presented()
            view = app.selected_session.conversation
            source = lambda i: f"## Document {i}\n\n" + "\n\n".join(
                f"Paragraph {j}. " + "A measured paragraph with selectable source. " * 12
                for j in range(9))
            docs = [AgentResponse(source(i)) for i in range(32)]
            await view.contents.mount(*docs)
            view.window.anchor()
            await settled(view, pilot)
            if sum(doc.body_dormant for doc in docs) < 20:
                receipt = dict(accepts_frame=view.window.document_viewport.accepts_frame(),
                               owners=len(view.window.document_viewport.owners),
                               admitted=len(view.window.document_viewport.admitted_bodies),
                               roots=[dict(measurement=type(doc._body_measurement).__name__,
                                           ready=doc.body_ready, registered=doc._body_viewport is not None,
                                           visible=doc in app.screen._compositor.visible_widgets)
                                      for doc in docs])
                output = os.environ.get("VIEWPORT_EVIDENCE")
                if output:
                    (Path(output) / "retirement-state.json").write_text(json.dumps(receipt, indent=2))
            assert sum(doc.body_dormant for doc in docs) >= 20
            assert all(doc.source == source(i) for i, doc in enumerate(docs))
            from toad.widgets.viewport_body import MeasuredBody
            # Paint and native controls have separate byte and widget admission.
            # Exercise cold reconstruction using the original paint release;
            # this small source does not establish real byte-pressure eviction.
            dormant = next(doc for doc in docs if doc.body_dormant
                           and not view.window.document_viewport.requires_body(doc))
            dormant.release_paint()
            assert type(dormant._body_measurement) is MeasuredBody
            assert not dormant.query(MarkdownParagraph), "Cold body retained its native message pumps"
            before = len(app._registry)
            view.window.release_anchor()
            output = os.environ.get("VIEWPORT_EVIDENCE")
            if output:
                position = view.window.history_anchor
                (Path(output) / "cold-navigation-acquired.json").write_text(json.dumps(dict(
                    measurement=type(dormant._body_measurement).__name__,
                    rows=dormant.measured_rows, source_bytes=len(dormant.source.encode()),
                    scroll=view.window.scroll_y, target=view.window.scroll_target_y,
                    anchor=repr(position), revision=view.window.scroll_revision,
                    source_geometry=[str(geometry) for owner, geometry in
                                     app.screen._compositor.published_geometry((dormant,))],
                ), indent=2))
            view.window.scroll_to_widget(dormant, animate=False, immediate=True)
            if output:
                (Path(output) / "cold-navigation-selected.json").write_text(json.dumps(dict(
                    scroll=view.window.scroll_y, target=view.window.scroll_target_y,
                    anchor=repr(view.window.history_anchor), revision=view.window.scroll_revision,
                ), indent=2))
            # Native scroll_to_widget supplies one placement, not a source
            # destination through subsequent worker/extent publication. Keep
            # that original target in the window's existing reader lifetime.
            async with view.window.preserve_reader(dormant):
                await settled(view, pilot)
            output = os.environ.get("VIEWPORT_EVIDENCE")
            if output:
                manager = view.window.document_viewport
                compositor = app.screen._compositor
                (Path(output) / "cold-destination.json").write_text(json.dumps(dict(
                    measurement=type(dormant._body_measurement).__name__,
                    ready=dormant.body_ready, paragraphs=len(dormant.query(MarkdownParagraph)),
                    visible=dormant in compositor.visible_widgets,
                    required=manager.requires_body(dormant),
                    pending=manager._pending, worker=manager._worker is not None,
                    scroll=view.window.scroll_y, target=view.window.scroll_target_y,
                    follows=view.window.follows_tail,
                    region=str(dormant.region), virtual_region=str(dormant.virtual_region),
                    viewport=str(view.window.content_region),
                    source_geometry=[str(geometry) for owner, geometry in
                                     compositor.published_geometry((dormant,))],
                    frame_wait=app.screen.frame_presentation.awaits_publication(
                        view.window, manager.request)), indent=2))
            assert dormant.body_ready and dormant.query(MarkdownParagraph)
            # Selection protects the actual rendered endpoint, not the first
            # hidden paragraph whose preparation is deliberately lazy.
            text = next(view.window.visible_history_items(dormant.query(MarkdownParagraph)))
            selected = text.get_selection(SELECT_ALL)
            assert selected is not None
            expected = selected[0]
            assert "A measured paragraph with selectable source." in expected
            app.screen.selections = {text: SELECT_ALL}
            view.window.scroll_end(animate=False, immediate=True)
            await settled(view, pilot)
            assert text.is_attached and expected in app.screen.get_selected_text()
            assert sum(doc.body_dormant for doc in docs) >= 18
            app.screen.clear_selection()
            for index in (0, 31, 4, 29, 0, 31):
                view.window.release_anchor()
                view.window.scroll_to_widget(docs[index], animate=False, immediate=True)
                async with view.window.preserve_reader(docs[index]):
                    await settled(view, pilot)
                returned = docs[index]
                if output and returned not in app.screen._compositor.visible_widgets:
                    (Path(output) / "cold-return-unexposed.json").write_text(json.dumps(dict(
                        index=index, measurement=type(returned._body_measurement).__name__,
                        rows=returned.measured_rows, scroll=view.window.scroll_y,
                        target=view.window.scroll_target_y, revision=view.window.scroll_revision,
                        source_geometry=[str(geometry) for owner, geometry in
                                         app.screen._compositor.published_geometry((returned,))],
                    ), indent=2))
                assert returned in app.screen._compositor.visible_widgets
                assert returned.body_ready, "Visible source was not restored"
                if returned.body_retained_paint_ready:
                    selected = returned.get_selection(SELECT_ALL)
                    assert selected is not None
                    assert "A measured paragraph with selectable source." in selected[0]
                else:
                    paragraphs = returned.query(MarkdownParagraph)
                    assert paragraphs, "Cold source was not reconstructed"
                    assert any("A measured paragraph with selectable source." in child.source
                               for child in paragraphs)
            assert len(app._registry) <= before + 40, "Repeated visibility accumulated presentation trees"
            await pilot.resize_terminal(90, 40)
            await settled(view, pilot)
            view.window.scroll_to_widget(docs[0], animate=False, immediate=True)
            async with view.window.preserve_reader(docs[0]):
                await settled(view, pilot)
            assert docs[0].body_ready and docs[0].source == source(0)
            cold = next(doc for doc in docs if doc.body_dormant)
            await cold.append("\n\nA later live update.")
            view.window.scroll_to_widget(cold, animate=False, immediate=True)
            async with view.window.preserve_reader(cold):
                await settled(view, pilot)
            assert cold.source.endswith("A later live update.")
            assert any("A later live update." in child.source for child in cold.query(MarkdownParagraph))
            anchor = AgentResponse("A transient anchor")
            await view.contents.mount(anchor)
            await settled(view, pilot)

            async def transaction():
                async with view.window.history_lock:
                    async with view.window.preserve_history(anchor):
                        # Unchanged transactions correctly skip reflow. This
                        # retirement check needs an actual native extent edit.
                        anchor.styles.margin = (1, 0)

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
            await app.select_session(owner_mode)
            await settled(view, pilot)

            async def switch_during_transaction():
                async with view.window.history_lock:
                    async with view.window.preserve_history(docs[0]):
                        await app.select_session(other.mode_name)

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
    elif len(sys.argv) == 3 and sys.argv[1] == "--retirement-visibility-only":
        asyncio.run(retirement_visibility(Path(sys.argv[2]).resolve()))
    elif len(sys.argv) == 1:
        asyncio.run(main())
    else:
        raise SystemExit("usage: viewport_body_lifetime_pilot.py [--worker-custody-only OUTPUT]")
