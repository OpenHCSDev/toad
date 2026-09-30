"""Native question bindings, availability and selection share one declaration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_comms.declared_family import DeclaredFamily
from textual.binding import Binding
from toad.application_actions import NativeAction, KeyboundAction

if TYPE_CHECKING:
    from toad.widgets.question import Question


class QuestionAction(NativeAction["Question"], DeclaredFamily, affix="Action"):
    @classmethod
    def bindings(cls):
        return ()


class SelectionAction(KeyboundAction, QuestionAction):
    key: str
    description: str

    group = Binding.Group("Cursor", compact=True)
    show = True

    def available(self, question):
        return not question.selected and bool(question.options)


class SelectionUpAction(SelectionAction):
    key = "up"
    description = "Up"

    async def apply(self, question):
        question._reset_blink()
        question.selection = max(0, question.selection - 1)


class SelectionDownAction(SelectionAction):
    key = "down"
    description = "Down"

    async def apply(self, question):
        question._reset_blink()
        question.selection = min(len(question.options) - 1, question.selection + 1)


class SelectAction(KeyboundAction, QuestionAction):
    key = "enter"
    description = "Select"
    show = True

    def available(self, question):
        return not question.selected and 0 <= question.selection < len(question.options)

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
        return not question.selected and any(answer.kind in self.kinds for answer in question.options)

    async def apply(self, question):
        for kind in self.kinds:
            for index, answer in enumerate(question.options):
                if answer.kind == kind:
                    question.selection = index
                    await SelectAction().apply(question)
                    return
