"""Installed native source return preserves a non-tail reader with bounded data.

One real Pi/ACP source is visited through four logical tabs. No transport,
restoration, source loader or body renderer is replaced by a test double.
"""
import asyncio
from dataclasses import dataclass
from weakref import ReferenceType, ref
import difflib
import gc
import json
import os
from pathlib import Path

from l0a_native_installed_pilot import main as native_fixture, until
from native_session_retention_pilot import InstalledApp, conversation_paint
from toad.screens.main import MainScreen
from textual.widget import Widget
from textual.widgets._markdown import MarkdownBlock
from toad.widgets.prepared_markdown import PreparedConversationMarkdown
from toad.widgets.transcript_history import TranscriptFragmentView
from agent_comms.transcript_events import TextTranscript
from toad.widgets.agent_response import AgentResponse
from toad.widgets.transcript_fragments import TranscriptRenderTask
from toad.work_preparation import RenderPreparation


READER_TEXT = "READER_POSITION_3"


def response_geometry(conversation):
    """Expose the actual native leaf extent and its owned retirement state."""
    return [(node.source, node.region, node.virtual_size, node.body_dormant,
             node._body_measurement, node.loading,
             [(type(child).__name__, child.region, child.styles.margin)
              for child in node.children])
            for node in conversation.query(AgentResponse)]


async def settled(pilot, view):
    window = view.window
    await until(pilot, lambda: (
        window.document_viewport._worker is None
        and window.document_viewport.visible_bodies_ready
        and all(history.state.accepts_source_work
                for history in window.histories)
    ))
    # Body readiness describes preparation, not completion of the native frame
    # that consumes it. Sample the reader only after that actual paint boundary.
    painted = asyncio.Event()
    window.call_after_refresh(painted.set)
    await until(pilot, painted.is_set)


