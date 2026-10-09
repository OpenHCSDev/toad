"""Unit tests for the Markdown widget."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterator

import pytest
from markdown_it.token import Token
from rich.text import Span

import textual.widgets._markdown as MD
from textual import on
from textual.app import App, ComposeResult
from textual.content import Content
from textual.style import Style
from textual.widget import Widget
from textual.widgets import Markdown
from textual.widgets.markdown import MarkdownBlock


class UnhandledToken(MarkdownBlock):
    def __init__(self, markdown: Markdown, token: Token) -> None:
        super().__init__(markdown)
        self._token = token

    def __repr___(self) -> str:
        return self._token.type


class FussyMarkdown(Markdown):
    def unhandled_token(self, token: Token) -> MarkdownBlock | None:
        return UnhandledToken(self, token)


class MarkdownApp(App[None]):
    def __init__(self, markdown: str) -> None:
        super().__init__()
        self._markdown = markdown

    def compose(self) -> ComposeResult:
        yield FussyMarkdown(self._markdown)


@pytest.mark.parametrize("kind", ["list", "table"])
async def test_driver_wheel_completes_during_nested_markdown_construction(kind):
    """A single root must not retain the UI turn for its whole token tree."""
    from textual import events
    from textual.containers import VerticalScroll
    from textual.widgets import Static

    delivered = asyncio.Event()
    construction = []
    at_delivery = []
    rows = 40
    source = (
        "\n".join(f"- row {index}\n  - nested {index}" for index in range(rows))
        if kind == "list" else
        "| Heading |\n| --- |\n" + "\n".join(f"| row {index} |" for index in range(rows))
    )

    class Document(Markdown):
        def get_block_class(self, name):
            if name in ("paragraph_open", "td_open"):
                construction.append(name)
                if len(construction) == 1:
                    reader = self.app.query_one("#reader", VerticalScroll)
                    point = reader.scrollable_content_region.offset
                    target, _ = self.app.get_widget_at(point.x + 1, point.y + 1)
                    assert target is reader or reader in target.ancestors
                    self.app._driver.process_message(events.MouseScrollDown(
                        None, point.x + 1, point.y + 1, 0, 0, 0, False, False, False
                    ))
            return super().get_block_class(name)

    class ReadingApp(App):
        def compose(self):
            with VerticalScroll(id="reader"):
                yield Static("Existing body\n" * 60, id="reader-body")
                yield Document(id="document")

        async def on_event(self, event):
            ingress = isinstance(event, events.MouseScrollDown) and not event.is_forwarded
            result = await super().on_event(event)
            if ingress:
                at_delivery.append((len(construction), event.widget))
                delivered.set()
            return result

    app = ReadingApp()
    async with app.run_test(size=(60, 16)) as pilot:
        await pilot.pause()
        assert app.query_one("#reader", VerticalScroll).allow_vertical_scroll
        document = app.query_one(Document)
        publication = document.update(source)
        try:
            await asyncio.wait_for(delivered.wait(), 3)
            assert not publication.is_done
            reader = app.query_one("#reader", VerticalScroll)
            assert reader.scroll_y > 0, (at_delivery, reader.max_scroll_y, reader.region)
        finally:
            await publication
        assert at_delivery[0][0] < len(construction)
        assert len(document.children) == 1
        assert all(child.is_mounted for child in document.walk_children())
        assert document.source == source
        assert app._compose_stacks == [] and app._composed == []


@pytest.mark.parametrize("parked", [False, True])
async def test_stream_empty_stop_joins_without_publication(parked):
    appends = []

    class ObservedMarkdown(Markdown):
        async def append(self, fragment):
            appends.append(fragment)
            await super().append(fragment)

    document = ObservedMarkdown()
    async with App().run_test() as pilot:
        await pilot.app.mount(document)
        stream = document.get_stream(document)
        task = stream._task
        if parked:
            await asyncio.sleep(0)
        await stream.stop()
        assert appends == []
        assert task.done() and not task.cancelled()
        assert stream._task is None and stream._stopped
        await stream.stop()
        with pytest.raises(RuntimeError):
            await stream.write("late")


async def test_stream_stop_drains_real_append_before_propagating_caller_cancellation():
    entered = asyncio.Event()
    release = asyncio.Event()

    class HeldMarkdown(Markdown):
        async def append(self, fragment):
            entered.set()
            await release.wait()
            await super().append(fragment)

    document = HeldMarkdown()
    async with App().run_test() as pilot:
        await pilot.app.mount(document)
        stream = document.get_stream(document)
        await stream.write("first\n\n")
        await entered.wait()
        await stream.write("second")
        worker = stream._task
        stopping = asyncio.create_task(stream.stop())
        await asyncio.sleep(0)
        stopping.cancel()
        await asyncio.sleep(0)
        assert not stopping.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await stopping
        assert worker.done() and not worker.cancelled()
        assert stream._task is None and stream._stopped
        assert document._markdown == "first\n\nsecond"


async def test_document_supplies_inline_content_for_heading_paragraph_and_table():
    class CustomParagraph(MD.MarkdownParagraph):
        def _token_to_content(self, token: Token) -> Content:
            return super()._token_to_content(token) + Content(" custom")

    class SuppliedMarkdown(Markdown):
        BLOCKS = {**Markdown.BLOCKS, "paragraph_open": CustomParagraph}

        def _get_token_content(self, token: Token, *, block: MarkdownBlock) -> Content:
            return super()._get_token_content(token, block=block) + Content(" supplied")

    document = SuppliedMarkdown(
        "# Heading\n\nParagraph [link](https://example.com)\n\n"
        "| Header |\n| --- |\n| Cell |"
    )
    async with App().run_test() as pilot:
        await pilot.app.mount(document)
        await pilot.pause()
        assert document.query_one(MD.MarkdownH1)._content.plain == "Heading supplied"
        paragraph = document.query_one(MD.MarkdownParagraph)._content
        assert paragraph.plain == "Paragraph link custom supplied"
        assert paragraph.spans == [
            MD.Span(10, 14, Style.from_meta({"@click": "link('https://example.com')"}))
        ]
        table = document.query_one(MD.MarkdownTable)
        assert [content.plain for content in table._headers] == ["Header supplied"]
        assert [[content.plain for content in row] for row in table._rows] == [["Cell supplied"]]


@pytest.mark.parametrize(
    ["document", "expected_nodes"],
    [
        # Basic markup.
        ("", []),
        ("# Hello", [MD.MarkdownH1]),
        ("## Hello", [MD.MarkdownH2]),
        ("### Hello", [MD.MarkdownH3]),
        ("#### Hello", [MD.MarkdownH4]),
        ("##### Hello", [MD.MarkdownH5]),
        ("###### Hello", [MD.MarkdownH6]),
        ("---", [MD.MarkdownHorizontalRule]),
        ("Hello", [MD.MarkdownParagraph]),
        ("Hello\nWorld", [MD.MarkdownParagraph]),
        ("> Hello", [MD.MarkdownBlockQuote, MD.MarkdownParagraph]),
        ("- One\n-Two", [MD.MarkdownBulletList, MD.MarkdownParagraph]),
        (
            "1. One\n2. Two",
            [MD.MarkdownOrderedList, MD.MarkdownParagraph, MD.MarkdownParagraph],
        ),
        ("    1", [MD.MarkdownFence]),
        ("```\n1\n```", [MD.MarkdownFence]),
        ("```python\n1\n```", [MD.MarkdownFence]),
        ("""| One | Two |\n| :- | :- |\n| 1 | 2 |""", [MD.MarkdownTable]),
        # Test for https://github.com/Textualize/textual/issues/2676
        (
            "- One\n```\nTwo\n```\n- Three\n",
            [
                MD.MarkdownBulletList,
                MD.MarkdownParagraph,
                MD.MarkdownFence,
                MD.MarkdownBulletList,
                MD.MarkdownParagraph,
            ],
        ),
    ],
)
async def test_markdown_nodes(
    document: str, expected_nodes: list[Widget | list[Widget]]
) -> None:
    """A Markdown document should parse into the expected Textual node list."""

    def markdown_nodes(root: Widget) -> Iterator[MarkdownBlock]:
        for node in root.children:
            if isinstance(node, MarkdownBlock):
                yield node
            yield from markdown_nodes(node)

    async with MarkdownApp(document).run_test() as pilot:
        await pilot.pause()
        assert [
            node.__class__ for node in markdown_nodes(pilot.app.query_one(Markdown))
        ] == expected_nodes


async def test_softbreak_split_links_rendered_correctly() -> None:
    """Test for https://github.com/Textualize/textual/issues/2805"""

    document = """\
My site [has
this
URL](https://example.com)\
"""
    async with MarkdownApp(document).run_test() as pilot:
        markdown = pilot.app.query_one(Markdown)
        paragraph = markdown.children[0]
        assert isinstance(paragraph, MD.MarkdownParagraph)
        assert paragraph._content.plain == "My site has this URL"
        print(paragraph._content.spans)

        expected_spans = [
            Span(8, 20, Style.from_meta({"@click": "link('https://example.com')"})),
        ]
        print(expected_spans)

    assert paragraph._content.spans == expected_spans


