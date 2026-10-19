"""Pure choice and change-effect declarations shared by settings and renderers."""

from __future__ import annotations

from abc import ABC
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from agent_comms.declared_family import DeclaredFamily
from python_introspect import AnnotationChoices

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.forms.declared_views import DeclaredField


class Choice(ABC):
    title: ClassVar[str | None] = None

    @classmethod
    def label(cls) -> str:
        return cls.title or cls.declared_name.replace("-", " ").replace("_", " ").title()


@dataclass(frozen=True)
class FamilyChoices(AnnotationChoices):
    family: type[DeclaredFamily]

    def choices(self) -> tuple[object, ...]:
        return tuple(self.family.members_with(self.family))

    def label(self, choice: object) -> str:
        return choice.label()


@dataclass(frozen=True)
class Effect:
    apply: Callable[[ToadApp, DeclaredField], None]

    @staticmethod
    def open_widgets(app, widget_type):
        roots = (*app.workspace_sessions.views.values(), *app.screen_stack)
        return {widget for root in roots for widget in root.walk_children(widget_type)}