@dataclass
class ReaderCheckpoint:
    source: object
    document: object
    history: object
    text: str
    reader_y: float
    follows_tail: bool
    pages: tuple[tuple[object, tuple[object, ...]], ...]
    fragments: tuple[tuple[object, ...], ...]
    fragment_views: tuple[tuple[Widget, ...], ...]
    painted: str
    rendered_bodies: tuple[ReferenceType[MarkdownBlock], ...]
    rendered_content: tuple[object, ...]

    @staticmethod
    def record_failed_reader(source, app):
        view = source.conversation
        evidence = Path(os.environ["L0A_EVIDENCE"])
        diagnostic = {
            "source": source.id,
            "native_session": view.agent.session_id,
            "reader_region": str(view.window.region),
            "reader_virtual_size": str(view.window.virtual_size),
            "scroll_y": view.window.scroll_y,
            "max_scroll_y": view.window.max_scroll_y,
            "markdown": [{
                "region": str(body.region), "virtual_size": str(body.virtual_size),
                "display": body.display, "ready": body.body_ready,
                "children": len(body.children), "parent": type(body.parent).__name__,
            } for body in view.query(PreparedConversationMarkdown)],
        }
        (evidence / "body-return-geometry.json").write_text(json.dumps(diagnostic, indent=2))
        (evidence / "body-return-reader.txt").write_text(conversation_paint(app.screen))
        (evidence / "body-return.svg").write_text(app.export_screenshot())
        print("BODY_RETURN_GEOMETRY_FAILURE", diagnostic, flush=True)

    @classmethod
    async def capture(cls, source, app, pilot):
        view = source.conversation
        await settled(pilot, view)
        editor = view.prompt.prompt_text_area
        region = view.window.scrollable_content_region
        bodies = tuple(block for markdown in view.query(PreparedConversationMarkdown)
                       for block in markdown.query(MarkdownBlock)
                       if block in app.screen._compositor.visible_widgets
                       if block.region.overlaps(region))
        assert len(bodies) > 0, "Checkpoint needs actually rendered native Markdown bodies"
        pages = tuple((history, tuple(history.pages)) for history in view.window.histories)
        return cls(source, editor.document, editor.history, editor.text,
                   view.window.scroll_y, view.window.follows_tail, pages,
                   tuple(page.fragments for _, cohort in pages for page in cohort),
                   tuple(page.fragment_views for _, cohort in pages for page in cohort),
                   conversation_paint(app.screen), tuple(ref(block) for block in bodies),
                   tuple(block._render_cache for block in bodies))

    async def page_reads(self):
        agent = self.source.presentation.sources.agent
        async with agent.controller.transcripts.bind(agent.coordination.wire_root) as reader:
            return reader.transcripts.page_reads

    async def verify(self, app, pilot):
        view = self.source.conversation
        await settled(pilot, view)
        editor = view.prompt.prompt_text_area
        assert editor.document is self.document
        assert editor.history is self.history
        assert editor.text == self.text
        assert view.window.scroll_y == self.reader_y
        assert view.window.follows_tail is self.follows_tail
        current_pages = tuple((history, tuple(history.pages)) for history in view.window.histories)
        assert current_pages == self.pages, "Warm return replaced unchanged committed page resources"
        current_fragments = tuple(page.fragments for _, pages in current_pages for page in pages)
        assert len(current_fragments) == len(self.fragments)
        assert all(current is original for current, original in zip(current_fragments, self.fragments)), (
            "Warm return rebuilt unchanged source-owned prepared fragments", self.source.id
        )
        current_views = tuple(page.fragment_views for _, pages in current_pages for page in pages)
        assert len(current_views) == len(self.fragment_views)
        for current, original in zip(current_views, self.fragment_views):
            assert len(current) == len(original)
            assert all(view is previous for view, previous in zip(current, original)), (
                "Warm return replaced unchanged committed native fragment views", self.source.id
            )
        assert conversation_paint(app.screen) == self.painted
        current_bodies = {block for block in view.query(MarkdownBlock)
                          if block in app.screen._compositor.visible_widgets}
        for body, rendered in zip(self.rendered_bodies, self.rendered_content):
            assert body() in current_bodies, (
                "Native tab return replaced a previously rendered Markdown body",
                self.source.id, body(),
            )
            assert body()._render_cache is rendered, (
                "Warm return rendered an unchanged Markdown body again",
                self.source.id, body(), rendered.size, body()._render_cache.size,
            )
        print("CLICKED_RETURN_ACTUAL_RENDERED_BODY_IDENTITY", self.source.id,
              len(self.rendered_bodies), flush=True)


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    frame, source = app.screen, app.selected_session
    original_agent = agent
    process, runner = agent.process.process, agent.process.runner
    release.set()
    for index in range(4):
        prompt = f"READER_POSITION_{index}\n\n" + "\n\n".join(
            f"Source {index} paragraph {row}: retained canonical reader text."
            for row in range(12)
        )
        await asyncio.wait_for(agent.send_prompt(prompt), 25)
        await until(pilot, lambda: not comms.registry.require("beta").executing)
    await until(pilot, lambda: "NATIVE_RESPONSE_4" in conversation_paint(frame))
    # Reopen through the ordinary source owner before choosing a saved reader
    # record. Direct Agent input doesn't synthesize the UI's live UserInput;
    # the actual native journal snapshot publishes that canonical content.
    modes = []
    for index in range(3):
        details = await app.session_navigation.new(lambda: MainScreen(
            original_agent.project_root_path, agent_session_id=f"recent-return-{index}"))
        modes.append(details.mode_name)
        await pilot.pause(.02)
    await app.select_session(source.id)
    await until(pilot, lambda: "NATIVE_RESPONSE_4" in conversation_paint(frame))
    conversation = source.conversation
    await settled(pilot, conversation)
    window = conversation.window
    # Visible text can precede the pager's next measured layout. Establish a
    # real scroll range before selecting a non-tail record; zero is not a saved
    # reader position for this acceptance path.
    await until(pilot, lambda: window.max_scroll_y > 0)
    candidates = [node for node in conversation.query(TranscriptFragmentView)
                  if any(READER_TEXT in event.text
                         for event in node.fragment.events if isinstance(event, TextTranscript))]
    assert candidates, "Native source did not publish the selected reader record"
    window.release_anchor()
    window.scroll_to_widget(candidates[0], animate=False, immediate=True, top=True)
    await until(pilot, lambda: READER_TEXT in conversation_paint(frame))
    print("RECENT_POSITION", window.scroll_y, window.max_scroll_y, window.follows_tail, flush=True)
    await settled(pilot, conversation)
    before_y = window.scroll_y
    assert before_y < window.max_scroll_y and not window.follows_tail
    print("RECENT_INITIAL_GEOMETRY", [(type(node).__name__, node.region, node.virtual_size,
          node.show_vertical_scrollbar) for node in (window, *window.ancestors) if isinstance(node, Widget)], flush=True)
    source_paint = conversation_paint(frame)
    canonical_page = next(iter(window.histories)).pages[-1].page
    prepared_key = await RenderPreparation(TranscriptRenderTask(canonical_page.events)).identity(app.preparation)
    assert prepared_key in app.preparation._ready, "Canonical snapshot bypassed bounded reusable preparation"
    prepared_value = app.preparation._ready[prepared_key][0]
    source_responses = response_geometry(conversation)
    source_geometry = [
        (page.start, page.stop, page.region, tuple(
            (node.region, tuple(type(child).__name__ for child in node.children))
            for node in page.fragment_views
        )) for pager in window.histories for page in pager.pages
    ]
    editor = conversation.prompt.prompt_text_area
    document, history = editor.document, editor.history
    records = []
    for mode in modes:
        await app.select_session(mode)
        await pilot.pause(.02)
        await app.select_session(source.id)
        await until(pilot, lambda: READER_TEXT in conversation_paint(frame))
        restored = source.conversation
        await settled(pilot, restored)
        assert restored is conversation and app.screen is frame
        assert restored.agent is original_agent
        assert agent.process.process is process and agent.process.runner is runner
        assert process.returncode is None and not runner.done()
        assert not restored.window.follows_tail
        assert app.preparation._ready[prepared_key][0] is prepared_value, "Recent return rebuilt canonical fragment preparation"
        print("RECENT_PREPARATION_REUSED", app.preparation.retained_bytes,
              app.preparation.max_bytes, flush=True)
        if restored.window.scroll_y != before_y:
            print("RECENT_RETURN_GEOMETRY", [(type(node).__name__, node.region, node.virtual_size,
                  node.show_vertical_scrollbar) for node in (restored.window, *restored.window.ancestors) if isinstance(node, Widget)], flush=True)
            current_paint = conversation_paint(frame)
            print("RECENT_PAINT_DIAGNOSTIC", source_paint == current_paint,
                  [index for index, line in enumerate(source_paint.splitlines()) if READER_TEXT in line],
                  [index for index, line in enumerate(current_paint.splitlines()) if READER_TEXT in line], flush=True)
            print("RECENT_READER_DIAGNOSTIC", [(history.fragment_count, history.has_older,
                  (not history.state.accepts_source_work), history._check_pending, history.selected_categories,
                  history.region, frame._compositor.visible_widgets.get(history))
                  for history in restored.window.histories], flush=True)
        assert restored.window.scroll_y == before_y, (restored.window.scroll_y, before_y, restored.window.max_scroll_y, restored.window.scrollable_content_region)
        if conversation_paint(frame) != source_paint:
            print("RECENT_PAINT_DIFF", "\n".join(difflib.unified_diff(
                source_paint.splitlines(), conversation_paint(frame).splitlines(),
                fromfile="departing", tofile="returned")), flush=True)
            print("RECENT_PAINT_GEOMETRY", window.virtual_size, window.region,
                  window.show_vertical_scrollbar, window.scrollable_content_region, flush=True)
            print("RECENT_FRAGMENT_GEOMETRY", source_geometry, [
                (page.start, page.stop, page.region, tuple(
                    (node.region, tuple(type(child).__name__ for child in node.children))
                    for node in page.fragment_views
                )) for pager in window.histories for page in pager.pages
            ], flush=True)
            print("RECENT_RESPONSE_GEOMETRY", source_responses,
                  response_geometry(restored), flush=True)
        assert conversation_paint(frame) == source_paint
        assert restored.prompt.prompt_text_area is editor
        assert editor.document is document and editor.history is history
        assert len(requests) == 4, "Source return replayed native input"
        rich = {id(view) for owner in app.workspace_sessions.views.values()
                for view in owner.query("Conversation")}
        assert len(rich) == 1
        assert app.preparation.retained_bytes <= app.preparation.max_bytes
        gc.collect()
        records.append({"return_mode": mode, "scroll_y": restored.window.scroll_y,
                        "rich_views": len(rich), "native_calls": len(requests),
                        "prepared_bytes": app.preparation.retained_bytes,
                        "preparation_hits": app.preparation.hits,
                        "preparation_misses": app.preparation.misses})
    Path(os.environ["RECENT_SOURCE_RECEIPT"]).write_text(json.dumps(records, indent=2))
    print("Installed native non-tail return/cropped reader/editor/source lifetime passed", flush=True)


if __name__ == "__main__":
    asyncio.run(native_fixture(app_type=InstalledApp, acceptance=acceptance))
