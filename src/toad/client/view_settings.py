"""A viewed object's own settings, owned once for both frontends.

Textual's `ViewSettingsScope` / `ConversationSettingsScope` and Qt's conversation and thread
views inherit these owners. A setting declaration names the owner kinds that may override it
(`SettingsDeclaration(scopes=...)`), so the same fields are overridable on a Qt view as on its
Textual sibling, and the view's settings pane lists the same fields on both: every top-level
parameter of the view's `ObjectConfiguration`, in declaration order.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterator
from functools import cached_property
from typing import TYPE_CHECKING

from formbridge.forms.parameter_form_service import ParameterFormService

from toad.client.menu_entry import MenuEntry
from toad.client.sidebar_panels import PanelSpec
from toad.client.tab_identity import TabIdentity
from toad.command_catalog import CommandCatalog

if TYPE_CHECKING:
    from toad.object_configuration import ObjectConfiguration, ObjectSettingField
    from toad.preferences import SavedSettings


class SettingsReading:
    """Something that reads the settings of the view it sits in: that view's overrides, else
    the app's. A frontend says which scope that is: Textual finds it among the widget's
    ancestors (`SettingsReader`), a Qt widget is handed it when it is built."""

    configuration_scope: ViewSettingsOwner

    @property
    def configuration_state(self):
        return self.configuration_scope.configuration_state

    @property
    def settings(self):
        return self.configuration_state.fields


class ViewSettingsOwner:
    """A file, thread or channel owns its display overrides.

    A plain parent, as `SessionScope` is: ABCMeta would conflict with each toolkit's widget
    metaclass. The frontend names the view's tab identity and its app's saved settings;
    this owns the configuration opened over them and the fields the settings pane lists.
    A changed override reaches the view's open widgets through its `settings_widgets`
    (each `Effect` asks for them by capability)."""

    @property
    @abstractmethod
    def configuration_mode(self) -> str:
        """The session-navigation mode this view's overrides are stored under."""

    @property
    def configuration_identity(self) -> TabIdentity:
        """The tab this view's overrides are saved under."""
        return self.app.session_navigation.get(self.configuration_mode).identity

    @property
    def configuration_settings(self) -> SavedSettings:
        """The app-wide settings this view's overrides inherit from."""
        return self.app.saved_settings

    @cached_property
    def configuration_state(self) -> ObjectConfiguration:
        from toad.object_configuration import ObjectConfiguration
        settings = self.configuration_settings
        return ObjectConfiguration(self.configuration_identity, settings,
                                   settings.path().parent, self)

    def configuration_fields(self) -> Iterator[ObjectSettingField]:
        """Each top-level setting the view's settings pane shows, as a field of this view's
        configuration: its value, override and reset all go through the view."""
        state = self.configuration_state
        for path, _parameter in ParameterFormService().parameters_for_state(state):
            yield state.field(path.value)

    def configuration_actions(self) -> tuple:
        """The backend operations that configure this view's subject (a thread's model,
        thinking level, service tier for its next turn), as (context, action, fields).
        Reads Core: run it off the UI loop."""
        entries = []
        for context in self.navigation_target.configuration_contexts(self):
            for action in context.available_actions():
                for configuration in action.declaration.configuration_actions(action):
                    entries.append((context, configuration, configuration.editable_fields))
        return tuple(entries)

    async def view_menu_entries(self) -> tuple[MenuEntry, ...]:
        """The right-click options for this view (thread, channel, or file), read from the
        same declared menu owners (`CommandCatalog.pointer_menu` and `tab_menu`) so the view
        settings bar stays one declaration with right-click."""
        contexts = await self.app.preparation.run_thread(
            self.navigation_target.configuration_contexts, self
        )
        entries: list[MenuEntry] = []
        for context in contexts:
            entries.extend(await CommandCatalog.pointer_menu(context))
        if not entries and self.configuration_mode:
            entries.extend(self.app.session_navigation.tab_menu(self.configuration_mode))
        return tuple(entries)

    @staticmethod
    def configuration_action_panel(action) -> PanelSpec:
        """The settings pane entry a configuration action is listed under."""
        return PanelSpec(title=action.label, flex=True)

    @staticmethod
    def field_panel(field: ObjectSettingField) -> PanelSpec:
        """The settings pane entry a field is listed under."""
        return PanelSpec(title=field.label, flex=True, id=f"settings-{field.path.value}")

    def close_configuration(self) -> None:
        """Release the configuration when the view retires; one never opened (the view was
        never asked for its settings) has nothing to release."""
        if "configuration_state" in vars(self):
            self.configuration_state.close()


class ConversationSettingsOwner(ViewSettingsOwner):
    """A thread or channel additionally owns conversation and composer settings."""
