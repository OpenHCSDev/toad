"""Native nodes bound to Toad's application contract."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.dom import DOMNode

if TYPE_CHECKING:
    from toad.app import ToadApp


class ToadNode(DOMNode):
    """Keep the application refinement on one shared native parent."""

    app: ToadApp
