from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterator
from typing import Callable, ClassVar

from textual import containers, events, on, widgets
from textual._activation import PrimaryActivation
from textual.app import ComposeResult
from textual.content import Content
from textual.css.native import DeclaresTheme, Keyword, NativeDeclaration, NativeStyleResolver, Percent, TextVariable, Variable
from textual.css.styles import Styles
from textual.message import Message
from textual.reactive import reactive, var
from textual.widget import Widget
from textual.screen import Screen
from ui_theme.scheme import AccentColour, BoostColour, MutedColour

from toad.answer import Answer
from toad.native_style import (
    FillWidth,
    MutedText,
    NoMargin,
    PrimaryText,
    RightPadding,
    ScrollsVertically,
    SidePadding,
    SpacedBelow,
    StartsHidden,
    TransparentBackground,
)
from toad.tone_paint import UntintedTonePaint
from toad.question_actions import QuestionAction, QuestionContext, SelectKindAction
from toad.question_presentation import QuestionPresentation
from toad.widget_actions import StepsVerticalCursor, VisibleActions

type Options = list[Answer]


@dataclass
class Ask:
    """Data for Question."""

    question: str
    options: Options
    get_content: Callable[[], Widget] | None = None
    callback: Callable[[Answer], None] | None = None


class NonSelectableLabel(widgets.Label):
    ALLOW_SELECT = False


class OptionMarker(UntintedTonePaint, NonSelectableLabel):
    @property
    def paint_opacity(self):
        return 1.0 if self.query_ancestor(Question).has_focus else 0.3


class OptionPlace(DeclaresTheme):
    """Where an option stands against its question's cursor and answer; each place owns its look.

    Every place declares every property any place changes, so a move replaces the old look.
    """

    native_theme: ClassVar[tuple[NativeDeclaration, ...]] = (
        NativeDeclaration.of(Styles.color, TextVariable(MutedColour.name)),
        NativeDeclaration.of(Styles.opacity, Percent(100)),
    )
    caret_theme: ClassVar[tuple[NativeDeclaration, ...]] = (
        NativeDeclaration.of(Styles.visibility, Keyword("hidden")),
    )
    label_text_style: ClassVar[str] = "none"


class AwayOption(OptionPlace):
    """Neither under the cursor nor answered."""


class CursorOption(OptionPlace):
    native_theme = (
        NativeDeclaration.of(Styles.color, TextVariable(AccentColour.name)),
        NativeDeclaration.of(Styles.opacity, Percent(100)),
    )
    caret_theme = (NativeDeclaration.of(Styles.visibility, Keyword("visible")),)


class PassedOption(MutedText, OptionPlace):
    """Another option was the answer."""

    native_theme = (NativeDeclaration.of(Styles.opacity, Percent(50)),)


class ChosenOption(TransparentBackground, OptionPlace):
    """The answer; the pointer no longer highlights it."""

    native_theme = (NativeDeclaration.of(Styles.color, TextVariable(AccentColour.name)), NativeDeclaration.of(Styles.opacity, Percent(100)))
    label_text_style = "underline"


OPTION_PLACES = ((AwayOption, CursorOption), (PassedOption, ChosenOption))
"""Indexed by whether the question is answered, then whether the option is under the cursor."""


class CaretPhase(DeclaresTheme):
    """The cursor caret's blink phase; each phase owns the caret's opacity."""

    native_theme: ClassVar[tuple[NativeDeclaration, ...]] = (
        NativeDeclaration.of(Styles.opacity, Percent(100)),
    )

    @classmethod
    def toggled(cls) -> type[CaretPhase]:
        return DimCaret


class LitCaret(CaretPhase):
    pass


class DimCaret(CaretPhase):
    native_theme = (NativeDeclaration.of(Styles.opacity, Percent(20)),)

    @classmethod
    def toggled(cls) -> type[CaretPhase]:
        return LitCaret


class OptionCaret(SidePadding, OptionMarker):

    def native_declarations(self) -> tuple[NativeDeclaration, ...]:
        return (*super().native_declarations(),
                *self.query_ancestor(Option).place.caret_theme,
                *self.query_ancestor(Question).caret_phase.declared_theme())


