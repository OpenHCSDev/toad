"""Read-only native documents with detached preparation and live reader intent."""
from __future__ import annotations

import asyncio
from functools import partial

from textual.document._document import Document, DocumentBase
from textual.document._document_navigator import DocumentNavigator
from textual.document._wrapped_document import WrappedDocument
from textual.worker import Worker
from textual.widgets._text_area import TextArea


class PreparedTextArea(TextArea):
    """Keep TextArea selection/navigation while preparing plain text off-loop.

    Editors retain TextArea's synchronous load/edit contract. This read-only
    surface explicitly awaits prepared loads; resizing coalesces on the native
    worker lifetime and publishes only a matching document/width/tab view.
    """

    def __init__(self, text: str = "", **kwargs):
        super().__init__(text, read_only=True, language=None, **kwargs)

    @staticmethod
    def prepare_document(source: str | DocumentBase, width: int, tab_width: int) -> WrappedDocument:
        document = Document(source if isinstance(source, str) else source.text)
        return WrappedDocument(document, width, tab_width)

    async def _prepare_document(self, source: str | DocumentBase,
                                width: int, tab_width: int) -> WrappedDocument:
        """Applications may supply their existing detached process renderer."""
        return await asyncio.to_thread(self.prepare_document, source, width, tab_width)

    def load_text_prepared(self, text: str) -> Worker[None]:
        return self.run_worker(partial(self._load_prepared, text), group="prepared-document-load",
                               exclusive=True)

    async def _load_prepared(self, text: str) -> None:
        original = self.document
        # Even an unchanged publication owns cancellation of its predecessor.
        # Keep equality and document lifetime here, not in individual readers.
        if original.text == text:
            return
        source = text
        while self.is_attached and not self._pruning and self.document is original:
            width = self.wrap_width_for(original if isinstance(source, str) else source)
            tabs = self.indent_width
            prepared = await self._prepare_document(source, width, tabs)
            if not self.is_attached or self._pruning or self.document is not original:
                return
            if (width, tabs) != (self.wrap_width_for(prepared.document), self.indent_width):
                source = prepared.document
                continue
            if (prepared.document.lines == original.lines and
                    prepared.document.newline == original.newline):
                return
            self.history.clear()
            self._highlight_query = None
            self._set_document_view(prepared)
            self._line_cache.clear()
            self._refresh_size()
            self.post_message(self.Changed(self).set_sender(self))
            self.update_suggestion()
            return

    def _rewrap_and_refresh_virtual_size(self) -> None:
        if not self.is_attached:
            return super()._rewrap_and_refresh_virtual_size()
        if any(worker.node is self and worker.group == "prepared-document-wrap"
               and not worker.is_finished for worker in self.workers):
            return
        self.run_worker(self._prepare_wrapping, group="prepared-document-wrap")

    async def _prepare_wrapping(self) -> None:
        while self.is_attached and not self._pruning:
            document = self.document
            width, tabs = self.wrap_width, self.indent_width
            wrapped = self.wrapped_document
            if (wrapped.document is document and
                    (wrapped._width, wrapped._tab_width) == (width, tabs)):
                # Native edits update this same view incrementally. A resize
                # with unchanged wrapping inputs needs scrollbar/size refresh,
                # not another detached document and navigator.
                self._refresh_size()
                if (width, tabs) == (self.wrap_width, self.indent_width):
                    return
                # Scrollbar publication can itself change the wrapping width.
                continue
            prepared = await self._prepare_document(document, width, tabs)
            if not self.is_attached or self._pruning:
                return
            if (document is not self.document or (width, tabs) !=
                    (self.wrap_width, self.indent_width)):
                continue
            # Programmatic native edits may mutate a read-only document while
            # preparation is outstanding. Compare its actual lines/newline,
            # not a copied revision or a separate source signature.
            if (document.lines != prepared.document.lines or
                    document.newline != prepared.document.newline):
                continue
            reader = self.wrapped_document.offset_to_location(self.scroll_offset)
            prepared.document = document
            self.wrapped_document = prepared
            self.navigator = DocumentNavigator(prepared)
            self._line_cache.clear()
            self._refresh_size()
            offset = prepared.location_to_offset(reader)
            self.scroll_to(x=offset.x, y=offset.y, animate=False, immediate=True)
            self.record_cursor_width()
            # Admit the resulting scrollbar geometry through the same matching
            # resource decision before declaring this worker complete.
