from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from textual import containers, events, on, widgets
from textual._activation import PrimaryActivation
from textual.app import ComposeResult
from textual.content import Content
from textual.message import Message
from textual.reactive import reactive, var
from textual.widget import Widget
from textual.screen import Screen

from toad.answer import Answer
from toad.tone_paint import UntintedTonePaint
from toad.question_actions import QuestionAction, QuestionContext, SelectKindAction
from toad.question_presentation import QuestionPresentation
from toad.widget_actions import DeclaredWidgetActions

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


class Option(PrimaryActivation, containers.HorizontalGroup):
    ALLOW_SELECT = False
    DEFAULT_CSS = """
    Option {

        &:hover {
            background: $boost;
        }
        color: $text-muted;
        #caret {
            visibility: hidden;
            padding: 0 1;
        }
        #index {
            padding-right: 1;
        }
        #label {
            width: 1fr;
        }
        &.-active {            
            color: $text-accent;
            #caret {
                visibility: visible;
            }
        }
        &.-selected {
            opacity: 0.5;
        }
        &.-active.-selected {
            opacity: 1.0;
            background: transparent;
            color: $text-accent;            
            #label {
                text-style: underline;
            }
            #caret {
                visibility: hidden;
            }
        }
    }
    """

    @dataclass
    class Selected(Message):
        """The option was selected."""

        index: int

    keys: reactive[tuple[str, ...]] = reactive(())

    selected: reactive[bool] = reactive(False, toggle_class="-selected")

    def __init__(
        self, index: int, content: Content, keys: tuple[str, ...], classes: str = ""
    ) -> None:
        super().__init__(classes=classes)
        self.index = index
        self.content = content
        self.keys = keys

    def compose(self) -> ComposeResult:
        yield OptionMarker("❯", id="caret")
        yield OptionMarker(Content.styled(", ".join(self.keys) or " ", "b"), id="index")
        yield NonSelectableLabel(self.content, id="label")

    def watch_keys(self, keys: tuple[str, ...]) -> None:
        for marker in self.query("#index").results(OptionMarker):
            marker.update(Content.styled(", ".join(keys) or " ", "b"))

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.select_option()

    @property
    def primary_activation(self):
        return self.select_option

    def select_option(self) -> None:
        self.post_message(self.Selected(self.index))


class Question(QuestionContext, DeclaredWidgetActions, containers.VerticalGroup, actions=(QuestionAction,), can_focus=True):
    """A text question with a menu of responses."""

    BINDING_GROUP_TITLE = "Question"
    ALLOW_SELECT = False
    DEFAULT_CSS = """
    Question {
        width: 1fr;
        height: auto;
        padding: 0 1; 
        background: transparent;
        #title {
            margin-bottom: 1;
            color: $text-primary;
        }
        #question-container {
            margin-bottom: 1;
        }        

        

        #option-container.-blink Option.-active #caret {
            opacity: 0.2;
        }

    }
    """

    title: var[str] = var("")
    options: var[Options] = var(list)

    selection: reactive[int] = reactive(0, init=False)
    selected: var[bool] = var(False, toggle_class="-selected")
    blink: var[bool] = var(False)


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
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self.set_reactive(Question.title, title)
        self.presentation = QuestionPresentation()
        self._option_view = containers.VerticalGroup(id="option-container")
        self._ask: Ask | None = None
        self._get_content = get_content
        self.set_reactive(Question.options, options or [])

    def watch_has_focus(self, has_focus: bool) -> None:
        super().watch_has_focus(has_focus)
        self.presentation.mount.focus(has_focus)
        if not has_focus:
            self.blink = False
        for marker in self.query(OptionMarker):
            marker.refresh_paint()

    def on_mount(self) -> None:
        self.presentation.reopen()
        self.presentation.start(self, self._option_view)
        self.screen.bindings_updated_signal.subscribe(self, self.refresh_option_keys)

    def on_unmount(self) -> None:
        self.screen.bindings_updated_signal.unsubscribe(self)
        self.presentation.retire()

    def _reset_blink(self) -> None:
        self.blink = False
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

        with containers.VerticalGroup(id="contents"):
            if self.title:
                yield widgets.Label(self.title, id="title", markup=False)
            if self._get_content is not None:
                yield self._get_content()

        self._option_view = containers.VerticalGroup(id="option-container")
        with self._option_view:
            for index, (answer, keys) in enumerate(zip(self.options, self.option_keys())):
                yield Option(
                    index, Content(answer.text), keys,
                    classes="-active" if index == self.selection else "",
                ).data_bind(Question.selected)

    def option_keys(self) -> tuple[tuple[str, ...], ...]:
        candidates = tuple((declaration.kind, binding.key)
                           for declaration in SelectKindAction.members_with(SelectKindAction)
                           for binding in declaration.configured_bindings(self))
        seen: set[str] = set()
        result = []
        for answer in self.options:
            result.append(tuple(key for kind, key in candidates
                                if kind == answer.kind and kind not in seen))
            seen.update(kind for kind, _key in candidates if kind == answer.kind)
        return tuple(result)

    def refresh_option_keys(self, _screen: Screen) -> None:
        for option, keys in zip(self.query(Option), self.option_keys()):
            option.keys = keys

    @property
    def question(self) -> Question:
        return self

    @property
    def accepts_selection(self) -> bool:
        return not self.selected and 0 <= self.selection < len(self.options)

    def watch_selection(self, old_selection: int, new_selection: int) -> None:
        self.presentation.mount.select(new_selection)

    async def recompose(self) -> None:
        await self.presentation.recompose(self, super().recompose)

    def watch_blink(self, blink: bool) -> None:
        self.presentation.mount.blink(blink)

    @on(Option.Selected)
    def on_option_selected(self, event: Option.Selected) -> None:
        event.stop()
        self._reset_blink()
        if not self.selected:
            self.selection = event.index


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
