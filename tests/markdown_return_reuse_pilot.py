"""Installed painted body remount uses bounded syntax, with fresh file resolution.

The optional page/wheel phase borrows the original async page buffer, mounts
authored typed pages and dispatches native wheel/reversal/End input. No Agent,
Node, model provider or claim about saved native history is involved.
"""
import asyncio
import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from sidebar_retirement_pilot import InstalledApp, until, viewport_text
from toad.render_tasks import MarkdownRenderTask
from toad.work_preparation import RenderPreparation
from toad.widgets.agent_response import AgentResponse
from textual.widgets._markdown import MarkdownParagraph
from textual.style import Style
from textual import events


async def page_wheel(app, pilot, view):
    from agent_comms.transcript_events import AssistantTranscript
    from agent_comms.transcripts import TranscriptCursor, TranscriptPage
    from toad.transcript_preparation import CategoryProjection, PageRequest, TranscriptPageWork
    from toad.widgets.history_anchor import ReaderPosition
    from toad.widgets.message_filter import all_categories
    from toad.widgets.transcript_history import TranscriptHistory

    source = str(app.project_dir / "authored-typed-page-source")
    records = tuple(AssistantTranscript(
        f"MOUNTED_PAGE_{index:02}\n\n"
        + "\n\n".join(f"Original paragraph {line} for record {index}." for line in range(5)),
    ) for index in range(24))
    through = TranscriptCursor(source, len(records))
    reads = []

    def page(start, stop):
        return TranscriptPage(records[start:stop], TranscriptCursor(source, start),
                              TranscriptCursor(source, stop), start > 0, stop < len(records))

    async def loader(*, before=None, after=None, through):
        assert through == TranscriptCursor(source, len(records))
        assert before is None or after is None
        cursor = before or after or through
        assert cursor.session_file == source
        if after is not None:
            start, stop = cursor.offset, min(cursor.offset + 8, len(records))
        else:
            start, stop = max(0, cursor.offset - 8), cursor.offset
        reads.append((start, stop))
        return page(start, stop)

    # The real pager creates and retires its own buffer/scope. No test installs
    # a page buffer, body or preparation result into its private storage.
    history = TranscriptHistory(page(16, 24), loader=loader)
    await view.transcript.suspend()
    await view.post(history)
    window = view.window
    window.jump_to_latest()
    await until(pilot, lambda: "MOUNTED_PAGE_23" in viewport_text(window))
    reader = history._reader()
    request = PageRequest(before=TranscriptCursor(source, 16))
    first, second = await asyncio.gather(reader.get(request), reader.get(request))
    assert first == second and first is not second
    assert first.page == page(8, 16) and first.fragments
    key = TranscriptPageWork(reader.scope, loader, reader.through, request).work_key
    retained = app.preparation._ready[key][0]
    assert await reader.get(request) == first
    assert app.preparation._ready[key][0] is retained
    # This original projection consumes ThreadWork through its production hook;
    # page fragment/Markdown tasks consume RendererWork and async page work.
    projected = await CategoryProjection(all_categories()).project(first, app.preparation)
    assert projected.fragments == first.fragments
    assert app.preparation.retained_bytes <= app.preparation.max_bytes
    print("ORIGINAL_ASYNC_PAGE_FILTER_AND_RETAINED_DELIVERY", {
        "page": [first.page.before.offset, first.page.after.offset],
        "fragments": len(first.fragments), "reads": reads,
        "ready_identity_retained": app.preparation._ready[key][0] is retained,
    }, flush=True)

    editor = view.prompt.prompt_text_area
    document, undo = editor.document, editor.history
    draft = editor.text
    assert draft, "Caller must supply its original authored draft"
    motions = []
    for event_type, count in ((events.MouseScrollUp, 12), (events.MouseScrollDown, 4),
                              (events.MouseScrollUp, 4)):
        before = viewport_text(window)
        # One native event per acquisition: the Pilot forwards through Screen,
        # pointer dispatch and bubbling to the original HistoryWindow receiver.
        for _ in range(count):
            region = window.scrollable_content_region
            offset = region.offset + (region.width // 2, region.height // 2)
            hit, _ = app.screen.get_widget_at(*offset)
            assert hit is window or window in hit.ancestors
            await pilot._post_mouse_events([event_type], offset=offset)
        await pilot.wait_for_scheduled_animations()
        await until(pilot, lambda: "MOUNTED_PAGE_" in viewport_text(window))
        painted = viewport_text(window)
        assert painted != before, "Native wheel/reversal did not change painted history"
        position = ReaderPosition.capture(window)
        assert not window.follows_tail
        assert all(admission in position.admissions for admission in history.capture_reader_admissions())
        assert editor.document is document and editor.history is undo
        assert editor.text == draft
        motions.append({"event": event_type.__name__, "count": count,
                        "scroll_y": window.scroll_y, "reader": repr(position),
                        "painted": painted})
        print("ORIGINAL_NATIVE_WHEEL_READER", motions[-1], flush=True)

    # End is a genuine focused key, not a programmatic body/cursor substitute.
    region = window.scrollable_content_region
    offset = region.offset + (region.width // 2, region.height // 2)
    await pilot.click(offset=offset)
    await pilot.pause()
    assert app.focused is window
    await pilot.press("end")
    await pilot.wait_for_scheduled_animations()
    await until(pilot, lambda: window.follows_tail and "MOUNTED_PAGE_23" in viewport_text(window))
    assert editor.document is document and editor.history is undo
    assert editor.text == draft
    assert view.agent is None and app._exception is None
    await history.retire_source()
    assert reader.closed
    await history.remove()
    return {"async_page_reads": reads, "retained_page_reused": True,
            "independent_page_delivery": True, "original_filter_projection": True,
            "native_wheel_reversal": motions, "end_tail_painted": True,
            "editor_document_undo_preserved": True, "source_scope_retired": reader.closed,
            "scope": "Authored typed-page installed App; not SDK/saved-history/physical/latency proof"}


async def acceptance(app, pilot, *, page_and_wheel=True):
    """Borrow the caller's private mounted App; return before its whole teardown.

    The caller completes and retires its own fixture history first, then
    resumes its original DocumentViewport. Its authored draft must be present.
    This leaf owns only its responses and typed pager. It does not bind another
    Agent, root or application, or modify the caller's editor draft.
    """
    project = Path(app.project_dir)
    view = app.selected_session.conversation
    sources = [f"RETURN_SOURCE_{index} file-{index}.py\n\n" + "**retained syntax** " * 20
               for index in range(2)]
    keys = [await RenderPreparation(MarkdownRenderTask(source, app.native_ansi_color,
                                                     app.current_theme.dark)).identity(app.preparation)
            for source in sources]
    retained = {}
    mounted = []
    painted_ms = []
    for index in (0, 1, 0, 1, 0):
        before = app.preparation.hits
        started = perf_counter()
        response = AgentResponse(sources[index], paginate=False)
        await view.post(response)
        response.scroll_visible(animate=False, immediate=True)
        await until(pilot, lambda: response in app.screen._compositor.visible_widgets and
                    f"RETURN_SOURCE_{index}" in viewport_text(response))
        await until(pilot, lambda: bool(response.query(MarkdownParagraph)))
        painted_ms.append((perf_counter() - started) * 1000)
        paragraphs = list(response.query(MarkdownParagraph))
        mounted.append(len(paragraphs))
        links = [span.style.meta.get("@click", "") for paragraph in paragraphs
                 for span in paragraph._content.spans if isinstance(span.style, Style)]
        expected = "toad-file-search:" if index not in retained else "toad-file:"
        assert any(expected in action for action in links), links
        value = app.preparation._ready[keys[index]][0]
        if index in retained:
            assert value is retained[index], "Return replaced retained syntax"
            assert app.preparation.hits > before, "Body return did not reuse preparation"
        else:
            retained[index] = value
            (project / f"file-{index}.py").write_text("pass\n")
        assert app.preparation.retained_bytes <= app.preparation.max_bytes
        await response.remove()
        assert not view.query(AgentResponse), "Retired body remained pooled"
    assert app._exception is None
    receipt = {
        "hits": app.preparation.hits, "misses": app.preparation.misses,
        "retained_bytes": app.preparation.retained_bytes,
        "budget": app.preparation.max_bytes, "mounted_paragraphs": mounted, "painted_ms": painted_ms,
    }
    print("INSTALLED_PAINTED_ABABA_SYNTAX_REUSE_FRESH_LINKS_NO_BODY_POOL", receipt, flush=True)
    if page_and_wheel:
        receipt["page_wheel"] = await page_wheel(app, pilot, view)
    assert view.agent is None and app._exception is None
    print("ORIGINAL_PAGE_BODY_WORKFLOW", receipt, flush=True)
    return receipt


async def main(*, output=None, page_and_wheel=False, installed_only=False):
    if installed_only:
        import agent_comms, toad, textual, sys
        for module in (agent_comms, toad, textual):
            assert Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    if output is not None:
        output.mkdir(parents=True, exist_ok=False)
    with TemporaryDirectory(dir=os.environ["TMPDIR"], prefix="syntax-return-") as directory:
        project = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(project / "wire"),
                          TOAD_TEST_ATTEMPT=f"syntax-return-{os.getpid()}",
                          XDG_CONFIG_HOME=str(project / "config"),
                          XDG_STATE_HOME=str(project / "state"),
                          XDG_DATA_HOME=str(project / "data"))
        from agent_comms.comms import Comms
        from agent_comms.threads import Thread
        from toad.widgets.comms_chat import session_thread_name

        service = Comms(project / "wire")
        service.messaging.initialize_private_initial_protocol()
        service.registry.declare(Thread(session_thread_name(project), frozenset(), str(project)))
        app = InstalledApp(project_dir=str(project))
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            if page_and_wheel:
                app.selected_session.conversation.prompt.prompt_text_area.insert("ORIGINAL_PAGE_WHEEL_DRAFT")
            receipt = await acceptance(app, pilot, page_and_wheel=page_and_wheel)
        await asyncio.get_running_loop().shutdown_default_executor()
        assert app.preparation._closed and not app.preparation._pending and not app.preparation._thread_tasks
        assert app._exception is None
        receipt["original_App_workers_joined"] = True
        if output is not None:
            (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--page-wheel", action="store_true")
    parser.add_argument("--installed-only", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(output=args.output, page_and_wheel=args.page_wheel,
                     installed_only=args.installed_only))
