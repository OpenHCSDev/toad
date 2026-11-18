"""Stored overrides and views of the keyboard declarations."""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import cache, cached_property
from importlib import import_module
from pkgutil import walk_packages
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated

from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.nominal.field_codec import NominalSpelling, NominalText
from objectstate import mark_ui_hidden_config
from textual.binding import BindingsMap
from textual.dom import DOMNode
from formbridge.key_declarations import KeyDeclaration, KeyInvocation
from textual.screen import ModalScreen

import toad
from toad.key_modes import KeyMode
from toad.menus import MenuCommand
from toad.setting_declarations import Effect, FamilyChoices
from toad.client.application_actions import ApplicationAction, KeyFamilyMeta
from toad.widget_actions import DeclaredWidgetActions

if TYPE_CHECKING:
    from formbridge.forms.declared_fields import DeclaredField

    from toad.app import ToadApp


@cache
def discover() -> None:
    """Acquire producer modules once; their own family registries retain membership."""
    DeclaredFamily.discover_package(toad)
    for module in walk_packages(toad.__path__, toad.__name__ + "."):
        if module.ispkg:
            DeclaredFamily.discover_package(import_module(module.name))


class KeymapRefused(ValueError):
    """An invalid keyboard preference the editor may report to its user."""


class KeyInvocationId(NominalText):
    """One concrete command, including its parameters, as its declaration names it now:
    `module.qualname`, with `:`-joined qualified parts for parameterised bindings."""


class KeyInvocationSpelling(NominalSpelling[KeyInvocationId]):
    """A saved keymap entry names its command by the saved name its declaration owns (see
    `KeyFamilyMeta`), not by the module it lives in. Decoding never refuses the settings
    file: an entry no declaration answers keeps its saved text, is not applied, and is
    reported and listed as broken (`Keymap.broken`) — never silently dropped."""

    spelling = re.compile(r".+")

    @classmethod
    def from_text(cls, value: str) -> KeyInvocationId:
        catalog = KeymapCatalog.capture(tuple(KeyMode.members_with(KeyMode)))
        try:
            return catalog.resolve(value)
        except KeymapRefused:
            return KeyInvocationId(value)

    @classmethod
    def encode(cls, value: object) -> str:
        return KeymapCatalog.capture(tuple(KeyMode.members_with(KeyMode))).spelling(
            KeyInvocationId(str(value)))


@dataclass(frozen=True)
class LegacyDeclaration:
    """A declared class as a pre-saved-name keymap spelled it, `module.qualname`, read from
    the class itself: the qualname is its own, so a moved module only shortens the match."""

    identity: KeyInvocationId
    module: tuple[str, ...]
    qualname: str

    def shared_module(self, saved: str) -> int | None:
        """How many trailing module names the saved path shares with this class's module;
        None unless the saved path ends in exactly this class's qualname."""
        head, dot, tail = saved.rpartition("." + self.qualname)
        if tail or not dot:
            return None
        names = tuple(head.split(".")) if head else ()
        shared = 0
        while (shared < min(len(names), len(self.module))
               and names[-1 - shared] == self.module[-1 - shared]):
            shared += 1
        return shared


@dataclass(frozen=True)
class BrokenRemap:
    """A saved keymap entry no declaration answers: kept in the file, never applied."""

    remap: KeyRemap
    reason: str


@dataclass(frozen=True)
class KeymapRow:
    declaration: KeyInvocationId
    mode: type[KeyMode]

    @classmethod
    def of(cls, invocation: KeyInvocation, mode: type[KeyMode]) -> KeymapRow:
        return cls(KeyInvocationId(invocation.key_identity()), mode)

    @cached_property
    def binding_id(self) -> str:
        return KeyInvocation.in_mode(self.declaration, self.mode.binding_mode())


@dataclass(frozen=True)
class ScopedClaim:
    """One default claim in a dispatch scope: the row the keymap edits and its declared keys."""

    row: KeymapRow
    keys: tuple[str, ...]


@dataclass(frozen=True)
class KeyRemap(KeymapRow):
    keys: tuple[str, ...]


