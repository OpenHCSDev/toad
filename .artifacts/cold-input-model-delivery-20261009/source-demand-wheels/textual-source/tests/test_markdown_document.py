"""Detached native preparation against the actual mounted Markdown owner."""

import asyncio
from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import os
import pickle

import pytest

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.geometry import Offset, Size, Spacing
from textual.layouts.stream import StreamLayout
from textual.selection import SELECT_ALL, Selection
from textual.visual import Visual
from textual.widgets import Label, Markdown
from textual.widgets._markdown import MarkdownBlock, MarkdownFence

SOURCE = """# Native document

This **strong** paragraph has [a native link](https://example.com), `code`, and 界.

> A quote with enough text to wrap when the acquired width changes.

- outer item
  - nested item
- second item

3. third
4. fourth

| left | right |
| --- | --- |
| [cell](https://example.org) | content |

```python
print('native fence')
```

---

Last paragraph.

## Repeated heading

First section.

## Repeated heading

Second section.

> ## Nested heading
>
> Nested headings do not appear in the top-level contents.
"""


class AcquiredMarkdown(Markdown):
    BLOCKS = Markdown.BLOCKS.copy()

    async def _parse_tokens(self, *args, **kwargs):
        tokens = await super()._parse_tokens(*args, **kwargs)
        self.acquired_tokens = tokens
        return tokens


async def test_document_admission_keeps_mutable_layout_palette_and_filter_inputs():
    from textual.filter import DimFilter
    from textual.layouts.grid import GridLayout

    class AdmissionApp(App):
        def compose(self):
            with VerticalScroll():
                yield AcquiredMarkdown("Original native paragraph.")

    app = AdmissionApp()
    # Acquire private native terminal inputs; do not mutate the shared theme.
    app.ansi_theme_dark = deepcopy(app.ansi_theme_dark)
    app.ansi_theme_light = deepcopy(app.ansi_theme_light)
    dim = DimFilter()
    app._filters.append(dim)
    async with app.run_test() as pilot:
        await pilot.pause()
        markdown = app.query_one(AcquiredMarkdown)
        ancestor = app.query_one(VerticalScroll)
        ancestor.styles.layout = "grid"
        await pilot.pause()
        layout = ancestor.styles.layout
        assert isinstance(layout, GridLayout)
        document = markdown.acquire_document(markdown.source, markdown.acquired_tokens)
        presentation = document.presentation
        assert presentation.current_for(markdown)

        layout.stretch_height = not layout.stretch_height
        assert not presentation.current_for(markdown)
        layout.stretch_height = not layout.stretch_height
        assert presentation.current_for(markdown)

        palette = app.ansi_theme.ansi_colors._colors
        original_color = palette[0]
        palette[0] = (1, 2, 3)
        assert not presentation.current_for(markdown)
        palette[0] = original_color
        assert presentation.current_for(markdown)

        original_factor = dim.dim_factor
        dim.dim_factor = 0.75
        assert not presentation.current_for(markdown)
        dim.dim_factor = original_factor
        assert presentation.current_for(markdown)

        ancestor.styles.color = "red"
        assert not presentation.current_for(markdown)


