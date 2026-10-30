"""Pure choice and change-effect declarations shared by settings and renderers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from agent_comms.declared_choice import DeclaredChoice
from python_introspect import AnnotationChoices

if TYPE_CHECKING:
    from formbridge.forms.declared_fields import DeclaredField

    from toad.app import ToadApp


@dataclass(frozen=True)
class FamilyChoices[ChoiceT: DeclaredChoice](AnnotationChoices):
    family: type[ChoiceT]

    def choices(self) -> tuple[type[ChoiceT], ...]:
        return tuple(self.family.members_with(self.family))

    def label(self, choice: object) -> str:
        # AnnotationChoices erases the type at its UI boundary; choices() supplies
        # members of this declared nominal family.
        return cast(type[ChoiceT], choice).choice_label()


@dataclass(frozen=True)
class Effect:
    apply: Callable[[ToadApp, DeclaredField], None]

    @staticmethod
    def open_widgets(app, widget_type):
        roots = (*app.workspace_sessions.views.values(), *app.screen_stack)
        return {widget for root in roots for widget in root.walk_children(widget_type)}


class EachOpenWidget(Effect):
    """A widget capability's own method as a setting effect.

    The class the method is declared on is the widget type: a change runs the
    method on every open widget composing that capability.
    """

    owner: type

    def __init__(self, method: Callable[[object], None]) -> None:
        super().__init__(self.on_each_open)
        self.method = method

    def __set_name__(self, owner: type, name: str) -> None:
        self.owner = owner

    def on_each_open(self, app: ToadApp, field: DeclaredField) -> None:
        for widget in self.open_widgets(app, self.owner):
            self.method(widget)