@dataclass(frozen=True)
class KeyConflict:
    first: KeymapRow
    second: KeymapRow
    key: str

    def __str__(self) -> str:
        catalog = KeymapCatalog.capture((self.first.mode,))
        return (f"{self.key}: {catalog.require(self.first.declaration).key_title()} and "
                f"{catalog.require(self.second.declaration).key_title()} "
                f"({FamilyChoices(KeyMode).label(self.first.mode)})")


@dataclass(frozen=True)
class KeymapCatalog:
    """A detached view of the same concrete bindings the native scopes dispatch."""

    invocations: Mapping[KeyInvocationId, KeyInvocation]
    scopes: Mapping[type[KeyMode], tuple[tuple[ScopedClaim, ...], ...]]
    default_keys: Mapping[tuple[KeyInvocationId, type[KeyMode]], tuple[str, ...]]
    rows: Mapping[type[KeyMode], Mapping[str, KeymapRow]]

    @classmethod
    def capture(cls, modes: tuple[type[KeyMode], ...]) -> KeymapCatalog:
        """The catalog of the classes declared now. Reading those declarations is a class walk;
        building their bindings is not, so it runs once per distinct set of declarations."""
        discover()
        return cls.of(tuple(modes), DOMNode.descendants(), tuple(ApplicationAction.declarations()))

    @classmethod
    @cache
    def of(
        cls,
        modes: tuple[type[KeyMode], ...],
        contexts: tuple[type[DOMNode], ...],
        actions: tuple[type[ApplicationAction], ...],
    ) -> KeymapCatalog:
        """The modes' catalogs together: each mode is built once, whichever set asks for it (the
        editor shows every mode; a conflict check or its message reads one)."""
        catalogs = tuple(cls.declared(mode, contexts, actions) for mode in modes)
        invocations: dict[KeyInvocationId, KeyInvocation] = {}
        for catalog in catalogs:
            for reference, invocation in catalog.invocations.items():
                invocations.setdefault(reference, invocation)
        return cls(MappingProxyType(invocations), MappingProxyType({
            mode: scopes for catalog in catalogs for mode, scopes in catalog.scopes.items()
        }), MappingProxyType({
            (reference, mode): catalog.default_keys.get((reference, mode), ())
            for reference in invocations for catalog in catalogs for mode in catalog.scopes
        }), MappingProxyType({mode: cls.mode_rows(mode, invocations) for mode in modes}))

    @staticmethod
    def mode_rows(mode: type[KeyMode], invocations: Mapping[KeyInvocationId, KeyInvocation],
                  ) -> Mapping[str, KeymapRow]:
        return MappingProxyType({row.binding_id: row for reference in invocations
                                 for row in (KeymapRow(reference, mode),)})

    @classmethod
    @cache
    def declared(
        cls,
        mode: type[KeyMode],
        contexts: tuple[type[DOMNode], ...],
        actions: tuple[type[ApplicationAction], ...],
    ) -> KeymapCatalog:
        """One mode's catalog, a function of the declarations it is given, so a context or action
        declared later is a different argument and never a stale answer. Families a context's
        keymap_claims reads for itself (Menu reads MenuCommand's members) are settled by
        discover(), which capture runs first and which imports every toad module."""
        native_mode = mode.binding_mode()
        application = tuple(BindingsMap(
            binding for declaration in actions
            for binding in DeclaredWidgetActions.exclusive_bindings(declaration, native_mode)
        ).keymap_claims())
        owned = [application]
        for owner in contexts:
            defaults = owner.keymap_claims(native_mode)
            if not issubclass(owner, ModalScreen):
                defaults = (*defaults, *application)
            owned.append(defaults)
        invocations: dict[KeyInvocationId, KeyInvocation] = {}
        keys: dict[KeyInvocationId, dict[str, None]] = {}
        scoped: list[tuple[ScopedClaim, ...]] = []
        for defaults in owned:
            claims: list[ScopedClaim] = []
            for claim in defaults:
                reference = KeyInvocationId(claim.invocation.key_identity())
                invocations.setdefault(reference, claim.invocation)
                claims.append(ScopedClaim(KeymapRow(reference, mode), claim.keys))
                for key in claim.keys:
                    keys.setdefault(reference, {})[key] = None
            scoped.append(tuple(claims))
        return cls(MappingProxyType(invocations), MappingProxyType({mode: tuple(scoped)}),
                   MappingProxyType({(reference, mode): tuple(keys.get(reference, ()))
                                     for reference in invocations}),
                   MappingProxyType({mode: cls.mode_rows(mode, invocations)}))

    @staticmethod
    def menu_keys(command: MenuCommand, mode: type[KeyMode], keymap: Keymap) -> tuple[str, ...]:
        declaration = type(command)
        return keymap.keys_for(KeymapRow.of(declaration, mode), declaration.default_keys())

    def require(self, reference: KeyInvocationId) -> KeyInvocation:
        try:
            return self.invocations[reference]
        except KeyError:
            raise KeymapRefused(f"Unknown keyboard invocation {reference!r}") from None

    @cached_property
    def saved_names(self) -> Mapping[str, KeyInvocationId]:
        """Each command by the name a keymap saves it under: a toad declaration's registered
        saved name (unique by construction, `KeyFamilyMeta`), any other command's identity."""
        return MappingProxyType({self.spelling(reference): reference
                                 for reference in self.invocations})

    @cached_property
    def legacy(self) -> tuple[LegacyDeclaration, ...]:
        """The declared classes a keymap saved before saved names existed could name, read
        from each class's own module and qualname, never from what happens to be imported."""
        declared = {KeyDeclaration.qualified(cls): cls
                    for cls in (*KeyFamilyMeta.saved_members(), *KeyDeclaration._declared)}
        return tuple(LegacyDeclaration(KeyInvocationId(identity), tuple(cls.__module__.split(".")),
                                       cls.__qualname__)
                     for identity, cls in declared.items() if identity in self.invocations)

    def resolve(self, saved: str) -> KeyInvocationId:
        """The command a saved keymap entry names. A saved name or a current identity answers
        directly. An older file's `module.qualname` of a declaration that has since moved finds
        the declaration with that qualname whose module shares the most trailing names with
        it; a tie or no match refuses by name."""
        if saved in self.invocations:
            return KeyInvocationId(saved)
        if saved in self.saved_names:
            return self.saved_names[saved]
        scored = [(shared, declaration.identity) for declaration in self.legacy
                  for shared in (declaration.shared_module(saved),) if shared is not None]
        if not scored:
            raise KeymapRefused(f"Unknown keyboard invocation {saved!r}")
        best = max(shared for shared, _ in scored)
        chosen = sorted(identity for shared, identity in scored if shared == best)
        if len(chosen) > 1:
            raise KeymapRefused(f"Keyboard invocation {saved!r} could name any of "
                                f"{', '.join(chosen)}")
        return chosen[0]

    def spelling(self, reference: KeyInvocationId) -> str:
        """What a keymap saves for a command: its declaration's saved name; a command toad
        does not declare keeps its identity; an entry no command answers keeps its text."""
        return KeyFamilyMeta.saved_name_of(reference) or str(reference)

    def problem(self, reference: KeyInvocationId) -> str | None:
        """Why a saved entry is not applied, or None when a command answers it."""
        if reference in self.invocations:
            return None
        try:
            self.resolve(reference)
        except KeymapRefused as refusal:
            return str(refusal)
        return None

    def defaults(self, row: KeymapRow) -> tuple[str, ...]:
        return self.default_keys[row.declaration, row.mode]

    def effective(self, row: KeymapRow, keymap: Keymap) -> tuple[str, ...]:
        return keymap.keys_for(row, self.defaults(row))


