"""Native question bindings, availability and selection share one declaration."""
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal
from abc import abstractmethod

from textual.binding import Binding
from textual.dom import DOMNode
from textual.widgets.text_area import EditingMode
from toad.widget_actions import Action

if TYPE_CHECKING:
    from toad.widgets.question import Question


class QuestionContext(DOMNode):
    """Inline questions and their review screen select the same question owner."""
    @property
    @abstractmethod
    def question(self) -> Question: ...


class QuestionAction(Action[QuestionContext], affix="Action"):
    pass


class SelectionAction(QuestionAction):
    """Move the selection through the options."""

    group = Binding.Group("Cursor", compact=True)
    show = True

    def available(self, context):
        return context.question.accepts_selection


class SelectionUpAction(SelectionAction):
    keys = {EditingMode: ("up",)}

    async def apply(self, context):
        question = context.question
        question._reset_blink()
        question.selection = max(0, question.selection - 1)


class SelectionDownAction(SelectionAction):
    keys = {EditingMode: ("down",)}

    async def apply(self, context):
        question = context.question
        question._reset_blink()
        question.selection = min(len(question.options) - 1, question.selection + 1)


class SelectAction(QuestionAction):
    """Answer with the selected option."""

    keys = {EditingMode: ("enter",)}
    show = True

    def available(self, context):
        return context.question.accepts_selection

    async def apply(self, context):
        question = context.question
        question._reset_blink()
        question.post_message(question.Answer(question.selection,
                             question.options[question.selection], question._ask))
        question.selected = True
        question.refresh_bindings()


class SelectKindAction(QuestionAction, declared_name=None):
    """Answer with the first option of the declared external permission kind."""
    kind: ClassVar[Literal["allow_once", "allow_always", "reject_once", "reject_always"]]
    show = True

    def available(self, context):
        question = context.question
        return question.accepts_selection and any(answer.kind == self.kind for answer in question.options)

    async def apply(self, context):
        question = context.question
        for index, answer in enumerate(question.options):
            if answer.kind == self.kind:
                question.selection = index
                await SelectAction().apply(context)
                return


class AllowOnceAction(SelectKindAction):
    kind = "allow_once"
    title = "Allow once"
    keys = {EditingMode: ("a",)}
    group = Binding.Group("Allow once/always", compact=True)


class AllowAlwaysAction(SelectKindAction):
    kind = "allow_always"
    title = "Allow always"
    keys = {EditingMode: ("A",)}
    group = AllowOnceAction.group


class RejectOnceAction(SelectKindAction):
    kind = "reject_once"
    title = "Reject once"
    keys = {EditingMode: ("r",)}
    group = Binding.Group("Reject once/always", compact=True)


class RejectAlwaysAction(SelectKindAction):
    kind = "reject_always"
    title = "Reject always"
    keys = {EditingMode: ("R",)}
    group = RejectOnceAction.group


class PermissionNavigationAction(Action, declared_name=None):
    group = Binding.Group("Navigation", compact=True)
    show = True


class NextChangeAction(PermissionNavigationAction):
    keys = {EditingMode: ("j",)}

    async def apply(self, context):
        context.navigator.action_cursor_down()


class PreviousChangeAction(PermissionNavigationAction):
    keys = {EditingMode: ("k",)}

    async def apply(self, context):
        context.navigator.action_cursor_up()
