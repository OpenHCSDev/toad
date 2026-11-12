"""Pure choice and change-effect declarations shared by settings and renderers."""

from __future__ import annotations

from annotationlib import Format, get_annotations
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, cast

from agent_comms.nominal.declared_choice import DeclaredChoice
from objectstate.lazy_factory import LazyResolutionDataclass
from python_introspect import AnnotatedDataclassValidationMixin, AnnotationChoices
from toad.settings_scope import SettingsScope

if TYPE_CHECKING:
    from formbridge.forms.declared_fields import DeclaredField

    from toad.app import ToadApp


class SettingsDeclaration(AnnotatedDataclassValidationMixin, LazyResolutionDataclass):
    """An actual settings record and the scopes its own field declarations admit."""

    configuration_scopes: ClassVar[tuple[type[SettingsScope], ...]] = ()

    def __init_subclass__(cls, *, scopes: tuple[type[SettingsScope], ...] = (), **kwargs):
        super().__init_subclass__(**kwargs)
        cls.configuration_scopes = scopes

    @classmethod
    def field_source(cls, name: str) -> type[SettingsDeclaration]:
        return next(owner for owner in cls.__mro__
                    if name in get_annotations(owner, format=Format.STRING))

    @classmethod
    def admits_field(cls, name: str, scope: SettingsScope) -> bool:
        return any(isinstance(scope, admitted)
                   for admitted in cls.field_source(name).configuration_scopes)


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
        return app.settings_widgets(widget_type)


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
