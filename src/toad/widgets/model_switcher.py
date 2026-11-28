"""Searchable, recently-used-first model picker for ACP sessions."""

from __future__ import annotations


from textual import containers, events, on, work
from textual.app import ComposeResult
from textual.css.scalar import Scalar
from textual.view import FILL
from textual.widgets import Button

from toad.acp.agent_configuration import (
    AdvertisedChoices,
    AdvertisedSetting,
    ModelConfigurationSetting,
)
from toad.client.model_selection import SessionChoiceSelection
from toad.core import input_events
from toad.core_event_carrier import CoreEventReceiver
from toad.forms.editors import ValueEditor
from toad.forms.form_view import InlineFormView
from toad.native_style import (
    AutoHeight,
    AutoWidth,
    DockedBottom,
    HiddenOverflow,
    ScreenOverlay,
    SideMargin,
    StableGutter,
)
from toad.widgets.acting_button import DismissButton
from toad.widgets.model_selection import (
    ModelSelection,
    SelectionBounds,
)
from toad.widgets.prompt_popup import AlwaysOpenPromptPopup, InfoPopup


class SessionModelEditor(
    ValueEditor,
    SessionChoiceSelection,
    ModelSelection,
    shows=(ModelConfigurationSetting,),
):
    """The ordinary form owns the value; model search is its specialized editor."""

    @property
    def history_scope(self) -> str:
        return self.query_ancestor(SessionForm).prompt.model_history_scope

    def bind_control(self) -> None:
        self.listen(events.Mount, self.opened)

    def opened(self, event: events.Mount) -> None:
        self.query_ancestor(SessionForm).open_model(self)

    def compose(self) -> ComposeResult:
        yield from self.compose_content()

    def model_setting(self) -> ModelConfigurationSetting:
        return self.field.metadata(AdvertisedChoices).setting

    @property
    def current(self):
        return self.field.value

    def select_model(self, model_id: str) -> None:
        self.send(model_id)

    def paint(self) -> None:
        self.configuration_changed()

    def connect_provider(self) -> None:
        self.query_ancestor(SessionForm).publish_core(input_events.ProviderLogin())

    def dismiss_control(self) -> None:
        self.query_ancestor(SessionForm).dismiss_control()


class SessionForm(CoreEventReceiver, InlineFormView):

    def __init__(self, state, parts, prompt):
        super().__init__(state, parts)
        self.prompt = prompt

    @classmethod
    def settings(cls, configuration):
        return configuration.picker_settings

    @classmethod
    def for_prompt(cls, prompt):
        configuration = prompt.agent_binding.configuration
        state = configuration.editing_settings(cls.settings(configuration))
        return cls(state, cls.field_family.of(state), prompt)

    def open_model(self, editor):
        """An inline form paints its model choices without taking keyboard focus."""
        editor.configuration_changed()

    def dismiss_control(self):
        """An inline selection leaves its form open."""

    def represents(self, settings) -> bool:
        return tuple(row.field.metadata(AdvertisedSetting).setting
                     for row in self.values.values()) == self.settings(settings)

    def values_changed(self, paths: set[str]) -> None:
        super().values_changed(paths)
        for path in paths & self.values.keys():
            field = self.values[path].field
            setting = field.metadata(AdvertisedSetting).setting
            if field.value != setting.current:
                self.publish_core(setting.selection_event(field.value))


class PopupSessionForm(StableGutter, SessionForm):
    """The bounded popup scrolls its live advertised settings above its controls."""

    height = FILL

    def open_model(self, editor):
        if self.query_ancestor(ModelSwitcher).is_open:
            editor.focus_content(False)

    def dismiss_control(self):
        self.query_ancestor(ModelSwitcher).dismiss_control()

    @on(events.DescendantFocus)
    def reveal_focused_setting(self, event: events.DescendantFocus) -> None:
        self.scroll_to_widget(event.widget, animate=False, immediate=True)


class SessionSettingsButtons(DockedBottom, AutoHeight, containers.Horizontal):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.height = 3
        self.styles.align_horizontal = "center"


class SessionSettingsButton(AutoWidth, SideMargin, Button):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.min_width = 12


class FinishSessionSettings(DismissButton, SessionSettingsButton):
    """Close the panel after its live settings have been chosen."""


class ModelSwitcher(
    AlwaysOpenPromptPopup,
    SelectionBounds,
    HiddenOverflow,
    ScreenOverlay,
    InfoPopup,
):
    """Every advertised session field, edited through the shared form machinery."""

    height = Scalar.from_number(24)
    width = Scalar.from_number(84)

    def compose_content(self) -> ComposeResult:
        self.form = PopupSessionForm.for_prompt(self.prompt)
        yield self.form
        with SessionSettingsButtons():
            yield FinishSessionSettings("Done", variant="primary")

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
