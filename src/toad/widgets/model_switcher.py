"""Searchable, recently-used-first model picker for ACP sessions."""

from __future__ import annotations
from toad.core import input_events
from toad.core_event_carrier import CoreEventReceiver

from abc import abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Self, Protocol

from textual import events, getters, on, work
from textual.app import ComposeResult
from textual.binding import Binding
from toad.widget_actions import PriorityActions, MovesCursor, Submits, Dismisses
from textual.content import Content
from textual.containers import VerticalGroup
from textual.reactive import var
from textual.widgets import Input, OptionList, Static
from textual._activation import PrimaryActivation
from textual.widgets.option_list import Option

from toad import messages
from toad.db import DB
from toad.widgets.selection import SelectionOptionList, InlineSelection
from toad.widgets.prompt_popup import InfoPopup

if TYPE_CHECKING:
    from toad.widgets.prompt import Prompt


class ConnectProvider(InlineSelection, PrimaryActivation, CoreEventReceiver, Static, can_focus=True):
    BINDINGS = [("enter,space", "connect", "Connect provider")]

    def __init__(self):
        super().__init__("Connect a provider…", markup=False)

    @property
    def primary_activation(self):
        return self.action_connect

    def action_connect(self):
        self.query_ancestor(ModelSelection).connect_provider()

    def on_click(self, event: events.Click):
        event.stop()
        self.action_connect()


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


class ModelSelection(PriorityActions, MovesCursor, Submits, Dismisses, CoreEventReceiver, VerticalGroup):
    """Search, recents and provider connection shared by prompt and creation views."""
    BINDING_GROUP_TITLE = "Model search"
    BINDINGS = [
        Binding("ctrl+u", "clear_search", "Clear search", priority=True, show=False),
    ]
    DEFAULT_CSS = """
    ModelSelection {
        constrain: inside inflect;
        width: 80;
        max-width: 100%;
        height: auto;
        max-height: 80vh;
        border: round $primary;
        background: $background;
        padding: 0;
        margin: 1 0;
    }
    ModelSelection Input { height: 1; border: none; padding: 0 1; }
    ModelSelection .model-count { height: 1; padding: 0 1; color: $text-muted; }
    ModelSelection ConnectProvider { height: 1; padding: 0 1; color: $text-secondary; pointer: pointer; }
    ModelSelection OptionList {
        height: auto;
        max-height: 45vh;
        border: none;
        padding: 0;
        & > .option-list--option { padding: 0 1; }
    }
    ModelSelection OptionList > .option-list--option-highlighted {
        background: $block-cursor-background;
        color: $block-cursor-foreground;
        text-style: $block-cursor-text-style;
    }
    """

    search_input = getters.query_one(Input)
    option_list = getters.query_one(OptionList)
    history_scope = var("")
    choice_name = "models"

    def __init__(self):
        super().__init__()
        self.recent_ids: list[str] = []
        self._open_generation = 0
        self._selection_moved = False

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
        yield Static("", classes="model-count", markup=False)
        options = SelectionOptionList()
        options.can_focus = False
        yield options
        yield ConnectProvider()

    def configuration_changed(self) -> None:
        if self.is_mounted and self.selection_active:
            self.filter_models(preserve_selection=True)

    def focus_content(self, scroll_visible: bool) -> None:
        self._open_generation += 1
        self._selection_moved = False
        with self.search_input.prevent(Input.Changed):
            self.search_input.value = ""
        self.filter_models()
        self.search_input.focus(scroll_visible=False)
        self.load_recents(self._open_generation, self.history_scope)

    @work(exclusive=True)
    async def load_recents(self, generation: int, scope: str) -> None:
        recent = await DB().recent_models(scope)
        if (
            self.selection_active
            and generation == self._open_generation
            and scope == self.history_scope
        ):
            self.recent_ids = recent
            self.filter_models(
                preserve_selection=self._selection_moved
                or bool(self.search_input.value)
            )

    def filter_models(self, *, preserve_selection: bool = False) -> None:
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
        self.option_list.set_options(options)
        if options:
            ids = [option.id for option in options]
            self.option_list.highlighted = (
                ids.index(previous_id)
                if preserve_selection and previous_id in ids
                else 0
            )
        else:
            self.option_list.highlighted = None
        self.query_one(".model-count", Static).update(
            f"{len(options)} / {len(models)} {self.choice_name} · {'best matches' if terms else 'recent first'}"
            if options
            else f"No matching {self.choice_name}"
        )

    @on(Input.Changed)
    def on_search_changed(self, event: Input.Changed):
        event.stop()
        self._selection_moved = False
        self.filter_models()

    @on(OptionList.OptionHighlighted)
    def on_option_highlighted(self, event: OptionList.OptionHighlighted):
        event.stop()

    @on(SelectionOptionList.PointerSelected)
    def on_pointer_selected(self, event: SelectionOptionList.PointerSelected) -> None:
        event.stop()
        self._selection_moved = True

    @on(OptionList.OptionSelected)
    def on_option_selected(self, event: OptionList.OptionSelected):
        event.stop()
        if event.option_id is not None:
            self.select_model(event.option_id)

    def cursor_up(self):
        self._selection_moved = True
        self.option_list.action_cursor_up()

    def cursor_down(self):
        self._selection_moved = True
        self.option_list.action_cursor_down()

    def submit(self):
        connect = self.query_one(ConnectProvider)
        if connect.has_focus:
            connect.action_connect()
            return
        if (option := self.option_list.highlighted_option) is not None:
            if option.id is not None:
                self.select_model(option.id)

    def action_clear_search(self):
        self.search_input.clear()


class ModelSwitcher(ModelSelection, InfoPopup):
    DEFAULT_CSS = """
    ModelSwitcher { display: none; overlay: screen; }
    ModelSwitcher.-open { display: block; }
    """

    @classmethod
    def for_prompt(cls, prompt: Prompt) -> Self | None:
        return cls().data_bind(history_scope=type(prompt).model_history_scope)

    @property
    def choices(self):
        return self.prompt.agent_binding.configuration.model.choices

    @property
    def current(self):
        return self.prompt.agent_binding.configuration.model.current

    @property
    def selection_active(self):
        return self.is_open

    def select_model(self, model_id: str):
        self.publish_core(input_events.ChangeModel(model_id))
        self.dismiss()

    def connect_provider(self):
        self.dismiss()
        self.publish_core(input_events.ProviderLogin())
