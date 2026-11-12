"""Searchable, recently-used-first model picker for ACP sessions."""

from __future__ import annotations
from formbridge.forms.declared_fields import DeclaredField
from objectstate import ObjectState
from textual.css.scalar import Scalar
from toad.core import input_events

from typing import Self

from textual import events, on
from textual.app import ComposeResult
from textual.widgets import Select

from toad.acp.agent_configuration import (
    AdvertisedChoices,
    AdvertisedSetting,
    ConfigurationSetting,
    ModelConfigurationSetting,
)
from toad.core_event_carrier import CoreEventReceiver
from toad.forms.editors import ValueEditor
from toad.forms.form_view import InlineFormView
from toad.widgets.model_selection import ConnectProvider, ModelSelection
from toad.widgets.prompt_popup import InfoPopup

from toad.native_style import ScreenOverlay

class SessionModelEditor(ValueEditor, ModelSelection, shows=(ModelConfigurationSetting,)):
    """The ordinary form owns the value; model search is its specialized editor."""

    @property
    def history_scope(self) -> str:
        return self.query_ancestor(ModelSwitcher).prompt.model_history_scope

    def bind_control(self) -> None:
        pass

    def compose(self) -> ComposeResult:
        yield from self.compose_content()

    @property
    def choices(self):
        return self.field.metadata(AdvertisedChoices).setting.choices

    @property
    def current(self):
        return self.field.value

    @property
    def selection_active(self):
        return self.is_attached

    def select_model(self, model_id: str) -> None:
        self.send(model_id)

    def paint(self) -> None:
        self.configuration_changed()

    def connect_provider(self) -> None:
        self.publish_core(input_events.ProviderLogin())

    def dismiss_control(self) -> None:
        self.query_ancestor(ModelSwitcher).dismiss_control()


class SessionForm(CoreEventReceiver, InlineFormView):
    def values_changed(self, paths: set[str]) -> None:
        super().values_changed(paths)
        for path in paths & self.values.keys():
            field = self.values[path].field
            setting = field.metadata(AdvertisedSetting).setting
            if field.value != setting.current:
                self.publish_core(setting.selection_event(field.value))


class ModelSwitcher(ScreenOverlay, InfoPopup):
    """Every advertised session field, edited through the shared form machinery."""

    height = Scalar.from_number(24)
    width = Scalar.from_number(84)
    overflow_y = "auto"

    def compose_content(self) -> ComposeResult:
        self.form = SessionForm.whole(self.prompt.agent_binding.configuration.editing())
        yield self.form

    def configuration_changed(self) -> None:
        if self.is_mounted and self._content_build is not None:
            self.run_worker(self.recompose(), exclusive=True, group="session-form")

    def focus_content(self, scroll_visible: bool) -> None:
        editor = next(iter(self.form.values.values()), None)
        if editor is not None:
            editor.editor.focus()
            for model in self.query(SessionModelEditor):
                model.focus_content(False)

    @classmethod
    def for_prompt(cls, prompt: object) -> Self | None:
        return cls()

