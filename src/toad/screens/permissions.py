from toad.patch import DiffMode
from weakref import ref
import os
from textual import work, on
from textual.app import ComposeResult
from textual import containers

from textual import getters
from toad.widget_actions import CyclesFocus, PriorityActions
from textual.content import Content
from textual.screen import Screen
from textual.reactive import var, Initialize
from textual.css.native import Keyword, NativeDeclaration, Percent, Variable
from textual.css.styles import Styles
from textual.view import AUTO, FILL
from ui_theme.scheme import BackgroundColour, PrimaryColour

from toad.native_layout import NativeLayout, NativeTheme

from textual.widgets import OptionList, Static, Select
from toad.widgets.footer import ToadFooter
from textual.widgets.option_list import Option

from toad.answer import Answer
from toad.widgets.question import Question
from toad.question_actions import SelectKindAction, QuestionContext, PermissionNavigationAction

class FillArea(NativeLayout):
    """Areas sharing the available permission-review space."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = self.styles.height = FILL


class BackgroundArea(NativeTheme):
    native_theme = (
        NativeDeclaration.of(Styles.background, Variable(BackgroundColour.name)),
    )


class FaintArea(NativeTheme):
    native_theme = (
        NativeDeclaration.of(Styles.background, Keyword("black"), Percent(10)),
    )


class FramedArea(NativeTheme):
    """One property declaration owns the permission frame's outline."""

    faint_border = NativeDeclaration.of(
        Styles.border, Keyword("tall"), Keyword("black"), Percent(10)
    )

    @property
    def frame_declaration(self) -> NativeDeclaration:
        return self.faint_border

    def native_declarations(self) -> tuple[NativeDeclaration, ...]:
        return (*super().native_declarations(), self.frame_declaration)


class FocusedFrame(FramedArea):
    focused_border = NativeDeclaration.of(
        Styles.border, Keyword("tall"), Variable(PrimaryColour.name)
    )

    @property
    def frame_declaration(self) -> NativeDeclaration:
        # Focus changes only this frame's paint value; the control keeps its lifecycle.
        return self.focused_border if self.has_focus else super().frame_declaration

    def watch_has_focus(self, has_focus: bool) -> None:
        super().watch_has_focus(has_focus)
        self.apply_native_styles(self.app.stylesheet)


class PermissionGrid(FillArea, BackgroundArea, containers.Grid):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.margin = 1
        self.styles.padding = 0
        self.styles.grid_size_columns = self.styles.grid_size_rows = 2
        self.styles.grid_columns = (AUTO, FILL)
        self.styles.grid_rows = (AUTO, FILL)


class PermissionInstructions(FramedArea, FaintArea, NativeLayout, Static):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.padding = (0, 2)


class PermissionsQuestion(FocusedFrame, FaintArea, NativeLayout, Question):
    BINDING_GROUP_TITLE = "Permissions Options"

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = AUTO
        self.styles.max_width = 32
        self.styles.expand = "optimal"
        self.styles.height = AUTO
        self.styles.margin = (1, 0)
        self.styles.padding = (0, 2, 0, 1)


class ChangesOptionList(FillArea, OptionList):
    BINDING_GROUP_TITLE = "Changes list"

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.min_width = 20
        self.styles.expand = "optimal"


class DiffViewSelect(Select):
    BINDING_GROUP_TITLE = "Diff view select"


class NavigationArea(NativeLayout, containers.Vertical):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = AUTO
        self.styles.height = FILL


class ToolScroll(FocusedFrame, BackgroundArea, FillArea, containers.VerticalScroll):
    BINDING_GROUP_TITLE = "Changes window"

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.margin = (1, 0, 0, 0)


class PermissionsScreen(BackgroundArea, QuestionContext, PriorityActions, CyclesFocus, Screen[Answer],
                        actions=(SelectKindAction, PermissionNavigationAction),
                        scopes={PriorityActions: (SelectKindAction,)}):
    BINDING_GROUP_TITLE = "Permissions"
    AUTO_FOCUS = "Question"

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
        self._question = PermissionsQuestion("", options=options)
        self.diffs = diffs
        self.agent_name = agent_name

    @property
    def question(self) -> Question:
        return self._question

    def get_diff_type(self) -> type[DiffMode]:
        return self.app.settings.diff.view

    diff_type: var[type[DiffMode]] = var(Initialize(get_diff_type))

    def compose(self) -> ComposeResult:
        with PermissionGrid():
            yield DiffViewSelect(
                [(member.choice_label(), member) for member in DiffMode.members_with(DiffMode)],
                value=self.diff_type,
                allow_blank=False,
                id="diff-select",
            )
            yield PermissionInstructions(
                Content.from_markup(
                    "[b]Approval request[/b] [dim]$name wishes to make the following changes",
                    name=self.agent_name,
                ),
                id="instructions",
            )
            with NavigationArea(id="nav-container"):
                yield self.question
                yield ChangesOptionList(id="navigator")
            yield ToolScroll(id="tool-container")

        yield ToadFooter()

    async def on_mount(self):
        self.query_one("#diff-select", Select).value = self.get_diff_type()
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



class PermissionReview(PermissionsScreen):
    """Mounting checks the same pending request and source binding."""
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
        if not self.request.owns_projection(self.binding, view):
            event.prevent_default()
            self.retire()
