from toad.setting_choices import DiffMode, AutoDiff
from weakref import ref
import os
from textual import work, on
from textual.app import ComposeResult
from textual import containers

from textual import getters
from textual.binding import Binding
from textual.content import Content
from textual.screen import Screen
from textual.reactive import var, Initialize

from textual.widgets import OptionList, Footer, Static, Select
from textual.widgets.option_list import Option

from toad.answer import Answer
from toad.widgets.question import Question
from toad.question_actions import SelectKindAction

from toad.app import ToadApp

class PermissionsQuestion(Question):
    BINDING_GROUP_TITLE = "Permissions Options"


class ChangesOptionList(OptionList):
    BINDING_GROUP_TITLE = "Changes list"


class DiffViewSelect(Select):
    BINDING_GROUP_TITLE = "Diff view select"


class ToolScroll(containers.VerticalScroll):
    BINDING_GROUP_TITLE = "Changes window"


class PermissionsScreen(Screen[Answer]):
    BINDING_GROUP_TITLE = "Permissions"
    AUTO_FOCUS = "Question"
    CSS_PATH = "permissions.tcss"

    TAB_GROUP = Binding.Group("Focus")
    NAVIGATION_GROUP = Binding.Group("Navigation", compact=True)
    BINDINGS = [
        Binding("j", "next", "Next", group=NAVIGATION_GROUP),
        Binding("k", "previous", "Previous", group=NAVIGATION_GROUP),
        Binding(
            "tab",
            "app.focus_next",
            "Focus next",
            group=TAB_GROUP,
            show=True,
            priority=True,
        ),
        Binding(
            "shift+tab",
            "app.focus_previous",
            "Focus previous",
            group=TAB_GROUP,
            show=True,
            priority=True,
        ),
        *SelectKindAction.bindings(priority=True),
    ]

    tool_container = getters.query_one("#tool-container", containers.VerticalScroll)
    navigator = getters.query_one("#navigator", OptionList)
    index: var[int] = var(0)

    def __init__(
        self,
        options: list[Answer],
        diffs: list[tuple[str, str, str | None, str]] | None = None,
        agent_name: str = "The Agent",
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        """

        Args:
            options: Potential answers to the permission request.
            diffs: List of diffs to display, tuples of (PATH1, PATH2, SOURCE1, SOURCE2)
            name: Textual name attribute.
            id: Textual id attribute.
            classe: Textual classes.
        """
        super().__init__(name=name, id=id, classes=classes)
        self.question = PermissionsQuestion("", options=options)
        self.diffs = diffs
        self.agent_name = agent_name

    def get_diff_type(self) -> type[DiffMode]:
        app = self.app
        diff_type = AutoDiff
        if isinstance(app, ToadApp):
            diff_type = app.settings.diff.view
        return diff_type

    diff_type: var[type[DiffMode]] = var(Initialize(get_diff_type))

    def compose(self) -> ComposeResult:
        with containers.Grid(classes="top"):
            yield DiffViewSelect(
                [(member.label(), member) for member in DiffMode.members_with(DiffMode)],
                value=self.diff_type,
                allow_blank=False,
                id="diff-select",
            )
            yield Static(
                Content.from_markup(
                    "[b]Approval request[/b] [dim]$name wishes to make the following changes",
                    name=self.agent_name,
                ),
                id="instructions",
            )
            with containers.Vertical(id="nav-container"):
                yield self.question
                yield ChangesOptionList(id="navigator")
            yield ToolScroll(id="tool-container")

        yield Footer()

    async def action_select_kind(self, kind: str | tuple[str, ...]) -> None:
        command = SelectKindAction.parse((kind,))
        if command.available(self.question):
            await command.apply(self.question)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return self.question.check_action(action, parameters)

    async def on_mount(self):
        app = self.app
        if isinstance(app, ToadApp):
            diff_view_setting = app.settings.diff.view
            self.query_one("#diff-select", Select).value = diff_view_setting
        self.navigator.highlighted = 0

        self._add_diffs()
        self.question.focus()

    @work
    async def _add_diffs(self) -> None:
        """Add any diffs given in the constructor."""
        if self.diffs is None:
            return
        diffs = self.diffs[:]
        self.diffs = None
        for diff in diffs:
            if not self.is_attached:
                return  # The controller may have cancelled while the screen hydrated.
            await self.add_diff(*diff)

    async def add_diff(
        self, path1: str, path2: str, before: str | None, after: str
    ) -> None:
        self.index += 1
        option_id = f"item-{self.index}"
        from toad.widgets.diff_view import make_diff

        diff_view = make_diff(path1, path2, before, after, id=option_id)
        await diff_view.prepare()
        container = self.query_one_optional("#tool-container", containers.VerticalScroll)
        if container is None:
            return
        await container.mount(diff_view)
        if not self.is_attached:
            return

        option_text = f"📄 {os.path.basename(path1)}"
        navigator = self.query_one_optional("#navigator", OptionList)
        if navigator is not None:
            navigator.add_option(Option(option_text, option_id))

    @on(OptionList.OptionHighlighted)
    def on_option_highlighted(self, event: OptionList.OptionHighlighted):
        container = self.query_one_optional("#tool-container", containers.VerticalScroll)
        if container is not None:
            diff = container.query_one_optional(f"#{event.option_id}")
            if diff is not None:
                diff.scroll_visible(top=True)

    @on(Question.Answer)
    def on_question_answer(self, event: Question.Answer) -> None:
        def dismiss():
            self.dismiss(event.answer)

        self.set_timer(0.4, dismiss)

    @on(Select.Changed, "#diff-select")
    def on_diff_select(self, event: Select.Changed) -> None:
        diff_type = event.value
        from textual_diff_view import DiffView

        for diff_view in self.query(DiffView):
            diff_view.auto_split = diff_type.auto_split
            diff_view.split = diff_type.split

    def action_next(self) -> None:
        self.navigator.action_cursor_down()

    def action_previous(self) -> None:
        self.navigator.action_cursor_up()


class PermissionReview(PermissionsScreen):
    """Admission at mount uses the same pending request and source binding."""
    def __init__(self, request, view, diffs, binding):
        super().__init__(request.options, diffs, agent_name=view.agent_title or "The Agent")
        self.request = request
        self.binding = binding
        self._view = ref(view)

    def retire(self):
        if self.is_active:
            self.dismiss(None)

    def on_screen_resume(self, event):
        self.on_mount(event)

    def on_mount(self, event):
        view = self._view()
        if view is None or not self.request.pending or self.request.controller.agent.controller.surface is not self.binding:
            event.prevent_default()
            self.retire()
