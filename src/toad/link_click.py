"""The Textual frontend's click on a drawn link: the link itself rides in the style's meta."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from metaclass_registry.mro_dispatch import MroDispatch
from textual.actions import StyleAction
from textual.app import App
from textual.dom import DOMNode

from toad.line_blocks import LineLink


@dataclass(frozen=True)
class OpenLineLink(StyleAction):
    """A click on text a link drew: the widget that drew it opens the link (OpensLinks)."""

    link: LineLink

    async def run(self, app: App, namespace: DOMNode) -> bool:
        cast(MroDispatch, namespace).dispatch_sync(self.link)
        return True

    async def secondary(self, app: App, namespace: DOMNode, event: object) -> bool:
        """A right-click offers the link's own menu."""
        return await self.link.copy_menu(namespace, event)
