"""Stored overrides and views of the keyboard declarations."""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import cache
from importlib import import_module
from pkgutil import walk_packages
from typing import Annotated

import toad

from agent_comms.declared_family import DeclaredFamily
from agent_comms.field_codec import TextRepresentation
from textual.binding import BindingsMap
from textual.document._editing import EditorCommand
from textual.keys import KeyDeclaration
from textual.screen import ModalScreen
from textual.widgets import TextArea

from toad.key_modes import KeyMode
from toad.setting_declarations import Effect, FamilyChoices
from toad.widget_actions import ApplicationAction, DeclaredWidgetActions, YieldingKey


@cache
def discover() -> None:
    """Acquire producer modules once; their own family registries retain membership."""
    DeclaredFamily.discover_package(toad)
    for module in walk_packages(toad.__path__, toad.__name__ + "."):
        if module.ispkg:
            DeclaredFamily.discover_package(import_module(module.name))


class KeyDeclarationName(TextRepresentation[type[KeyDeclaration]]):
    @classmethod
    def from_text(cls, value: str) -> type[KeyDeclaration]:
        discover()
        for declaration in KeyDeclaration.declarations():
            if declaration.identity() == value:
                return declaration
        raise ValueError(f"Unknown keyboard declaration {value!r}")

    @classmethod
    def encode(cls, value: type[KeyDeclaration]) -> str:
        return value.identity()


@dataclass(frozen=True)
class KeymapRow:
    declaration: Annotated[type[KeyDeclaration], KeyDeclarationName]
    mode: type[KeyMode]

    @property
    def binding_id(self) -> str:
        return self.declaration.binding_id(self.mode().binding_mode)

    @property
    def defaults(self) -> tuple[str, ...]:
        return tuple(binding.key for _key, binding in
                     BindingsMap(self.declaration.bindings_for(self.mode().binding_mode)))

    def effective(self, keymap: Keymap) -> tuple[str, ...]:
        return next((remap.keys for remap in keymap.bindings
                     if remap.binding_id == self.binding_id), self.defaults)


@dataclass(frozen=True)
class KeyRemap(KeymapRow):
    keys: tuple[str, ...]


@dataclass(frozen=True)
class KeyConflict:
    first: KeymapRow
    second: KeymapRow
    key: str

    def __str__(self) -> str:
        return (f"{self.key}: {self.first.declaration.title} and "
                f"{self.second.declaration.title} ({FamilyChoices(KeyMode).label(self.first.mode)})")


@Effect
def apply_keymap(app, field) -> None:
    app.set_keymap(app.settings.ui.keymap.native())


@dataclass(frozen=True)
class Keymap:
    bindings: Annotated[tuple[KeyRemap, ...], apply_keymap] = ()

    def __post_init__(self) -> None:
        identities = tuple(remap.binding_id for remap in self.bindings)
        if len(set(identities)) != len(identities):
            raise ValueError("A keyboard declaration may have only one override per mode.")

    def native(self) -> dict[str, str]:
        return {remap.binding_id: ",".join(remap.keys) for remap in self.bindings}

    def changed(self, row: KeymapRow, keys: tuple[str, ...]) -> Keymap:
        if not keys:
            raise ValueError("Enter a key, or use Reset to restore the defaults.")
        bindings = tuple(remap for remap in self.bindings if remap.binding_id != row.binding_id)
        candidate = replace(self, bindings=(*bindings, KeyRemap(row.declaration, row.mode, keys)))
        return self.checked(candidate, row.mode)

    def checked(self, candidate: Keymap, mode: type[KeyMode]) -> Keymap:
        existing = frozenset(self.conflicts(mode))
        introduced = tuple(conflict for conflict in candidate.conflicts(mode)
                           if conflict not in existing)
        if introduced:
            raise ValueError("Key conflict: " + "; ".join(map(str, introduced)))
        return candidate

    def reset(self, row: KeymapRow) -> Keymap:
        return self.checked(replace(self, bindings=tuple(remap for remap in self.bindings
                                                        if remap.binding_id != row.binding_id)), row.mode)

    def conflicts(self, mode: type[KeyMode]) -> tuple[KeyConflict, ...]:
        """Collisions derive from the same class scopes that produce dispatch bindings."""
        discover()
        native_mode = mode().binding_mode
        rows = {row.binding_id: row for declaration in KeyDeclaration.declarations()
                for row in (KeymapRow(declaration, mode),)}
        application = tuple(binding for declaration in ApplicationAction.declarations()
                            if not issubclass(declaration, YieldingKey)
                            for binding in declaration.bindings_for(native_mode))
        conflicts: set[KeyConflict] = set()
        for owner in DeclaredWidgetActions.contexts():
            defaults = owner.declared_bindings(native_mode)
            if issubclass(owner, TextArea):
                defaults = (*defaults, *(binding for declaration in EditorCommand.declarations()
                                         for binding in declaration.bindings_for(native_mode)
                                         if binding.id not in {item.id for item in defaults}))
            if not issubclass(owner, ModalScreen):
                defaults = (*defaults, *application)
            # Inspect before Textual resolves clashes by replacing a conflicting binding.
            claims: dict[str, set[str]] = {}
            for _key, binding in BindingsMap(defaults):
                if binding.id in rows:
                    row = rows[binding.id]
                    for key in row.effective(self):
                        claims.setdefault(key, set()).add(binding.id)
            for key, identities in claims.items():
                claimed = tuple(sorted(identities))
                for index, first in enumerate(claimed):
                    for second in claimed[index + 1:]:
                        pair = sorted((rows[first], rows[second]), key=lambda row: row.binding_id)
                        if (pair[0].declaration.permits_key_overlap(pair[1].declaration)
                                or pair[1].declaration.permits_key_overlap(pair[0].declaration)):
                            continue
                        conflicts.add(KeyConflict(pair[0], pair[1], key))
        return tuple(sorted(conflicts, key=str))
