"""The Textual frontend's click on a drawn link: the link itself rides in the style's meta."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from metaclass_registry.mro_dispatch import MroDispatch
from textual.actions import StyleAction
from textual.widgets._markdown import MarkdownLink

from toad.line_blocks import LineLink, NoLink

if TYPE_CHECKING:
    from textual.app import App
    from textual.dom import DOMNode


@dataclass(frozen=True)
class OpenLineLink(StyleAction):
    """A click on text a link drew: the widget that drew it opens the link (OpensLinks)."""

    link: LineLink

    async def run(self, app: App, namespace: DOMNode) -> None:
        cast(MroDispatch, namespace).dispatch_sync(self.link)

    @staticmethod
    def link_of(action: StyleAction | None) -> LineLink:
        """The link a decoded style action opens, for a right-click's menu; a Markdown href
        carries a link through markdown-it's string-only attributes. Anything else leads nowhere."""
        match action:
            case OpenLineLink(link=link):
                return link
            case MarkdownLink(href=href) if href.startswith(LineLink.href_scheme):
                return LineLink.from_href(href)
        return NoLink()