@Effect
def apply_keymap(app: ToadApp, field: DeclaredField) -> None:
    app.follow_keymap()


def report_broken_keymap(app: ToadApp) -> None:
    """Tell the user which saved shortcuts are not applied. Settings apply on Load, before a
    screen can show a notice, so the app calls this once it is mounted; the keymap screen
    lists the same entries for as long as they stay in the file."""
    if broken := app.settings.ui.keymap.broken:
        app.show_error("Not applied (listed in the keymap screen): " + "; ".join(
            f"{entry.remap.declaration} in {FamilyChoices(KeyMode).label(entry.remap.mode)}: "
            f"{entry.reason}" for entry in broken), "Keyboard shortcuts")


@mark_ui_hidden_config
@dataclass(frozen=True)
class Keymap:
    bindings: Annotated[tuple[KeyRemap, ...], apply_keymap] = ()

    def __post_init__(self) -> None:
        if len(self.overrides) != len(self.bindings):
            raise KeymapRefused("A keyboard declaration may have only one override per mode.")

    @cached_property
    def overrides(self) -> Mapping[str, tuple[str, ...]]:
        """Each remap's keys by its binding id: every lookup reads this one map."""
        return MappingProxyType({remap.binding_id: remap.keys for remap in self.bindings})

    @cached_property
    def broken(self) -> tuple[BrokenRemap, ...]:
        """Saved entries no declared command answers: kept, reported, never applied."""
        catalog = KeymapCatalog.capture(tuple(KeyMode.members_with(KeyMode)))
        return tuple(BrokenRemap(remap, reason) for remap in self.bindings
                     for reason in (catalog.problem(remap.declaration),) if reason is not None)

    def native(self) -> dict[str, str]:
        """The overrides to apply: every entry a declared command answers."""
        broken = {entry.remap.binding_id for entry in self.broken}
        return {binding_id: ",".join(keys) for binding_id, keys in self.overrides.items()
                if binding_id not in broken}

    def keys_for(self, row: KeymapRow, defaults: tuple[str, ...]) -> tuple[str, ...]:
        """The preference alone selects an override; its caller owns the default scope."""
        return self.overrides.get(row.binding_id, defaults)

    def changed(self, row: KeymapRow, keys: tuple[str, ...]) -> Keymap:
        """No keys is an explicit unbinding, kept as its own override; Reset restores the defaults."""
        bindings = tuple(remap for remap in self.bindings if remap.binding_id != row.binding_id)
        candidate = replace(self, bindings=(*bindings, KeyRemap(row.declaration, row.mode, keys)))
        return self.checked(candidate, row.mode)

    def checked(self, candidate: Keymap, mode: type[KeyMode]) -> Keymap:
        existing = frozenset(self.conflicts(mode))
        introduced = tuple(conflict for conflict in candidate.conflicts(mode)
                           if conflict not in existing)
        if introduced:
            raise KeymapRefused("Key conflict: " + "; ".join(map(str, introduced)))
        return candidate

    def reset(self, row: KeymapRow) -> Keymap:
        return self.checked(replace(self, bindings=tuple(remap for remap in self.bindings
                                                        if remap.binding_id != row.binding_id)), row.mode)

    def conflicts(self, mode: type[KeyMode]) -> tuple[KeyConflict, ...]:
        """Collisions derive from concrete invocations in the native dispatch scopes."""
        catalog = KeymapCatalog.capture((mode,))
        rows = catalog.rows[mode]
        conflicts: set[KeyConflict] = set()
        for defaults in catalog.scopes[mode]:
            # A scope is ordered: the declared defaults set precedence, and dispatch runs the
            # first claim on a key and shadows the rest (the prompt's CopyOrClearInputAction over
            # TextArea.action_copy, TextArea's own end over navigation's ScrollEnd). Two declared
            # claims on one key are that precedence, never a collision. A collision is a key a
            # remap moved onto a row that another claim in the scope also holds.
            claims: dict[str, dict[str, bool]] = {}
            for claim in defaults:
                row = claim.row
                for key in self.keys_for(row, claim.keys):
                    held = claims.setdefault(key, {})
                    held[row.binding_id] = held.get(row.binding_id, False) or key not in claim.keys
            for key, held in claims.items():
                claimed = tuple(sorted(held))
                for index, first in enumerate(claimed):
                    for second in claimed[index + 1:]:
                        if not (held[first] or held[second]):
                            continue
                        pair = sorted((rows[first], rows[second]), key=lambda row: row.binding_id)
                        first_invocation = catalog.require(pair[0].declaration)
                        second_invocation = catalog.require(pair[1].declaration)
                        if (first_invocation.permits_invocation_overlap(second_invocation)
                                or second_invocation.permits_invocation_overlap(first_invocation)):
                            continue
                        conflicts.add(KeyConflict(pair[0], pair[1], key))
        return tuple(sorted(conflicts, key=str))
