"""Searchable, recently-used-first model picker for ACP sessions."""

from __future__ import annotations

from typing import Self

from textual import events, work
from textual.app import ComposeResult
from textual.css.scalar import Scalar

from toad.acp.agent_configuration import (
    AdvertisedChoices,
    AdvertisedSetting,
    ModelConfigurationSetting,
)
from toad.core import input_events
from toad.core_event_carrier import CoreEventReceiver
from toad.forms.editors import ValueEditor
from toad.forms.form_view import InlineFormView
from toad.native_style import ScreenOverlay
from toad.widgets.model_selection import (
    ModelSelection,
    SelectionBounds,
)
from toad.widgets.prompt_popup import InfoPopup


class SessionModelEditor(ValueEditor, ModelSelection, shows=(ModelConfigurationSetting,)):
    """The ordinary form owns the value; model search is its specialized editor."""

    @property
    def history_scope(self) -> str:
        return self.query_ancestor(SessionForm).prompt.model_history_scope

    def bind_control(self) -> None:
        self.listen(events.Mount, self.opened)

    def opened(self, event: events.Mount) -> None:
        self.focus_content(False)

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
        self.query_ancestor(SessionForm).prompt.publish_core(input_events.ProviderLogin())

    def dismiss_control(self) -> None:
        self.query_ancestor(SessionForm).dismiss_control()


class SessionForm(CoreEventReceiver, InlineFormView):

    def __init__(self, state, parts, prompt):
        super().__init__(state, parts)
        self.prompt = prompt

    @classmethod
    def for_prompt(cls, prompt):
        state = prompt.agent_binding.configuration.editing()
        return cls(state, cls.field_family.of(state), prompt)

    def dismiss_control(self):
        """An inline selection leaves its form open."""

    def represents(self, settings) -> bool:
        return tuple(row.field.metadata(AdvertisedSetting).setting
                     for row in self.values.values()) == settings.picker_settings

    def values_changed(self, paths: set[str]) -> None:
        super().values_changed(paths)
        for path in paths & self.values.keys():
            field = self.values[path].field
            setting = field.metadata(AdvertisedSetting).setting
            if field.value != setting.current:
                self.prompt.publish_core(setting.selection_event(field.value))


class PopupSessionForm(SessionForm):
    """The popup adds dismissal to the same advertised settings form."""

    def dismiss_control(self):
        self.query_ancestor(ModelSwitcher).dismiss_control()


class ModelSwitcher(SelectionBounds, ScreenOverlay, InfoPopup):
    """Every advertised session field, edited through the shared form machinery."""

    height = Scalar.from_number(24)
    width = Scalar.from_number(84)
    overflow_y = "auto"

    def compose_content(self) -> ComposeResult:
        self.form = PopupSessionForm.for_prompt(self.prompt)
        yield self.form

    def configuration_changed(self) -> None:
        if self.is_mounted and self.is_open:
            self.rebuild_form()

    @work(exclusive=True, group="session-form")
    async def rebuild_form(self) -> None:
        await self.recompose()
        if self.is_open:
            self.focus_content(False)

    def focus_content(self, scroll_visible: bool) -> None:
        if not self.form.represents(self.prompt.agent_binding.configuration):
            self.rebuild_form()
            return
        editor = next(iter(self.form.values.values()), None)
        if editor is not None:
            editor.editor.focus()
            for model in self.query(SessionModelEditor):
                model.focus_content(False)

    @classmethod
    def for_prompt(cls, prompt: object) -> Self | None:
        return cls()
