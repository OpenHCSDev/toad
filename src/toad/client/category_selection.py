"""Which message categories a view's transcript shows, owned once for both frontends.

Textual's `CategoryFilterView` and Qt's conversation and thread views inherit
`CategorySelection`; the thread sidebar's comms panel toggles a category through
`set_category` on whichever selection its view answers. A view that filters nothing answers
`NoCategorySelection`, and the panel hides its toggles.
"""

from __future__ import annotations

from agent_comms.ui_model.message_category import MessageCategory, all_categories


class CategorySelection:
    """A view whose transcript shows a selection of message categories.

    A plain parent, as `SessionScope` is: ABCMeta would conflict with each toolkit's widget
    metaclass. Each frontend's view stores `visible_categories` in its own field (Textual a
    reactive, Qt an attribute) and redraws in `categories_changed`."""

    visible_categories: frozenset[type[MessageCategory]]
    filters = True
    """The comms panel shows this selection's toggles."""

    @property
    def category_selection(self) -> CategorySelection:
        return self

    def set_category(self, category: type[MessageCategory], on: bool) -> None:
        """Show or hide one category, then let the transcript draw the shown rows again."""
        selected = self.visible_categories
        self.visible_categories = selected | {category} if on else selected - {category}
        self.categories_changed()

    def categories_changed(self) -> None:
        """The selection changed: frontends whose write does not redraw on its own override."""


class NoCategorySelection(CategorySelection):
    """A view that filters nothing (the welcome, an opening view): every category shows and
    the panel offers no toggles."""

    filters = False
    visible_categories = all_categories()

    def set_category(self, category: type[MessageCategory], on: bool) -> None:
        raise RuntimeError("This view filters no categories; its panel offers no toggle")
