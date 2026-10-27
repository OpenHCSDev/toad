"""Native question bindings, availability and selection share one declaration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from textual.binding import Binding
from textual.widgets.text_area import EditingMode
from toad.widget_actions import Action

if TYPE_CHECKING:
    from toad.widgets.question import Question


class QuestionAction(Action, affix="Action"):
    pass


class SelectionAction(QuestionAction):
    """Move the selection through the options."""

    group = Binding.Group("Cursor", compact=True)
    show = True

    def available(self, question):
        return question.accepts_selection


class SelectionUpAction(SelectionAction):
    keys = {EditingMode: ("up",)}

    async def apply(self, question):
        question._reset_blink()
        question.selection = max(0, question.selection - 1)


class SelectionDownAction(SelectionAction):
    keys = {EditingMode: ("down",)}

    async def apply(self, question):
        question._reset_blink()
        question.selection = min(len(question.options) - 1, question.selection + 1)


class SelectAction(QuestionAction):
    """Answer with the selected option."""

    keys = {EditingMode: ("enter",)}
    show = True

    def available(self, question):
        return question.accepts_selection

    async def apply(self, question):
        question._reset_blink()
        question.post_message(question.Answer(question.selection,
                             question.options[question.selection], question._ask))
        question.selected = True
        question.refresh_bindings()


@dataclass(frozen=True)
class SelectKindAction(QuestionAction):
    kinds: tuple[str, ...]
    # ACP PermissionOption.kind is the external accepted taxonomy; aliases removed.
    SHORTCUTS = {"allow_once": ("a", "Allow once"),
                 "allow_always": ("A", "Allow always"),
                 "reject_once": ("r", "Reject once"),
                 "reject_always": ("R", "Reject always")}

    @classmethod
    def bindings(cls, *, priority=False):
        return tuple(Binding(key, f"{cls.declared_name}({kind!r})", label,
                             group=Binding.Group(label.split()[0] + " once/always", compact=True),
                             priority=priority)
                     for kind, (key, label) in cls.SHORTCUTS.items())

    @classmethod
    def parse(cls, parameters):
        match parameters:
            case (str() as kind,):
                return cls((kind,))
            case (tuple() as kinds,) if all(isinstance(kind, str) for kind in kinds):
                return cls(kinds)
        raise ValueError("select_kind requires one kind or tuple of kinds")

    def available(self, question):
        return question.accepts_selection and any(answer.kind in self.kinds for answer in question.options)

    async def apply(self, question):
        for kind in self.kinds:
            for index, answer in enumerate(question.options):
                if answer.kind == kind:
                    question.selection = index
                    await SelectAction().apply(question)
                    return