async def test_load_non_existing_file() -> None:
    """Loading a file that doesn't exist should result in the obvious error."""
    async with MarkdownApp("").run_test() as pilot:
        with pytest.raises(FileNotFoundError):
            await pilot.app.query_one(Markdown).load(
                Path("---this-does-not-exist---.it.is.not.a.md")
            )


@pytest.mark.parametrize(
    ("anchor", "found"),
    [
        ("hello-world", False),
        ("hello-there", True),
    ],
)
async def test_goto_anchor(anchor: str, found: bool) -> None:
    """Going to anchors should return a boolean: whether the anchor was found."""
    document = "# Hello There\n\nGeneral.\n"
    async with MarkdownApp(document).run_test() as pilot:
        markdown = pilot.app.query_one(Markdown)
        assert markdown.goto_anchor(anchor) is found


async def test_update_of_document_posts_table_of_content_update_message() -> None:
    """Updating the document should post a TableOfContentsUpdated message."""

    messages: list[str] = []

    class TableOfContentApp(App[None]):
        def compose(self) -> ComposeResult:
            yield Markdown("# One\n\n#Two\n")

        @on(Markdown.TableOfContentsUpdated)
        def log_table_of_content_update(
            self, event: Markdown.TableOfContentsUpdated
        ) -> None:
            nonlocal messages
            messages.append(event.__class__.__name__)

    async with TableOfContentApp().run_test() as pilot:

        assert messages == ["TableOfContentsUpdated"]
        await pilot.app.query_one(Markdown).update("")
        await pilot.pause()
        assert messages == ["TableOfContentsUpdated", "TableOfContentsUpdated"]