class OptionKeys(RightPadding, OptionMarker):
    """Its look is its bases."""


class OptionLabel(FillWidth, NonSelectableLabel):

    def apply_native_styles(self, resolver: NativeStyleResolver) -> None:
        # A native text-style declaration publishes its unparsed flags, which paint cannot add.
        super().apply_native_styles(resolver)
        self.styles.text_style = self.query_ancestor(Option).place.label_text_style


class Option(PrimaryActivation, TransparentBackground, containers.HorizontalGroup):
    ALLOW_SELECT = False
    hover_theme: ClassVar[tuple[NativeDeclaration, ...]] = (
        NativeDeclaration.of(Styles.background, Variable(BoostColour.name)),
    )
    pointer_theme: tuple[NativeDeclaration, ...] = ()

    @dataclass
    class Selected(Message):
        """The option was selected."""

        index: int

    keys: reactive[tuple[str, ...]] = reactive(())

    def __init__(self, index: int, content: Content, keys: tuple[str, ...]) -> None:
        super().__init__()
        self.index = index
        self.content = content
        self.keys = keys

    @property
    def place(self) -> type[OptionPlace]:
        question = self.query_ancestor(Question)
        return OPTION_PLACES[question.selected][self.index == question.selection]

    def native_declarations(self) -> tuple[NativeDeclaration, ...]:
        return (*super().native_declarations(), *self.pointer_theme, *self.place.declared_theme())

    @on(events.Enter)
    @on(events.Leave)
    def pointer_moved(self) -> None:
        self.pointer_theme = ((), self.hover_theme)[self.is_mouse_over]
        self.update_node_styles()

    def compose(self) -> ComposeResult:
        yield OptionCaret("❯")
        yield OptionKeys(Content.styled(", ".join(self.keys) or " ", "b"))
        yield OptionLabel(self.content)

    def watch_keys(self, keys: tuple[str, ...]) -> None:
        for marker in self.query(OptionKeys):
            marker.update(Content.styled(", ".join(keys) or " ", "b"))

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.select_option()

    @property
    def primary_activation(self):
        return self.select_option

    def select_option(self) -> None:
        self.post_message(self.Selected(self.index))


class QuestionContents(containers.VerticalGroup):
    """The question's title and any content it shows above the options."""


class QuestionTitle(PrimaryText, SpacedBelow, widgets.Label):

    """Its look is its bases."""


class QuestionOptions(containers.VerticalGroup):
    """The question's answers, in order."""


