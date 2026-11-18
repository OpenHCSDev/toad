"""The line-block painter contract every frontend inherits.

Fragments draw one shared `LineBlock` family (`HistoryFragment.blocks(shown)`); a frontend
paints each kind through its own most-specific handler. The kinds a fragment can emit are
declared here once, abstract, so a frontend that skips one fails when it is instantiated
instead of raising "declares no projection" the first time a reader expands a tool call.
A subclass keeps `@handles` on its override: an undecorated override drops the handler.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from metaclass_registry.mro_dispatch import handles

from toad.client.line_blocks import (
    Body, Divider, Gap, LineLink, LineRole, NoLink, SpanColumns, Spans, Summary, TextRole,
)
from toad.core.projection import MroProjection
from toad.message_rows import WireBody
from toad.patch import Patch
from toad.rich_preparation import RichTextBody


class LineBlockPainter[Result](MroProjection[Result], ABC):
    """Each shared block kind through this frontend's painter."""

    @handles(Divider)
    @abstractmethod
    def divider(self, block: Divider) -> Result:
        """A rule with the message header's spans centred in it."""

    @handles(Gap)
    @abstractmethod
    def gap(self, block: Gap) -> Result:
        """One blank line between messages."""

    @handles(Summary)
    @abstractmethod
    def summary(self, block: Summary) -> Result:
        """One row: a collapsed tool call, read receipt or context line."""

    @handles(Spans)
    @abstractmethod
    def spans(self, block: Spans) -> Result:
        """Wrapped styled spans, each optionally a link."""

    @handles(SpanColumns)
    @abstractmethod
    def span_columns(self, block: SpanColumns) -> Result:
        """Cells flowing into columns at the drawing width."""

    @handles(Body)
    @abstractmethod
    def body(self, block: Body) -> Result:
        """Text, Markdown or code, optionally behind an accent bar."""

    @handles(WireBody)
    @abstractmethod
    def wire_body(self, block: WireBody) -> Result:
        """A bus message's own text, laid out by its message style."""

    @handles(Patch)
    @abstractmethod
    def patch(self, block: Patch) -> Result:
        """An edit's diff, as an expanded tool call shows it."""

    @handles(RichTextBody)
    @abstractmethod
    def rich_text(self, block: RichTextBody) -> Result:
        """Terminal output, as an expanded tool call shows it."""


class LinkPresentation[Result](MroProjection[Result], ABC):
    """What a frontend adds to text that leads somewhere; text that leads nowhere is plain."""

    markdown_role: ClassVar[type[LineRole]] = TextRole.linked()
    """A link inside a Markdown body is drawn as linked body text."""

    @handles(LineLink)
    @abstractmethod
    def linked(self, link: LineLink) -> Result:
        """Text that runs `link` when clicked, underlined when the link says so."""

    @handles(NoLink)
    @abstractmethod
    def plain(self, link: NoLink) -> Result:
        """Text that leads nowhere."""