async def test_document_preparation_inputs_share_matches_without_participant_admission():
    from textual.document._paint import DocumentPaint

    markdown = AcquiredMarkdown("One original paragraph.")
    ancestor = VerticalScroll(markdown)
    app = App()
    async with app.run_test(size=(54, 20)) as pilot:
        await app.mount(ancestor)
        await pilot.pause()
        document = markdown.acquire_document(markdown.source, markdown.acquired_tokens)
        width = markdown.region.width
        paint = await asyncio.to_thread(document.prepare, width)
        original = DocumentPaint.preparation_inputs(document, width)
        assert paint.preparation_key == original
        assert paint.matches(document, width)

        # Genuine style writes change admission; restoring the original rule
        # absence restores answer inputs, not that publication lifetime.
        ancestor.styles.color = "red"
        ancestor.styles.clear_rule("color")
        await pilot.pause()
        rebound = document.with_presentation(markdown)
        assert document.presentation.admission != rebound.presentation.admission
        assert DocumentPaint.preparation_inputs(rebound, width) == original
        assert paint.matches(rebound, width)
        assert not paint.is_current(markdown, width)
        assert paint.with_presentation(rebound).is_current(markdown, width)

        independent = markdown.acquire_document(markdown.source, markdown.acquired_tokens)
        assert DocumentPaint.preparation_inputs(independent, width) != original
        assert not paint.matches(independent, width)
        assert not paint.matches(document, width + 1)

        assert paint.leaves
        for selected in (
            {"root_selection": SELECT_ALL},
            {"selections": {}},
            {"selections": {0: SELECT_ALL}},
            {"selection_style": Visual.selection_style(markdown)},
            {"selecting": True},
        ):
            assert DocumentPaint.preparation_inputs(document, width, **selected) != original
            assert not paint.matches(document, width, **selected)

        # Same acquired UUID with a genuinely changed grammar configuration
        # still refuses reuse. Effective style change independently refuses it.
        markdown.BULLETS = ("different native bullet",)
        changed = document.with_presentation(markdown)
        assert not document.same_source(changed)
        assert DocumentPaint.preparation_inputs(changed, width) != original
        assert not paint.matches(changed, width)
        ancestor.styles.color = "red"
        changed_style = rebound.with_presentation(markdown)
        assert changed_style.presentation.key != rebound.presentation.key
        assert DocumentPaint.preparation_inputs(changed_style, width) != original


class DocumentCodeLabel(Label):
    DEFAULT_CSS = "DocumentCodeLabel { color: magenta; padding: 1 2; }"


class DocumentFence(MarkdownFence):
    def compose(self) -> ComposeResult:
        yield self.code_label(self._highlighted_code, DocumentCodeLabel)

    @classmethod
    def document_node(cls, block):
        return block.fence_node(label_type=DocumentCodeLabel)

    @classmethod
    def document_declarations(cls):
        return cls, DocumentCodeLabel


AcquiredMarkdown.BLOCKS.update(fence=DocumentFence, code_block=DocumentFence)


def painted_characters(lines):
    """Compare actual paint and native metadata independent of segmentation."""
    return tuple(
        tuple(
            (
                character,
                str(segment.style),
                (
                    {
                        key: value
                        for key, value in segment.style.meta.items()
                        if key != "document_leaf"
                    }
                    if segment.style is not None
                    else {}
                ),
            )
            for segment in line
            for character in segment.text
        )
        for line in lines
    )


