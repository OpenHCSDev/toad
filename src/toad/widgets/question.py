from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from textual.app import ComposeResult
from textual import events, on
from textual.binding import Binding
from textual import containers
from textual.content import Content
from textual.reactive import var, reactive
from textual.message import Message
from textual.widget import Widget

from textual import widgets

from toad.answer import Answer
from toad.question_presentation import QuestionPresentation
from toad.widget_actions import DeclaredWidgetActions
from toad.question_actions import QuestionAction, SelectKindAction

type Options = list[Answer]


@dataclass
class Ask:
    """Data for Question."""

    question: str
    options: Options
    get_content: Callable[[], Widget] | None = None
    callback: Callable[[Answer], Any] | None = None


class NonSelectableLabel(widgets.Label):
    ALLOW_SELECT = False


class Option(containers.HorizontalGroup):
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

    selected: reactive[bool] = reactive(False, toggle_class="-selected")

    def __init__(
        self, index: int, content: Content, key: str | None, classes: str = ""
    ) -> None:
        super().__init__(classes=classes)
        self.index = index
        self.content = content
        self.key = key

    def compose(self) -> ComposeResult:
        key = self.key
        yield NonSelectableLabel("❯", id="caret")
        if key:
            yield NonSelectableLabel(Content.styled(f"{key}", "b"), id="index")
        else:
            yield NonSelectableLabel(Content(" "), id="index")

        yield NonSelectableLabel(self.content, id="label")

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.post_message(self.Selected(self.index))


class Question(DeclaredWidgetActions, containers.VerticalGroup, can_focus=True):
    ACTIONS = QuestionAction
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

        &:blur {
            #index {
                opacity: 0.3;
            }
            #caret {
                opacity: 0.3;
            }
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
    ):
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self.set_reactive(Question.title, title)
        self.presentation = QuestionPresentation()
        self._option_view = containers.VerticalGroup(id="option-container")
        self._ask: Ask | None = None
        self._get_content = get_content
        self.set_reactive(Question.options, options or [])

    def on_mount(self) -> None:
        self.presentation.reopen()
        self.presentation.start(self, self._option_view)

    def on_unmount(self) -> None:
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
            kinds: set[str] = set()
            for index, answer in enumerate(self.options):
                active = index == self.selection
                key = (
                    SelectKindAction.SHORTCUTS.get(answer.kind, (None, ""))[0]
                    if (answer.kind and answer.kind not in kinds)
                    else None
                )
                yield Option(
                    index,
                    Content(answer.text),
                    key,
                    classes="-active" if active else "",
                ).data_bind(Question.selected)
                if answer.kind is not None:
                    kinds.add(answer.kind)

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
