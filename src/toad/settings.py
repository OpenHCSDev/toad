"""Typed preference declarations, one load boundary and descriptor-owned editing."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, overload

from agent_comms.field_codec import FieldCodec
from textual.widget import Widget

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.setting_choices import Choice

T = TypeVar("T")
G = TypeVar("G", bound="SettingsGroup")
_UNSET = object()


def no_effect(app: ToadApp, value: object) -> None:
    """Preference is consumed directly when its operation runs."""


class SettingsNode(ABC):
    def __init__(
        self,
        *,
        title: str,
        help: str = "",
        editable: bool = True,
        wire_name: str | None = None,
    ) -> None:
        self.title, self.help, self.editable = title, help, editable
        self._wire_name = wire_name

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    @property
    def wire_name(self) -> str:
        return self._wire_name or self.name.replace("_", "-")

    @abstractmethod
    def load(self, group: SettingsGroup, raw: object, present: bool) -> None: ...

    @abstractmethod
    def encode(self, group: SettingsGroup) -> object: ...

    @abstractmethod
    def form(self, group: SettingsGroup) -> Widget: ...

    @abstractmethod
    def leaves(self, group: SettingsGroup) -> Iterator[BoundSetting]: ...


class SettingKind[T](SettingsNode):
    def __init__(
        self,
        *,
        default: T,
        effect: Callable[[ToadApp, T], None] = no_effect,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.default, self.effect = default, effect

    @overload
    def __get__(self, group: None, owner: type | None = None) -> SettingKind[T]: ...
    @overload
    def __get__(self, group: SettingsGroup, owner: type | None = None) -> T: ...
    def __get__(self, group, owner=None):
        return self if group is None else group._values[self.name]

    def __set__(self, group: SettingsGroup, value: T) -> None:
        if group._values[self.name] == value:
            return
        group._values[self.name] = value
        group._present.add(self.name)
        group._mark_present()
        group._root._changed = True
        group._root._notify(PreferenceChange(self, value))

    @abstractmethod
    def parse(self, raw: object) -> T: ...

    @abstractmethod
    def widget(self, bound: BoundSetting[T]) -> Widget: ...

    def load(self, group: SettingsGroup, raw: object, present: bool) -> None:
        group._values[self.name] = self.parse(raw) if present else self.default

    def encode(self, group: SettingsGroup) -> object:
        return FieldCodec.encode(self.__get__(group))

    def leaves(self, group: SettingsGroup) -> Iterator[BoundSetting[T]]:
        yield BoundSetting(self, group)

    def form(self, group: SettingsGroup) -> Widget:
        from textual.containers import VerticalGroup
        from textual.widgets import Static

        bound = BoundSetting(self, group)
        help_text = self.description()
        title = group._declaration.title if group._declaration else ""
        return VerticalGroup(
            Static(self.title, classes="title"),
            Static(help_text, classes="help"),
            self.widget(bound),
            classes="setting",
            name=f"{title.lower()} {self.title.lower()}",
        )

    def description(self):
        from textual.content import Content

        return Content.assemble(
            Content.from_markup(self.help),
            (f"\ndefault: {self.display(self.default)}", "$text-secondary"),
        )

    def display(self, value: T) -> str:
        return str(value)

    def parse_text(self, text: str) -> T:
        return self.parse(text)


@dataclass(frozen=True)
class PreferenceChange[T]:
    field: SettingKind[T]
    value: T

    def apply(self, app: ToadApp) -> None:
        self.field.effect(app, self.value)


@dataclass(frozen=True)
class BoundSetting[T]:
    kind: SettingKind[T]
    group: SettingsGroup

    @property
    def value(self) -> T:
        return self.kind.__get__(self.group)

    def set(self, value: T) -> None:
        self.kind.__set__(self.group, value)

    @property
    def key(self) -> str:
        return ".".join((*self.group.path, self.kind.wire_name))


class Group[G: "SettingsGroup"](SettingsNode):
    def __init__(self, declaration: type[G], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.declaration = declaration

    @overload
    def __get__(self, group: None, owner: type | None = None) -> Group[G]: ...
    @overload
    def __get__(self, group: SettingsGroup, owner: type | None = None) -> G: ...
    def __get__(self, group, owner=None):
        return self if group is None else group._values[self.name]

    def load(self, group: SettingsGroup, raw: object, present: bool) -> None:
        group._values[self.name] = self.declaration(
            raw if present else {},
            parent=group,
            declaration=self,
        )

    def encode(self, group: SettingsGroup) -> object:
        return self.__get__(group).document()

    def form(self, group: SettingsGroup) -> Widget:
        from textual.containers import VerticalGroup
        from textual.widgets import Static

        return VerticalGroup(
            VerticalGroup(
                Static(self.title, classes="title"),
                Static(self.help, classes="help"),
                classes="heading",
            ),
            VerticalGroup(
                *self.__get__(group).form(), id="setting-group", classes="setting-group"
            ),
            classes="setting-object",
        )

    def leaves(self, group: SettingsGroup) -> Iterator[BoundSetting]:
        yield from self.__get__(group).leaves()


class SettingsGroup:
    def __init__(
        self,
        raw: object = _UNSET,
        *,
        parent: SettingsGroup | None = None,
        declaration: Group | None = None,
        notify: Callable[[PreferenceChange], None] = lambda change: None,
    ) -> None:
        self._parent, self._declaration = parent, declaration
        self._root = parent._root if parent is not None else self
        if parent is None:
            self._notify, self._changed = notify, False
        self._values: dict[str, Any] = {}
        self._present: set[str] = set()
        raw = {} if raw is _UNSET else raw
        if not isinstance(raw, dict):
            raise TypeError("Settings group must be an object")
        nodes = self.nodes()
        unknown = raw.keys() - {node.wire_name for node in nodes}
        if unknown:
            raise ValueError(
                f"Unknown settings in {'.'.join(self.path)}: {sorted(unknown)}"
            )
        for node in nodes:
            present = node.wire_name in raw
            node.load(self, raw.get(node.wire_name), present)
            if present:
                self._present.add(node.name)

    @classmethod
    def nodes(cls) -> tuple[SettingsNode, ...]:
        declarations = {
            name: value
            for base in reversed(cls.__mro__)
            for name, value in vars(base).items()
        }
        return tuple(
            value for value in declarations.values() if isinstance(value, SettingsNode)
        )

    @property
    def path(self) -> tuple[str, ...]:
        return (
            (*self._parent.path, self._declaration.wire_name)
            if self._parent is not None
            else ()
        )

    def _mark_present(self) -> None:
        if self._parent is not None:
            self._parent._present.add(self._declaration.name)
            self._parent._mark_present()

    def document(self) -> dict[str, object]:
        return {
            node.wire_name: node.encode(self)
            for node in self.nodes()
            if node.name in self._present
        }

    @property
    def json(self) -> str:
        return json.dumps(self.document(), indent=4, allow_nan=False)

    @property
    def changed(self) -> bool:
        return self._root._changed

    def up_to_date(self) -> None:
        self._root._changed = False

    def leaves(self) -> Iterator[BoundSetting]:
        for node in self.nodes():
            yield from node.leaves(self)

    def form(self) -> Iterator[Widget]:
        for node in self.nodes():
            if node.editable:
                yield node.form(self)

    def apply_all(self) -> None:
        for bound in self.leaves():
            self._root._notify(PreferenceChange(bound.kind, bound.value))


class BooleanSetting(SettingKind[bool]):
    def toggle(self, group: SettingsGroup) -> None:
        self.__set__(group, not self.__get__(group))

    def parse(self, raw: object) -> bool:
        return FieldCodec.decode(bool, raw)

    def widget(self, bound: BoundSetting[bool]) -> Widget:
        from toad.setting_widgets import BooleanEditor

        return BooleanEditor(bound)


class StringSetting(SettingKind[str]):
    def parse(self, raw: object) -> str:
        return FieldCodec.decode(str, raw)

    def widget(self, bound: BoundSetting[str]) -> Widget:
        from toad.setting_widgets import InputEditor

        return InputEditor(bound)


class TextSetting(StringSetting):
    def description(self):
        from textual.content import Content

        return Content.from_markup(self.help)

    def widget(self, bound: BoundSetting[str]) -> Widget:
        from toad.setting_widgets import TextEditor

        return TextEditor(bound)


class PathSetting(SettingKind[Path]):
    def parse(self, raw: object) -> Path:
        from os.path import expandvars

        return Path(expandvars(FieldCodec.decode(str, raw))).expanduser()

    def encode(self, group: SettingsGroup) -> str:
        return str(self.__get__(group))

    def widget(self, bound: BoundSetting[Path]) -> Widget:
        from toad.setting_widgets import InputEditor

        return InputEditor(bound)


class Bounded:
    def __init__(
        self,
        *,
        minimum: float | None = None,
        maximum: float | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.minimum, self.maximum = minimum, maximum

    def constrain(self, value: T) -> T:
        if self.minimum is not None and value < self.minimum:
            raise ValueError(f"Minimum is {self.minimum}")
        if self.maximum is not None and value > self.maximum:
            raise ValueError(f"Maximum is {self.maximum}")
        return value


class NumericSetting(Bounded, SettingKind[T], ABC):
    def widget(self, bound: BoundSetting[T]) -> Widget:
        from textual.validation import Number

        from toad.setting_widgets import InputEditor

        return InputEditor(
            bound,
            type=self.input_type,
            validators=[Number(minimum=self.minimum, maximum=self.maximum)],
        )


class IntegerSetting(NumericSetting[int]):
    input_type = "integer"

    def parse(self, raw: object) -> int:
        return self.constrain(FieldCodec.decode(int, raw))

    def parse_text(self, text: str) -> int:
        return self.parse(int(text))


class NumberSetting(NumericSetting[float]):
    input_type = "number"

    def parse(self, raw: object) -> float:
        return self.constrain(float(FieldCodec.decode(float | int, raw)))

    def parse_text(self, text: str) -> float:
        return self.parse(float(text))


C = TypeVar("C", bound="Choice")


class ChoiceSetting(SettingKind[type[C]]):
    def __init__(self, family: type[C], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.family = family

    def parse(self, raw: object) -> type[C]:
        return FieldCodec.decode(type[self.family], raw)

    def display(self, value: type[C]) -> str:
        return value.label()

    def widget(self, bound: BoundSetting[type[C]]) -> Widget:
        from toad.setting_widgets import ChoiceEditor

        return ChoiceEditor(bound, self.family)
