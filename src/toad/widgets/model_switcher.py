"""Searchable, recently-used-first model picker for ACP sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from textual import events, getters, on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalGroup
from textual.content import Content
from textual.reactive import var
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from toad import messages
from toad.db import DB
from toad.widgets.selection import SelectionOptionList

if TYPE_CHECKING:
    from toad.acp.agent import Model


class ConnectProvider(Static, can_focus=True):
    BINDINGS = [("enter,space", "connect", "Connect provider")]

    def __init__(self):
        super().__init__("Connect a provider…", markup=False)

    def action_connect(self):
        self.query_ancestor(ModelSwitcher).is_open = False
        self.post_message(messages.ProviderLogin())

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


class ModelSwitcher(VerticalGroup):
    BINDING_GROUP_TITLE = "Model search"
    BINDINGS = [
        Binding("up", "cursor_up", "Previous model", priority=True),
        Binding("down", "cursor_down", "Next model", priority=True),
        Binding("enter", "submit", "Select model", priority=True),
        Binding("escape", "dismiss", "Close model search", priority=True),
        Binding("ctrl+u", "clear_search", "Clear search", priority=True, show=False),
    ]
    DEFAULT_CSS = """
    ModelSwitcher {
        display: none;
        overlay: screen;
        constrain: inside inflect;
        width: 80;
        max-width: 100vw;
        height: auto;
        max-height: 80vh;
        border: round $primary;
        background: $background;
        padding: 0;
        margin: 1 0;
    }
    ModelSwitcher.-open { display: block; }
    ModelSwitcher Input { height: 1; border: none; padding: 0 1; }
    ModelSwitcher .model-count { height: 1; padding: 0 1; color: $text-muted; }
    ModelSwitcher ConnectProvider { height: 1; padding: 0 1; color: $text-secondary; pointer: pointer; }
    ModelSwitcher ConnectProvider:hover, ModelSwitcher ConnectProvider:focus { text-style: underline; }
    ModelSwitcher OptionList {
        height: auto;
        max-height: 45vh;
        border: none;
        padding: 0;
        & > .option-list--option { padding: 0 1; }
    }
    ModelSwitcher OptionList > .option-list--option-highlighted {
        background: $block-cursor-background;
        color: $block-cursor-foreground;
        text-style: $block-cursor-text-style;
    }
    ModelSwitcher:ansi OptionList > .option-list--option-highlighted {
        background: ansi_blue;
        color: ansi_bright_white;
        text-style: bold;
    }
    """

    search_input = getters.query_one(Input)
    option_list = getters.query_one(OptionList)
    is_open = var(False, toggle_class="-open")
    history_scope = var("")

    def __init__(self):
        super().__init__()
        self.models: dict[str, Model] = {}
        self.current_model_id: str | None = None
        self.recent_ids: list[str] = []
        self._open_generation = 0
        self._selection_moved = False

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search models or providers…", compact=True)
        yield Static("", classes="model-count", markup=False)
        options = SelectionOptionList()
        options.can_focus = False
        yield options
        yield ConnectProvider()

    def set_models(self, models: dict[str, Model], current: Model | None) -> None:
        self.models = models
        self.current_model_id = current.id if current is not None else None
        if self.is_mounted and self.is_open:
            self.filter_models(preserve_selection=True)

    def focus(self, scroll_visible: bool = False) -> Self:
        self._open_generation += 1
        self._selection_moved = False
        self.is_open = True
        with self.search_input.prevent(Input.Changed):
            self.search_input.value = ""
        self.filter_models()
        self.search_input.focus(scroll_visible=False)
        self.load_recents(self._open_generation, self.history_scope)
        return self

    @work(exclusive=True)
    async def load_recents(self, generation: int, scope: str) -> None:
        recent = await DB().recent_models(scope)
        if (
            self.is_open
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
        ranked = []
        for model in self.models.values():
            fields = {model.name.casefold(), model.id.casefold()}
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
                model.id, len(recent) + (model.id != self.current_model_id)
            )
            ranked.append((-sum(scores), rank, model.name.casefold(), model.id, model))
        ranked.sort(key=lambda item: item[:4])
        options = []
        for *_, model in ranked:
            label = Content.assemble(
                ("✓ " if model.id == self.current_model_id else "  ", "$text-success"),
                (model.name, "bold"),
                (" · recent" if model.id in recent else "", "dim"),
            )
            if model.id != model.name:
                label += Content.styled(f" · {model.id}", "dim")
            options.append(Option(label, id=model.id))
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
            f"{len(options)} / {len(self.models)} models · {'best matches' if terms else 'recent first'}"
            if options
            else "No matching models"
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

    def select_model(self, model_id: str):
        self.post_message(messages.ChangeModel(model_id))
        self.action_dismiss()

    def action_cursor_up(self):
        self._selection_moved = True
        self.option_list.action_cursor_up()

    def action_cursor_down(self):
        self._selection_moved = True
        self.option_list.action_cursor_down()

    def action_submit(self):
        connect = self.query_one(ConnectProvider)
        if connect.has_focus:
            connect.action_connect()
            return
        if (option := self.option_list.highlighted_option) is not None:
            if option.id is not None:
                self.select_model(option.id)

    def action_clear_search(self):
        self.search_input.clear()

    def action_dismiss(self):
        self.is_open = False
        self.post_message(messages.Dismiss(self))

    def on_descendant_blur(self, event: events.DescendantBlur):
        self.call_later(self._close_if_unfocused)

    def _close_if_unfocused(self):
        if self.is_open and not self.has_focus_within:
            self.is_open = False
