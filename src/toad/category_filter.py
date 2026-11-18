"""The native view that owns the visible transcript categories."""

from agent_comms.ui_model.message_category import MessageCategory, all_categories
from textual.dom import DOMNode
from textual.reactive import var

from toad.client.category_selection import CategorySelection


class CategoryFilterView(CategorySelection, DOMNode):
    """Conversation content and filter controls observe the same reactive selection."""

    visible_categories: var[frozenset[type[MessageCategory]]] = var(
        lambda: all_categories(), init=False
    )

    def categories_changed(self) -> None:
        """The reactive's watchers redraw the transcript on the write itself."""
