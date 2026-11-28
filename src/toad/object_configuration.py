"""A viewed object's overrides, with ObjectState owning inheritance and its source."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from agent_comms.nominal.field_codec import FieldCodec
from formbridge.forms.declared_fields import DeclaredField
from objectstate import ObjectState, ObjectStateRegistry, ScopeKey
from objectstate.lazy_factory import LazyDataclassFactory
from pydantic import JsonValue

from toad import atomic
from toad.client.tab_identity import TabIdentity
from toad.client.view_settings import ViewSettingsOwner
from toad.preferences import SavedSettings
from toad.setting_declarations import Effect, SettingsDeclaration


@dataclass(frozen=True)
class ObjectSettingsDocument:
    identity: TabIdentity
    values: dict[str, JsonValue]


class ObjectSettingField(DeclaredField):
    """The original concrete declaration, over a lazy field's actual state."""

    @property
    def declaration(self):
        return self.state.defaults.parameter_structure.declarations[self.path.value]

    @property
    def owner_type(self):
        return DeclaredField(self.state.defaults, self.path).owner_type

    @property
    def allows_override(self) -> bool:
        return self.state.admits(self.path.value)

    @property
    def overridden(self) -> bool:
        return self.allows_override and self.state.parameters[self.path.value] is not None

    @property
    def source_text(self) -> str:
        if self.overridden:
            return "Override for this object"
        return "Inherited from global defaults" if self.allows_override else "Global setting · applies to every view"

    @property
    def source_detail(self) -> str:
        scope, owner = self.state.get_provenance(self.path.value)
        return f"{owner.__module__}.{owner.__qualname__} · {scope or 'global'}"

    def reset(self) -> None:
        """The writer resets its actual parameter to that parameter's signature default."""
        state = self.state if self.allows_override else self.state.defaults
        state.reset_parameter(self.path.value)
        if state is self.state.defaults:
            self.state.global_settings.save_sync()

    def edit(self, value):
        if self.allows_override:
            return super().edit(value)
        result = DeclaredField(self.state.defaults, self.path).edit(value)
        self.state.global_settings.save_sync()
        return result


class ObjectConfiguration(ObjectState):
    """One view's explicit values; unassigned fields follow its live defaults."""

    def __init__(self, identity: TabIdentity, global_settings: SavedSettings,
                 directory: Path, owner: ViewSettingsOwner) -> None:
        self.global_settings = global_settings
        defaults = global_settings.state
        self.identity, self.defaults, self.owner = identity, defaults, owner
        self.path = directory / "objects" / f"{identity.mode_name}.json"
        scope = str(ScopeKey.of("view", identity.mode_name))
        if ObjectStateRegistry.get_by_scope(scope) is not None:
            raise ValueError(f"Settings already open for {identity}")
        super().__init__(self.lazy_settings_type(global_settings)(), scope_id=scope, parent_state=defaults)
        if self.path.exists():
            document = FieldCodec.decode(ObjectSettingsDocument, FieldCodec.parse(self.path.read_text("utf-8")))
            if document.identity != identity:
                raise ValueError(f"Settings identity does not match {self.path}")
            for path, encoded in document.values.items():
                if path not in self.editable_paths:
                    raise ValueError(f"{path} cannot be overridden for {identity}")
                field = self.field(path)
                field.edit(FieldCodec.decode(field.annotation, encoded))
        self.mark_saved()
        ObjectStateRegistry.register(self)
        self.on_resolved_changed(self.apply_changes)
        self.on_state_changed(self.save_changes)

    @staticmethod
    def lazy_settings_type(global_settings: SavedSettings) -> type:
        """The settings tree as a view holds it, every field following the app's settings
        until the view sets it: made once per settings class."""
        return LazyDataclassFactory.make_lazy_simple(type(global_settings.state.object_instance))

    @classmethod
    def prepare_settings_type(cls, global_settings: SavedSettings) -> None:
        """Set up, once, what every view's configuration is built from: its lazy settings
        class, each nested one, and their annotations, which the first instance validates
        against. That is class setup (190 ms on a phone's speed), and unprepared it was
        paid by the first view the reader opened."""
        cls.lazy_settings_type(global_settings)()

    def field(self, path: str) -> ObjectSettingField:
        return ObjectSettingField(self, self.parameter_structure.path(path))

    @cached_property
    def editable_paths(self) -> frozenset[str]:
        return frozenset(path.value for path in self.parameter_structure.leaf_paths()
                         if self.admits(path.value))

    def admits(self, path: str) -> bool:
        field = self.field(path)
        owner = field.owner_type
        return (issubclass(owner, SettingsDeclaration)
                and owner.admits_field(field.path.field_name, self.owner))

    def update_parameter(self, param_name: str, value: object) -> set[str]:
        if param_name not in self.editable_paths:
            raise ValueError(f"{param_name} cannot be overridden for {self.identity}")
        return super().update_parameter(param_name, value)

    def apply_changes(self, paths: set[str]) -> None:
        for path in paths & self.editable_paths:
            field = self.field(path)
            if (effect := field.metadata(Effect)) is not None:
                effect.apply(self.owner, field)

    def save_changes(self, paths: set[str]) -> None:
        if not paths:
            return
        values = {path: FieldCodec.encode(value, self.field(path).annotation)
                  for path, value in self.get_current_values().items()
                  if path in self.editable_paths and value is not None}
        text = json.dumps(FieldCodec.encode(ObjectSettingsDocument(self.identity, values)), indent=2, allow_nan=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic.write(str(self.path), text)
        self.mark_saved()

    def close(self) -> None:
        self.off_resolved_changed(self.apply_changes)
        self.off_state_changed(self.save_changes)
        ObjectStateRegistry.unregister(self)
