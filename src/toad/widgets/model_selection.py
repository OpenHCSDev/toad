from __future__ import annotations

from formbridge.key_declarations import TextEntryMode
from textual import getters, on, work
from textual.app import ComposeResult
from textual.containers import VerticalGroup
from textual.content import Content
from textual.css.native import Keyword, NativeDeclaration, Variable
from textual.css.styles import Styles

from textual.reactive import var
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option, OptionListComponent
from ui_theme.scheme import (
    BackgroundColour,
    BlockCursorBackgroundColour,
    BlockCursorForegroundColour,
    BlockCursorTextStyle,
    PrimaryColour,
)

from toad.client.model_selection import (
    HighlightPlacement,
    KeepsHighlight,
    ModelChoice,
    ModelSelectionCore,
    ResetsHighlight,
    match_score,
)
from toad.core_event_carrier import CoreEventReceiver
from toad.native_style import (
    AutoHeight,
    Borderless,
    EllipsisOverflow,
    MutedText,
    NoPadding,
    NoWrap,
    OneRow,
    PointerCursor,
    ScrollsVertically,
    SecondaryText,
    SidePadding,
    SpacedAround,
    StableGutter,
)
from toad.widget_actions import (
    Activates,
    CyclesFocusedControl,
    DismissibleControl,
    ForwardsCursor,
    PriorityActions,
    Submits,
    WidgetAction,
)
from toad.widgets.prompt_popup import PaddedOptionRows
from toad.widgets.selection import InlineSelection, SelectionOptionList


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


class ClearModelSearchAction(WidgetAction):
    """Clear the model search query."""
    keys = {TextEntryMode: ("ctrl+u",)}
    priority = True

    async def apply(self, context: ModelSelection) -> None:
        context.search_input.clear()


class ModelCount(MutedText, OneRow, SidePadding, Static):

    """Its look is its bases."""


class ModelSearchInput(CyclesFocusedControl, Input):
    """Search text owns Tab traversal to the popup's next declared control."""


class ModelOptionList(
    StableGutter,
    ScrollsVertically,
    Borderless,
    AutoHeight,
    NoPadding,
    NoWrap,
    EllipsisOverflow,
    PaddedOptionRows,
    SelectionOptionList,
):
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


class SelectionBounds:
    def apply_native_layout(self) -> None:
            super().apply_native_layout()
            self.styles.constrain_x = "inside"
            self.styles.constrain_y = "inflect"
            self.styles.width = 80
            self.styles.max_width = "100%"
            self.styles.max_height = "80vh"


class ModelSelection(
    ModelSelectionCore,
    SelectionBounds,
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

    def __init__(self):
        super().__init__()
        self.init_model_selection()

    @property
    def selection_active(self) -> bool:
        return self.is_attached

    def compose_content(self) -> ComposeResult:
        yield ModelSearchInput(placeholder=f"Search {self.choice_name} or providers…", compact=True)
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

    @work(exclusive=True)
    async def load_recents(self, generation: int, scope: str) -> None:
        recent = await self.recent_choices(scope)
        self.apply_recents(generation, scope, recent)

    def filter_models(self, placement: HighlightPlacement) -> None:
        highlighted = self.option_list.highlighted_option
        previous_id = highlighted.id if highlighted is not None else None
        ranked, summary = self.rank_models(self.search_input.value)
        options = []
        for entry in ranked:
            model = entry.choice
            label = Content.assemble(
                ("✓ " if entry.is_current else "  ", "$text-success"),
                (model.name, "bold"),
                (" · recent" if entry.is_recent else "", "dim"),
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
        self.query_one(ModelCount).update(summary)

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
