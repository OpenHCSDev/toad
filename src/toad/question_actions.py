"""Native question bindings, availability and selection share one declaration."""
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal
from abc import abstractmethod

from formbridge.key_declarations import TextEntryMode
from textual.binding import Binding

from toad.widget_actions import Action

if TYPE_CHECKING:
    from toad.widgets.question import Question


class ChoiceQuestion:
    """A question whose options the user picks from: the owner the selection actions act on.

    Plain mixin, no toolkit base, so Textual's `Question` (a `VerticalGroup`) and Qt's
    `QtQuestion` (a `QFrame`) both inherit it without crossing metaclasses.
    """

    @abstractmethod
    def select_answer(self, index: int) -> None:
        """Pick the option at `index` and finalise the answer. Each toolkit implements its
        own commit path: Textual posts the Answer event and flips its reactive `selected`;
        Qt retracts the inline panel and fires the `Ask`'s callback. The family's
        `SelectAction` / `SelectKindAction` call this instead of touching toolkit-specific
        plumbing, so one declared key fires the same selection on either side."""


class QuestionContext:
    """Inline questions and their review screen select the same question owner.

    Plain mixin, no toolkit base: Textual's `Question` already inherits DOMNode
    via `containers.VerticalGroup`, and `PermissionsScreen` via `Screen[Answer]`.
    A Qt Question widget lists this mixin beside `QWidget` without dragging
    Textual's metaclass into its MRO. The context only names its question; selecting
    belongs to the `ChoiceQuestion` it names, so a review screen that delegates to its
    own question owes no selection of its own.
    """
    @property
    @abstractmethod
    def question(self) -> ChoiceQuestion: ...


class QuestionAction(Action[QuestionContext], affix="Action"):
    context_capability = QuestionContext

    def available(self, context):
        return context.question.accepts_selection


class SelectionAction(QuestionAction):
    """Move the selection through the options."""

    group = Binding.Group("Cursor", compact=True)
    show = True


class SelectAction(QuestionAction):
    """Answer with the selected option."""

    saved_key = "QuestionSelectAction"  # toad.widget_actions.SelectAction is saved as SelectAction

    keys = {TextEntryMode: ("enter",)}
    show = True

    def apply(self, context):
        question = context.question
        question.select_answer(question.selection)


class SelectKindAction(QuestionAction, declared_name=None):
    """Answer with the first option of the declared external permission kind."""
    kind: ClassVar[Literal["allow_once", "allow_always", "reject_once", "reject_always"]]
    show = True

    def available(self, context):
        return super().available(context) and any(answer.kind == self.kind for answer in context.question.options)

    def apply(self, context):
        question = context.question
        for index, answer in enumerate(question.options):
            if answer.kind == self.kind:
                question.select_answer(index)
                return


class AllowOnceAction(SelectKindAction):
    kind = "allow_once"
    title = "Allow once"
    keys = {TextEntryMode: ("a",)}
    group = Binding.Group("Allow once/always", compact=True)


class AllowAlwaysAction(SelectKindAction):
    kind = "allow_always"
    title = "Allow always"
    keys = {TextEntryMode: ("A",)}
    group = AllowOnceAction.group


class RejectOnceAction(SelectKindAction):
    kind = "reject_once"
    title = "Reject once"
    keys = {TextEntryMode: ("r",)}
    group = Binding.Group("Reject once/always", compact=True)


class RejectAlwaysAction(SelectKindAction):
    kind = "reject_always"
    title = "Reject always"
    keys = {TextEntryMode: ("R",)}
    group = RejectOnceAction.group


class PermissionNavigationAction(Action, declared_name=None):
    group = Binding.Group("Navigation", compact=True)
    show = True


class NextChangeAction(PermissionNavigationAction):
    keys = {TextEntryMode: ("j",)}

    async def apply(self, context):
        context.navigator.action_cursor_down()


class PreviousChangeAction(PermissionNavigationAction):
    keys = {TextEntryMode: ("k",)}

    async def apply(self, context):
        context.navigator.action_cursor_up()
