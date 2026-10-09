"""Initial publication keeps its own receipt, including deferred body owners."""

import asyncio
from functools import partial

import pytest
from markdown_it import MarkdownIt

from textual.app import App
from textual.await_complete import AwaitComplete
from textual.worker import WorkerCancelled, WorkerFailed
from textual.widgets import Markdown


class PreparedDocument(Markdown):
    """An authored application using the original native worker / callback owners."""

    def __init__(self, source, *, parser_factory=None):
        super().__init__(source, parser_factory=parser_factory)
        self.parsing = asyncio.Event()
        self.release = asyncio.Event()
        self.observing = asyncio.Event()

    def update(self, markdown):
        publication = super().update(markdown)
        self.source_worker = self.run_worker(publication, exit_on_error=False)
        return AwaitComplete(self.source_worker.wait())

    def _initialize_document(self, markdown):
        self.initial_publication = super()._initialize_document(markdown)
        self.call_later(self.initial_publication)
        return AwaitComplete.nothing()

    async def _parse_tokens(self, parser, markdown, *, use_thread):
        self.parsing.set()
        await self.release.wait()
        return await super()._parse_tokens(parser, markdown, use_thread=use_thread)

    async def on_callback(self, event):
        if (isinstance(event.callback, partial)
                and event.callback.func is self.initial_publication):
            self.observing.set()
        await super().on_callback(event)


class DocumentApp(App):
    def __init__(self):
        super().__init__()
        self.toc = []

    def on_markdown_table_of_contents_updated(self, message):
        self.toc.append(message.table_of_contents)


@pytest.mark.parametrize("source", [None, "# Acquired document"])
async def test_prepared_owner_mounts_before_publication_without_early_toc(source):
    app = DocumentApp()
    document = PreparedDocument(source)
    async with app.run_test() as pilot:
        await app.mount(document)
        assert document.is_mounted
        await asyncio.wait_for(document.observing.wait(), 2)
        assert not document.initial_publication.is_done
        assert not document.query("MarkdownBlock")
        assert not app.toc
        document.release.set()
        await document.initial_publication
        await pilot.pause()
        if source:
            assert document.query("MarkdownBlock")
        else:
            assert not document.query("MarkdownBlock")
        assert len(app.toc) == (2 if source is None else 1)
        assert app.toc[-1] == document.table_of_contents


async def test_deferred_original_receipt_reports_custom_parser_failure():
    def parser_factory():
        parser = MarkdownIt("gfm-like")

        def refuse(_state):
            raise ValueError("declared parser refused initial source")

        parser.core.ruler.push("declared_refusal", refuse)
        return parser

    app = DocumentApp()
    document = PreparedDocument("# Refused source", parser_factory=parser_factory)
    with pytest.raises(WorkerFailed, match="declared parser refused initial source"):
        async with app.run_test():
            await app.mount(document)
            await asyncio.wait_for(document.observing.wait(), 2)
            assert document.is_mounted and not app.toc
            document.release.set()
            await asyncio.wait_for(asyncio.shield(document._task), 2)
    assert isinstance(document.source_worker.error, ValueError)
    assert document.initial_publication.is_done
    assert not app.toc


async def test_original_worker_cancellation_releases_queued_observer_and_unmount():
    app = DocumentApp()
    document = PreparedDocument("# Cancelled source")
    async with app.run_test():
        await app.mount(document)
        await asyncio.wait_for(document.observing.wait(), 2)
        removal = document.remove()
        document.workers.cancel_node(document)
        await asyncio.wait_for(removal, 2)
        with pytest.raises(WorkerCancelled):
            await document.initial_publication
        assert document.source_worker.is_cancelled
        assert not document.is_attached
        assert not app.toc
        assert app._exception is None