class Question(VisibleActions, StepsVerticalCursor, QuestionContext, containers.VerticalGroup, actions=(QuestionAction,), can_focus=True):
    """A text question with a menu of responses."""

    BINDING_GROUP_TITLE = "Question"
    ALLOW_SELECT = False
    CONTENTS: ClassVar[type[QuestionContents]] = QuestionContents
    TITLE: ClassVar[type[QuestionTitle]] = QuestionTitle
    OPTIONS: ClassVar[type[QuestionOptions]] = QuestionOptions

    title: var[str] = var("")
    options: var[Options] = var(list)

    selection: reactive[int] = reactive(0, init=False)
    selected: var[bool] = var(False, init=False)
    # A reactive calls a callable default; the lambda keeps the member class itself.
    caret_phase: var[type[CaretPhase]] = var(lambda: LitCaret, init=False)


    @dataclass
    class Answer(Message):
        """User selected a response from this exact request."""

        index: int
        answer: Answer
        ask: Ask | None

    def __init__(
        self,
        title: str = "Ask and you will receive",
        get_content: Callable[[], Widget] | None = None,
        options: Options | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(disabled=disabled)
        self.set_reactive(Question.title, title)
        self.presentation = QuestionPresentation()
        self._option_view = self.OPTIONS()
        self._ask: Ask | None = None
        self._get_content = get_content
        self.set_reactive(Question.options, options or [])

    def watch_has_focus(self, has_focus: bool) -> None:
        super().watch_has_focus(has_focus)
        self.presentation.mount.focus(has_focus)
        self.caret_phase = LitCaret
        for marker in self.query(OptionMarker):
            marker.refresh_paint()

    def on_mount(self) -> None:
        self.presentation.reopen()
        self.presentation.start(self, self._option_view)
        self.screen.bindings_updated_signal.subscribe(self, self.refresh_option_keys)

    def on_unmount(self) -> None:
        self.presentation.retire()

    def _reset_blink(self) -> None:
        self.caret_phase = LitCaret
        self.presentation.mount.reset()

    def update(self, ask: Ask) -> None:
        self._ask = ask
        self.title = ask.question
        self._get_content = ask.get_content
        self.options = ask.options
        self.selection = 0
        self.selected = False
        self.presentation.detach()
        self.refresh(recompose=True, layout=True)
        self.refresh_bindings()

    def compose(self) -> ComposeResult:

        with self.CONTENTS():
            if self.title:
                yield self.TITLE(self.title, markup=False)
            if self._get_content is not None:
                yield self._get_content()

        self._option_view = self.OPTIONS()
        with self._option_view:
            for index, (answer, keys) in enumerate(zip(self.options, self.option_keys())):
                yield Option(index, Content(answer.text), keys)

    def option_keys(self) -> Iterator[tuple[str, ...]]:
        """Each answer's keys, in answer order. Lazy: zipped against no options, the binding maps
        are never built, so a question with nothing to answer pays nothing on a binding change."""
        candidates = tuple((declaration.kind, binding.key)
                           for declaration in SelectKindAction.members_with(SelectKindAction)
                           for binding in declaration.configured_bindings(self))
        seen: set[str] = set()
        for answer in self.options:
            yield tuple(key for kind, key in candidates if kind == answer.kind and kind not in seen)
            seen.update(kind for kind, _key in candidates if kind == answer.kind)

    def refresh_option_keys(self, _screen: Screen) -> None:
        for option, keys in zip(self.query(Option), self.option_keys()):
            option.keys = keys

    @property
    def question(self) -> Question:
        return self

    @property
    def accepts_selection(self) -> bool:
        return not self.selected and 0 <= self.selection < len(self.options)

    @property
    def accepts_navigation(self) -> bool:
        return self.accepts_selection

    def step_vertical(self, direction: int) -> None:
        self._reset_blink()
        self.selection = max(0, min(len(self.options) - 1, self.selection + direction))

    def watch_selection(self) -> None:
        self.presentation.mount.restyle()

    def watch_selected(self) -> None:
        self.presentation.mount.restyle()

    def watch_caret_phase(self) -> None:
        self.presentation.mount.restyle()

    async def recompose(self) -> None:
        await self.presentation.recompose(self, super().recompose)

    @on(Option.Selected)
    def on_option_selected(self, event: Option.Selected) -> None:
        event.stop()
        self._reset_blink()
        if not self.selected:
            self.selection = event.index


class PromptQuestionContents(
    SpacedBelow,
    RightPadding,
    ScrollsVertically,
    QuestionContents,
):
    """Scrolls tall content inside the prompt; holds one row when there is nothing to show."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.overflow_x = "hidden"
        self.styles.max_height = "50vh"
        self.styles.min_height = 1


class PromptQuestionTitle(FillWidth, NoMargin, QuestionTitle):
    """Its look is its bases."""


class PromptQuestionOptions(QuestionOptions):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.split = "bottom"


class PromptQuestion(SidePadding, StartsHidden, Question):
    """The question the prompt shows in place of its editor."""

    CONTENTS = PromptQuestionContents
    TITLE = PromptQuestionTitle
    OPTIONS = PromptQuestionOptions



if __name__ == "__main__":
    from textual.app import App
    from textual.widgets import Footer

    OPTIONS = [
        Answer(
            "Yes, allow once, and here is some annoyingly long text to deal with",
            "proceed_always",
            kind="allow_once",
        ),
        Answer("Yes, allow always", "allow_always", kind="allow_always"),
        Answer("Modify with external editor", "modify", kind="allow_once"),
        Answer("No, suggest changes (esc)", "reject"),
    ]

    class QuestionApp(App):
        def compose(self) -> ComposeResult:
            yield Question("Apply this change?", options=OPTIONS)
            yield Footer()

    QuestionApp().run()
