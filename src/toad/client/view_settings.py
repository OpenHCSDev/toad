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

from toad.client.sidebar_panels import PanelSpec

if TYPE_CHECKING:
    from toad.client.tab_identity import TabIdentity
    from toad.object_configuration import ObjectConfiguration, ObjectSettingField
    from toad.preferences import SavedSettings


class ViewSettingsOwner:
    """A file, thread or channel owns its display overrides.

    A plain parent, as `SessionScope` is: ABCMeta would conflict with each toolkit's widget
    metaclass. The frontend names the view's tab identity and its app's saved settings;
    this owns the configuration opened over them and the fields the settings pane lists.
    A changed override reaches the view's open widgets through its `settings_widgets`
    (each `Effect` asks for them by capability)."""

    @property
    @abstractmethod
    def configuration_identity(self) -> TabIdentity:
        """The tab this view's overrides are saved under."""

    @property
    @abstractmethod
    def configuration_settings(self) -> SavedSettings:
        """The app-wide settings this view's overrides inherit from."""

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
