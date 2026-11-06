"""Searchable, recently-used-first model picker for ACP sessions."""

from __future__ import annotations
from toad.core import input_events
from toad.core_event_carrier import CoreEventReceiver

from abc import abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Self, Protocol

from textual import getters, on, work
from textual.app import ComposeResult
from textual.document._editing import EditingMode
from toad.widget_actions import ForwardsCursor, WidgetAction, PriorityActions, Submits, DismissibleControl
from textual.content import Content
from textual.containers import VerticalGroup
from textual.css.native import Keyword, NativeDeclaration, Variable
from textual.css.styles import Styles
from textual.reactive import var
from textual.widgets import Input, OptionList, Select, Static
from toad.widget_actions import Activates
from textual.widgets.option_list import Option, OptionListComponent

from toad.acp.agent_configuration import ConfigurationSetting, ModelConfigurationSetting
from toad.widgets.selection import SelectionOptionList, InlineSelection
from toad.widgets.prompt_popup import InfoPopup, PaddedOptionRows
from ui_theme.scheme import (
    BackgroundColour,
    BlockCursorBackgroundColour,
    BlockCursorForegroundColour,
    BlockCursorTextStyle,
    PrimaryColour,
)

from toad.native_style import (
    AutoHeight,
    Borderless,
    MutedText,
    NoPadding,
    OneRow,
    PointerCursor,
    ScreenOverlay,
    SecondaryText,
    SidePadding,
    SpacedAround,
)

if TYPE_CHECKING:
    from toad.widgets.prompt import Prompt


class ConnectProvider(
    InlineSelection,
    Activates,
    CoreEventReceiver,
    SecondaryText,
    OneRow,
    SidePadding,
    PointerCursor,
    Static,
    can_focus=True,
):


    def __init__(self):
        super().__init__("Connect a provider…", markup=False)


    def activate(self):
        self.query_ancestor(ModelSelection).connect_provider()

def match_score(query: str, candidate: str) -> float:
    """Linear subsequence matching, with exact/prefix/substring preference."""
    if query == candidate:
        return 100
    if candidate.startswith(query):
        return 80
    if query in candidate:
        return 60
    previous = -1
    first = -1
    for character in query:
        previous = candidate.find(character, previous + 1)
        if previous == -1:
            return 0
        if first == -1:
            first = previous
    return 10 + len(query) / max(1, previous - first + 1)