class DocumentApp(App):
    CSS = """
    VerticalScroll { scrollbar-size-vertical: 0; }
    Markdown { margin: 0; }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield AcquiredMarkdown(SOURCE)


class BoundSourceMarkdown(AcquiredMarkdown):
    """Observe actual scene suppliers without replacing native conversion."""

    live_inline_calls = 0
    live_fence_calls = 0

    def _get_token_content(self, token, *, block):
        self.live_inline_calls += 1
        return super()._get_token_content(token, block=block)

    def acquire_document_content(self):
        return MarkdownBlock._token_to_content

    def _get_prepared_fence(self, *args):
        self.live_fence_calls += 1
        return super()._get_prepared_fence(*args)


class BoundSourceApp(DocumentApp):
    def compose(self):
        with VerticalScroll():
            yield BoundSourceMarkdown(SOURCE)


@pytest.mark.asyncio
async def test_scene_controls_bind_process_returned_grammar_roots(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    app = BoundSourceApp()
    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    ) as executor:
        async with app.run_test(size=(54, 100)) as pilot:
            await pilot.pause()
            markdown = app.query_one(BoundSourceMarkdown)
            document = markdown.acquire_document(SOURCE, markdown.acquired_tokens)
            delivered = await asyncio.wrap_future(
                executor.submit(document.prepare, markdown.region.width)
            )
            worker_pids = tuple(executor._processes)

            calls = markdown.live_inline_calls, markdown.live_fence_calls
            await markdown.materialize_document(delivered)
            await pilot.pause()
            assert markdown.table_of_contents == delivered.table_of_contents
            original_members = {}

            def members(source):
                original_members[source.source_index] = source
                for child in source._blocks:
                    members(child)

            for scene, source in zip(markdown.children, delivered.roots, strict=True):
                assert scene.source_block is source
                assert scene.source == source.source_text()
                assert scene.id == source.id
                members(source)
            for scene in markdown.query(MarkdownBlock):
                source = scene.source_block
                assert source is original_members[source.source_index]
                if source._inline_token is not None:
                    assert scene._content is source._content
                if isinstance(scene, MarkdownFence):
                    assert scene.code == source.code
                    assert scene._highlighted_code.is_same(
                        source.highlight(app.native_ansi_color, app.current_theme.dark)
                    )
            assert (markdown.live_inline_calls, markdown.live_fence_calls) == calls

            # Theme/style refresh is a new paint input, not a new source lineage.
            app.theme = "textual-light"
            markdown.disabled = True
            await pilot.pause()
            changed = delivered.document.with_presentation(markdown)
            assert changed.dark != document.dark
            assert changed.child_pseudo_classes != document.child_pseudo_classes
            assert changed.presentation.key != document.presentation.key
            assert changed.same_source(document)
            assert not delivered.is_current(markdown, delivered.width)
            assert all(scene.source_block is source for scene, source in
                       zip(markdown.children, delivered.roots, strict=True))

            # Eviction reconstructs the exact members, never a token-range match.
            before = tuple(markdown.children)
            await markdown.remove_children()
            await markdown.materialize_document(delivered)
            assert all(scene is not old and scene.source_block is source
                       for scene, old, source in
                       zip(markdown.children, before, delivered.roots, strict=True))
            assert (markdown.live_inline_calls, markdown.live_fence_calls) == calls
            retained = tuple(markdown.query(MarkdownBlock))
            await markdown.append("\n\nA native streamed successor.")
            assert markdown.source.endswith("A native streamed successor.")
            assert all(scene.source_block is None for scene in retained)
            assert all(scene.source_block is None for scene in markdown.query(MarkdownBlock))
            await markdown.update(SOURCE)
            assert all(scene.source_block is None for scene in markdown.query(MarkdownBlock))
            replacement = markdown.acquire_document(SOURCE, markdown.acquired_tokens)
            assert not replacement.same_source(document)

    assert all(not os.path.exists(f"/proc/{pid}") for pid in worker_pids)


class GrammarExtension(MarkdownBlock):
    def __init__(self, markdown, token, marker, *, source_block=None):
        self.marker = marker
        super().__init__(markdown, token, source_block=source_block)

    @classmethod
    def document_node(cls, block):
        cls._require_native_document(constructor=cls.__init__)
        return cls.native_document_node(block)


def acquired_grammar_extension(token, create):
    if token.type == "html_block":
        return create("html_block", token, "original-constructor-argument")
    return None


class ExtendedSourceMarkdown(AcquiredMarkdown):
    BLOCKS = {**AcquiredMarkdown.BLOCKS, "html_block": GrammarExtension}

    def unhandled_token(self, token):
        if token.type == "html_block":
            return GrammarExtension(self, token, "original-constructor-argument")
        return None

    def acquire_document_unhandled(self):
        return acquired_grammar_extension


@pytest.mark.asyncio
async def test_scene_factory_retains_custom_grammar_and_constructor():
    class GrammarApp(App):
        def compose(self):
            yield ExtendedSourceMarkdown("<native-extension>\noriginal\n</native-extension>\n")

    app = GrammarApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        markdown = app.query_one(ExtendedSourceMarkdown)
        document = markdown.acquire_document(markdown.source, markdown.acquired_tokens)
        paint = await asyncio.to_thread(document.prepare, markdown.region.width)
        assert len(paint.roots) == 1
        assert paint.roots[0].declaration is GrammarExtension
        await markdown.materialize_document(paint)
        scene = markdown.query_one(GrammarExtension)
        assert scene.source_block is paint.roots[0]
        assert scene.marker == "original-constructor-argument"
        await markdown.append("\n<native-extension>\nnext\n</native-extension>\n")
        assert all(block.marker == "original-constructor-argument"
                   and block.source_block is None
                   for block in markdown.query(GrammarExtension))


@pytest.mark.asyncio
async def test_source_binding_refuses_a_new_resolved_supplier():
    app = BoundSourceApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        markdown = app.query_one(BoundSourceMarkdown)
        document = markdown.acquire_document(SOURCE, markdown.acquired_tokens)
        # An independent supplier declaration is not a style-only refresh.
        markdown.acquire_document_content = lambda: lambda token: MarkdownBlock._token_to_content(token)
        changed = document.with_presentation(markdown)
        assert not document.same_source(changed)


class IndependentlyAcquiredMarkdown(AcquiredMarkdown):
    document = None

    def get_current_document(self):
        return self.document


@pytest.mark.asyncio
async def test_independent_source_owner_revokes_scene_without_native_update():
    class IndependentApp(App):
        def compose(self):
            yield IndependentlyAcquiredMarkdown("Original acquired source.")

    app = IndependentApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        markdown = app.query_one(IndependentlyAcquiredMarkdown)
        document = markdown.acquire_document(markdown.source, markdown.acquired_tokens)
        markdown.document = document
        paint = await asyncio.to_thread(document.prepare, markdown.region.width)
        await markdown.materialize_document(paint)
        root = markdown.children[0]
        assert root.source_block is paint.roots[0]
        markdown.styles.color = "red"
        markdown.document = document.with_presentation(markdown)
        assert root.source_block is paint.roots[0]
        # A requested source string is not the acquired source of old controls.
        markdown._markdown = "A pending independent source."
        assert root.source == paint.roots[0].source_text()
        markdown._markdown = document.source
        # The owner's fresh acquisition supersedes old controls despite equal
        # source text, without calling either native update or append.
        markdown.document = markdown.acquire_document(markdown.source, markdown.acquired_tokens)
        assert root.source_block is None
        before = tuple(markdown.children)
        with pytest.raises(ValueError, match="current source"):
            markdown.materialize_document(paint)
        assert tuple(markdown.children) == before
        assert markdown.source == "Original acquired source."
        # Native source requests revoke scene custody even if the independently
        # acquired owner still retains the preceding document.
        markdown.document = document
        await markdown.materialize_document(paint)
        root = markdown.children[0]
        assert root.source_block is paint.roots[0]
        publication = markdown.append(" A native successor.")
        assert root.source_block is None
        await publication
        assert root.source_block is None


class BeforeMountMarkdown(Markdown):
    async def _parse_tokens(self, parser, markdown, *, use_thread):
        tokens = await super()._parse_tokens(parser, markdown, use_thread=use_thread)
        assert not self.children
        self.host_pseudos = frozenset(self.get_pseudo_classes())
        self.document = self.acquire_document(markdown, tokens)
        self.document_paint = await asyncio.to_thread(
            self.document.prepare, self.region.width,
            root_selection=self.text_selection,
            selection_style=(Visual.selection_style(self) if self.text_selection is not None else None),
            selecting=self.screen._selecting,
        )
        return tokens


class BeforeMountApp(App):
    CSS = """
    VerticalScroll { scrollbar-size-vertical: 0; }
    BeforeMountMarkdown { margin: 0; background: cyan; padding: 0 2; }
    BeforeMountMarkdown:empty { background: red; padding: 1 3; }
    BeforeMountMarkdown:last-child { border-left: solid yellow; }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Label("Actual host sibling")
            yield BeforeMountMarkdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source, expected_empty",
    (
        pytest.param("A direct native document.", False, id="paragraph"),
        pytest.param("", True, id="empty-source"),
        pytest.param("<!-- no native roots -->", True, id="unhandled-comment"),
    ),
)
async def test_source_empty_membership_before_native_mount(
    source, expected_empty, monkeypatch
):
    monkeypatch.delenv("NO_COLOR", raising=False)
    app = BeforeMountApp()
    async with app.run_test(size=(54, 30)) as pilot:
        await pilot.pause()
        markdown = app.query_one(BeforeMountMarkdown)
        await markdown.update(source)
        # Membership publication changes the parent's :empty answer. Mount's
        # sibling-order callback does not own that parent style publication.
        markdown.update_node_styles()
        await pilot.pause()
        paint = markdown.document_paint
        assert "empty" in markdown.host_pseudos
        assert "empty" not in markdown.document.presentation.root.pseudo_classes
        assert "last-child" in markdown.document.presentation.root.pseudo_classes
        assert paint.root_empty == markdown.is_empty
        assert paint.root_empty is expected_empty
        size, mounted, _ = app.screen._compositor.render_subtree_strips(
            markdown, app.screen._compositor.find_widget(markdown)
        )
        assert paint.size == size
        assert paint.gutter == markdown.styles.gutter
        assert painted_characters(paint.lines) == painted_characters(mounted)
        refreshed = markdown.document.with_presentation(markdown)
        assert (
            refreshed.presentation.root.key == markdown.document.presentation.root.key
        )