async def test_link_in_markdown_table_posts_message_when_clicked():
    """A link inside a markdown table should post a `Markdown.LinkClicked`
    message when clicked.

    Regression test for https://github.com/Textualize/textual/issues/4683
    """

    markdown_table = """\
| Textual Links                                    |
| ------------------------------------------------ |
| [GitHub](https://github.com/textualize/textual/) |
| [Documentation](https://textual.textualize.io/)  |\
"""

    class MarkdownTableApp(App):
        messages = []

        def compose(self) -> ComposeResult:
            yield Markdown(markdown_table, open_links=False)

        @on(Markdown.LinkClicked)
        def log_markdown_link_clicked(
            self,
            event: Markdown.LinkClicked,
        ) -> None:
            self.messages.append(event.__class__.__name__)

    app = MarkdownTableApp()
    async with app.run_test() as pilot:
        await pilot.click(Markdown, offset=(8, 3))
        print(app.messages)
        assert app.messages == ["LinkClicked"]


async def test_markdown_quoting():
    # https://github.com/Textualize/textual/issues/3350
    links = []

    class MyApp(App):
        def compose(self) -> ComposeResult:
            self.md = Markdown(markdown="[tété](tété)", open_links=False)
            yield self.md

        def on_markdown_link_clicked(self, message: Markdown.LinkClicked):
            links.append(message.href)

    app = MyApp()
    async with app.run_test() as pilot:
        await pilot.click(Markdown, offset=(3, 0))
    assert links == ["t%C3%A9t%C3%A9"]