class ModelChoice(Protocol):
    @property
    def value(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str | None: ...


class ClearModelSearchAction(WidgetAction):
    """Clear the model search query."""
    keys = {EditingMode: ("ctrl+u",)}
    priority = True

    async def apply(self, context: ModelSelection) -> None:
        context.search_input.clear()


class ModelCount(MutedText, OneRow, SidePadding, Static):

    """Its look is its bases."""


class ModelOptionList(Borderless, AutoHeight, NoPadding, PaddedOptionRows, SelectionOptionList):
    native_components = {
        OptionListComponent.OPTION_HIGHLIGHTED: (
            NativeDeclaration.of(Styles.background, Variable(BlockCursorBackgroundColour.name)),
            NativeDeclaration.of(Styles.color, Variable(BlockCursorForegroundColour.name)),
            NativeDeclaration.of(Styles.text_style, Variable(BlockCursorTextStyle.name)),
        ),
    }

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.max_height = "45vh"


class HighlightPlacement:
    """Where a refilter puts the highlight."""

    @abstractmethod
    def index(self, ids: list[str | None], previous_id: str | None) -> int: ...


class ResetsHighlight(HighlightPlacement):
    """Nothing touched since the picker opened: the best match, first in the list."""

    def index(self, ids: list[str | None], previous_id: str | None) -> int:
        return 0


class KeepsHighlight(HighlightPlacement):
    """The user moved or typed: stay on their option while the filter still lists it."""

    def index(self, ids: list[str | None], previous_id: str | None) -> int:
        return ids.index(previous_id) if previous_id in ids else 0


class ModelSelection(
    SpacedAround,
    PriorityActions,
    ForwardsCursor,
    Submits,
    DismissibleControl,
    CoreEventReceiver,
    AutoHeight,
    NoPadding,
    VerticalGroup,
    actions=(ClearModelSearchAction,),
    scopes={PriorityActions: (ClearModelSearchAction,)},
):
    """Search, recents and provider connection shared by prompt and creation views."""
    BINDING_GROUP_TITLE = "Model search"
    native_theme = (
        NativeDeclaration.of(Styles.border, Keyword("round"), Variable(PrimaryColour.name)),
        NativeDeclaration.of(Styles.background, Variable(BackgroundColour.name)),
    )

    search_input = getters.query_one(Input)
    option_list = getters.query_one(SelectionOptionList)
    history_scope = var("")
    choice_name = "models"

    def __init__(self):
        super().__init__()
        self.recent_ids: list[str] = []
        self._open_generation = 0
        self.refilter: HighlightPlacement = ResetsHighlight()

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.constrain_x = "inside"
        self.styles.constrain_y = "inflect"
        self.styles.width = 80
        self.styles.max_width = "100%"
        self.styles.max_height = "80vh"

    @property
    @abstractmethod
    def choices(self) -> Sequence[ModelChoice]: ...

    @property
    @abstractmethod
    def current(self) -> str: ...

    @property
    @abstractmethod
    def selection_active(self) -> bool: ...

    @abstractmethod
    def select_model(self, model_id: str) -> None: ...

    @abstractmethod
    def connect_provider(self) -> None: ...

    def compose_content(self) -> ComposeResult:
        yield Input(placeholder=f"Search {self.choice_name} or providers…", compact=True)
        yield ModelCount("", markup=False)
        options = ModelOptionList()
        options.can_focus = False
        yield options
        yield ConnectProvider()

    def configuration_changed(self) -> None:
        if self.is_mounted and self.selection_active:
            self.filter_models(KeepsHighlight())

    def focus_content(self, scroll_visible: bool) -> None:
        self._open_generation += 1
        self.refilter = ResetsHighlight()
        self.recent_ids = []
        with self.search_input.prevent(Input.Changed):
            self.search_input.value = ""
        self.filter_models(self.refilter)
        self.search_input.focus(scroll_visible=False)
        self.load_recents(self._open_generation, self.history_scope)

    async def recent_choices(self, scope: str) -> list[str]:
        return await ModelConfigurationSetting().recent_choices(scope)

    @work(exclusive=True)
    async def load_recents(self, generation: int, scope: str) -> None:
        recent = await self.recent_choices(scope)
        if (
            self.selection_active
            and generation == self._open_generation
            and scope == self.history_scope
        ):
            self.recent_ids = recent
            self.filter_models(self.refilter)

    def filter_models(self, placement: HighlightPlacement) -> None:
        highlighted = self.option_list.highlighted_option
        previous_id = highlighted.id if highlighted is not None else None
        terms = self.search_input.value.casefold().split()
        recent = {model_id: index for index, model_id in enumerate(self.recent_ids)}
        models, current = self.choices, self.current
        ranked = []
        for model in models:
            fields = {model.name.casefold(), model.value.casefold()}
            scores = [
                max(
                    *(match_score(term, field) for field in fields),
                    match_score(term, (model.description or "").casefold()) * 0.5,
                )
                for term in terms
            ]
            if scores and not all(scores):
                continue
            rank = recent.get(
                model.value, len(recent) + (model.value != current)
            )
            ranked.append((-sum(scores), rank, model.name.casefold(), model.value, model))
        ranked.sort(key=lambda item: item[:4])
        options = []
        for *_, model in ranked:
            label = Content.assemble(
                ("✓ " if model.value == current else "  ", "$text-success"),
                (model.name, "bold"),
                (" · recent" if model.value in recent else "", "dim"),
            )
            if model.value != model.name:
                label += Content.styled(f" · {model.value}", "dim")
            options.append(Option(label, id=model.value))
        # Only the user moves the highlight with an OptionHighlighted; see on_option_highlighted.
        with self.option_list.prevent(OptionList.OptionHighlighted):
            self.option_list.set_options(options)
            if options:
                self.option_list.highlighted = placement.index(
                    [option.id for option in options], previous_id
                )
            else:
                self.option_list.highlighted = None
        self.query_one(ModelCount).update(
            f"{len(options)} / {len(models)} {self.choice_name} · {'best matches' if terms else 'recent first' if recent else 'current first'}"
            if options
            else f"No matching {self.choice_name}"
        )

    @on(Input.Changed)
    def on_search_changed(self, event: Input.Changed):
        event.stop()
        self.filter_models(ResetsHighlight())
        self.refilter = KeepsHighlight()

    @on(Input.Submitted)
    def on_search_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.submit()

    @on(OptionList.OptionHighlighted, "SelectionOptionList")
    def on_option_highlighted(self, event: OptionList.OptionHighlighted):
        """Arrow keys and the pointer: filter_models moves the highlight without this event."""
        event.stop()
        self.refilter = KeepsHighlight()

    @on(OptionList.OptionSelected, "SelectionOptionList")
    def on_option_selected(self, event: OptionList.OptionSelected):
        event.stop()
        if event.option_id is not None:
            self.select_model(event.option_id)

    @property
    def cursor_owner(self) -> SelectionOptionList:
        return self.option_list

    def submit(self):
        connect = self.query_one(ConnectProvider)
        if connect.has_focus:
            connect.activate()
            return
        if (option := self.option_list.highlighted_option) is not None:
            if option.id is not None:
                self.select_model(option.id)


class ConfigurationKind(Select[type[ConfigurationSetting]]):
    """Which configuration setting the switcher picks among."""

    @on(Select.Changed)
    def chosen(self, event: Select.Changed) -> None:
        event.stop()
        # The nonblank Select owns validation of its advertised nominal values.
        if event.value is not Select.NULL:
            self.query_ancestor(ModelSwitcher).setting_chosen(event.value)

class ModelSwitcher(ScreenOverlay, ModelSelection, InfoPopup):

    setting_kind: type[ConfigurationSetting] = ModelConfigurationSetting


    @property
    def setting(self) -> ConfigurationSetting:
        return self.prompt.agent_binding.configuration.setting(self.setting_kind)

    def compose_content(self) -> ComposeResult:
        yield ConfigurationKind(
            [(self.setting_kind.label.title(), self.setting_kind)], allow_blank=False,
            value=self.setting_kind, compact=True,
        )
        yield from super().compose_content()

    def sync_picker(self) -> None:
        choices = [
            (setting.picker_title, type(setting))
            for setting in self.prompt.agent_binding.configuration.picker_settings
        ]
        if self.setting_kind not in {kind for _, kind in choices}:
            self.setting_kind = type(self).setting_kind
        selector = self.query_one(ConfigurationKind)
        with selector.prevent(Select.Changed):
            selector.set_options(choices)
            selector.value = self.setting_kind
        self.choice_name = self.setting.picker_title
        self.search_input.placeholder = f"Search {self.choice_name}…"
        self.query_one(ConnectProvider).display = self.setting.show_provider

    def configuration_changed(self) -> None:
        if self.is_mounted and self.selection_active:
            self.sync_picker()
        super().configuration_changed()

    def focus_content(self, scroll_visible: bool) -> None:
        self.sync_picker()
        super().focus_content(scroll_visible)

    def setting_chosen(self, kind: type[ConfigurationSetting]) -> None:
        self.setting_kind = kind
        self.focus_content(False)

    @classmethod
    def for_prompt(cls, prompt: Prompt) -> Self | None:
        return cls().data_bind(history_scope=type(prompt).model_history_scope)

    @property
    def choices(self):
        return self.setting.choices

    @property
    def current(self):
        return self.setting.current

    async def recent_choices(self, scope: str) -> list[str]:
        return await self.setting.recent_choices(scope)

    @property
    def selection_active(self):
        return self.is_open

    def select_model(self, model_id: str):
        self.publish_core(self.setting.selection_event(model_id))
        self.dismiss_control()

    def connect_provider(self):
        self.dismiss_control()
        self.publish_core(input_events.ProviderLogin())