class EmptyDisplayApp(BeforeMountApp):
    CSS = (
        BeforeMountApp.CSS + "BeforeMountMarkdown MarkdownParagraph { display: none; }"
    )


class StreamBeforeMountApp(BeforeMountApp):
    CSS = BeforeMountApp.CSS + "VerticalScroll { layout: stream; }"


@pytest.mark.asyncio
async def test_root_selection_before_leaves_matches_native_scene_and_readiness(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    app = BeforeMountApp()
    async with app.run_test(size=(54, 100)) as pilot:
        await pilot.pause()
        markdown = app.query_one(BeforeMountMarkdown)
        assert not markdown.children
        app.screen._select_all_in_widget(markdown)
        await markdown.update(SOURCE)
        markdown.update_node_styles()
        await pilot.pause()
        document = markdown.document.with_presentation(markdown)
        style = Visual.selection_style(markdown)
        assert markdown.document_paint.root_selection == SELECT_ALL
        assert markdown.document_paint.selection_style == style
        assert markdown.document_paint.document.same_source(document)
        # Mount can add further native default CSS sources. Their actual
        # ordered supply is a new acquired presentation, not counter equality.
        paint = await asyncio.to_thread(
            document.prepare, markdown.region.width,
            root_selection=SELECT_ALL, selection_style=style,
        )
        assert paint.leaves
        assert paint.root_selection == SELECT_ALL
        assert paint.selections is None
        assert paint.is_current(markdown, paint.width)
        assert not paint.matches(document, paint.width)

        # The native mounted oracle acquires its own actual descendants. The
        # detached preparation above had only the root selection at ingress.
        app.screen._select_all_in_widget(markdown)
        await pilot.pause()
        _, mounted, _ = app.screen._compositor.render_subtree_strips(
            markdown, app.screen._compositor.find_widget(markdown)
        )
        assert painted_characters(markdown.document_paint.lines) == painted_characters(mounted)
        assert painted_characters(paint.lines) == painted_characters(mounted)
        unselected = await asyncio.to_thread(document.prepare, paint.width)
        assert not unselected.is_current(markdown, paint.width)
        assert any(a != b for a, b in zip(painted_characters(paint.lines), painted_characters(unselected.lines)))
        app.screen.clear_selection()
        await pilot.pause()
        assert not paint.is_current(markdown, paint.width)
        assert unselected.is_current(markdown, paint.width)
        with pytest.raises(ValueError, match="whole widget"):
            await asyncio.to_thread(
                document.prepare, paint.width,
                root_selection=Selection(Offset(0, 0), Offset(3, 0)),
                selection_style=style,
            )


@pytest.mark.asyncio
async def test_partial_leaf_selection_uses_original_offsets_and_native_style(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    app = DocumentApp()
    async with app.run_test(size=(54, 100)) as pilot:
        await pilot.pause()
        markdown = app.query_one(AcquiredMarkdown)
        document = markdown.acquire_document(SOURCE, markdown.acquired_tokens)
        paint = await asyncio.to_thread(document.prepare, markdown.region.width)
        index = next(i for i, leaf in enumerate(paint.leaves) if leaf.declaration is DocumentCodeLabel)
        selection = Selection.from_offsets(Offset(1, 0), Offset(6, 0))
        selections = {index: selection}
        app.screen.selections = {markdown.query_one(DocumentCodeLabel): selection}
        await pilot.pause()
        selected = await asyncio.to_thread(
            paint.prepare_selection, selections, Visual.selection_style(markdown)
        )
        assert selected.root_selection is None
        assert selected.is_current(markdown, paint.width, selections=selections)
        assert not selected.is_current(markdown, paint.width)
        selections.clear()
        assert selected.selections == ((index, selection),)
        _, mounted, _ = app.screen._compositor.render_subtree_strips(
            markdown, app.screen._compositor.find_widget(markdown)
        )
        assert painted_characters(selected.lines) == painted_characters(mounted)


@pytest.mark.asyncio
async def test_complete_document_request_and_paint_cross_spawn_process(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    app = StreamBeforeMountApp()
    async with app.run_test(size=(54, 30)) as pilot:
        await pilot.pause()
        markdown = app.query_one(BeforeMountMarkdown)
        scene_layout = markdown.parent.layout
        assert isinstance(scene_layout, StreamLayout)
        assert scene_layout._cached_placements
        scene_placements = scene_layout._cached_placements
        await markdown.update(SOURCE)
        markdown.update_node_styles()
        await pilot.pause()
        document = markdown.document.with_presentation(markdown)
        selection_style = Visual.selection_style(markdown)
        local = await asyncio.to_thread(
            document.prepare, markdown.region.width,
            root_selection=SELECT_ALL, selection_style=selection_style,
        )
        # Semantic root membership is supplied by the same native grammar,
        # not reconstructed from descendant placement or paint order.
        assert [(root.declaration, root.source_range) for root in local.roots] == [
            (type(root), root.source_range) for root in markdown.children
        ]
        assert [root.placement.region for root in local.roots] == [
            root.region.translate(-markdown.region.offset) for root in markdown.children
        ]
        acquired_layout = document.presentation.ancestors[-1].base_rules["layout"]
        assert isinstance(acquired_layout, StreamLayout)
        assert acquired_layout is not scene_layout
        assert acquired_layout._cached_placements is None
        assert all(placement.widget.parent is markdown.parent
                   for placement in scene_placements)

    # The request no longer borrows a running App or widget. Both complete
    # request and complete result traverse the original spawn/pickle boundary.
    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    ) as executor:
        future = executor.submit(
            document.prepare, local.width,
            root_selection=SELECT_ALL, selection_style=selection_style,
        )
        remote = await asyncio.wrap_future(future)
        worker_pids = tuple(executor._processes)

    assert all(not os.path.exists(f"/proc/{pid}") for pid in worker_pids)
    assert remote.matches(
        document, local.width,
        root_selection=SELECT_ALL, selection_style=selection_style,
    )
    assert not remote.matches(document, local.width)
    assert type(remote.gutter) is Spacing
    assert type(remote.size) is Size
    assert remote.gutter == local.gutter
    assert remote.size == local.size
    assert remote.content_size == local.content_size
    assert remote.root_empty == local.root_empty
    assert remote.blocks == local.blocks
    assert remote.table_of_contents == local.table_of_contents
    assert all(root.document is remote.document for root in remote.roots)
    assert [
        (root.declaration, root.source_index, root.source_range, root.code, root.source_text(), root.placement)
        for root in remote.roots
    ] == [
        (root.declaration, root.source_index, root.source_range, root.code, root.source_text(), root.placement)
        for root in local.roots
    ]
    assert [root.code for root in remote.roots if root.code is not None] == ["print('native fence')"]
    assert painted_characters(remote.lines) == painted_characters(local.lines)


@pytest.mark.asyncio
async def test_display_changing_empty_selector_requires_explicit_source(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    app = EmptyDisplayApp()
    async with app.run_test(size=(54, 30)) as pilot:
        await pilot.pause()
        with pytest.raises(TypeError, match="display changes an :empty selector input"):
            await app.query_one(BeforeMountMarkdown).update("A hidden source child.")


@pytest.mark.asyncio
async def test_native_document_rows_currentness_and_interactions(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    app = DocumentApp()
    async with app.run_test(size=(54, 100)) as pilot:
        await pilot.pause()
        markdown = app.query_one(AcquiredMarkdown)
        document = markdown.acquire_document(SOURCE, markdown.acquired_tokens)
        paint = await asyncio.to_thread(document.prepare, markdown.region.width)
        size, mounted, _ = app.screen._compositor.render_subtree_strips(
            markdown,
            app.screen._compositor.find_widget(markdown),
        )
        assert paint.size == size
        assert paint.gutter == markdown.styles.gutter
        assert paint.content_size == size.region.shrink(paint.gutter).size
        assert [(level, title) for level, title, _ in paint.table_of_contents] == [
            (level, title) for level, title, _ in markdown.table_of_contents
        ]
        assert all(heading.placement is not None for heading in paint.headings)
        assert paint.anchor_region("repeated-heading") is not None
        assert paint.anchor_region("repeated-heading-1") is not None
        assert paint.anchor_region("repeated-heading") != paint.anchor_region(
            "repeated-heading-1"
        )
        assert paint.anchor_region("nested-heading") is None
        assert tuple(line.text for line in paint.lines) == tuple(
            line.text for line in mounted
        )
        assert painted_characters(paint.lines) == painted_characters(mounted)
        assert paint.is_current(markdown, size.width)
        # Returned worker data retain this original acquisition identity.
        delivered = pickle.loads(pickle.dumps(paint))
        assert delivered.matches(document, size.width)
        assert delivered.table_of_contents == paint.table_of_contents
        assert not delivered.matches(
            markdown.acquire_document(SOURCE, markdown.acquired_tokens), size.width
        )
        assert any(
            "@click" in segment.style.meta
            for line in paint.lines
            for segment in line
            if segment.style is not None
        )
        assert any(leaf.selected_text(Selection(None, None)) for leaf in paint.leaves)
        assert any(leaf.declaration is DocumentCodeLabel for leaf in paint.leaves)
        link = next(
            (x, y)
            for y, line in enumerate(paint.lines)
            for x in range(line.cell_length)
            if "@click" in line.get_style_at(x).meta
        )
        leaf_index, offset = paint.get_leaf_and_offset_at(*link)
        assert leaf_index is not None and offset is not None
        assert paint.leaves[leaf_index].selected_text(Selection(None, None))
        assert any(
            block.source_text(document).startswith("# Native") for block in paint.blocks
        )
        markdown.styles.color = "red"
        assert not paint.is_current(markdown, size.width)
        refreshed = document.with_presentation(markdown)
        updated = await asyncio.to_thread(refreshed.prepare, size.width)
        assert updated.is_current(markdown, size.width)
        await pilot.resize_terminal(38, 100)
        await pilot.pause()
        current = document.with_presentation(markdown)
        assert not paint.matches(current, markdown.region.width)
        resized = await asyncio.to_thread(current.prepare, markdown.region.width)
        size, mounted, _ = app.screen._compositor.render_subtree_strips(
            markdown,
            app.screen._compositor.find_widget(markdown),
        )
        assert resized.size == size
        assert tuple(line.text for line in resized.lines) == tuple(
            line.text for line in mounted
        )
        assert painted_characters(resized.lines) == painted_characters(mounted)
        assert resized.table_of_contents == paint.table_of_contents
