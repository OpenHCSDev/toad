"""Edit the current goal as a draft without replacing its identity."""

from collections.abc import Awaitable, Callable

from agent_comms import Goal, MentionCandidate
from textual import on
from textual.app import ComposeResult
from textual.containers import HorizontalGroup, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from toad.messages import UserInputSubmitted
from toad.widgets.channel_prompt import ChannelPrompt


class GoalEdit(ModalScreen[str | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]
    AUTO_FOCUS = "ChannelTextArea"
    DEFAULT_CSS = """
    GoalEdit { align: center middle; background: $background 40%; }
    GoalEdit > Vertical { width: 85%; height: auto; max-height: 90%; padding: 1;
        border: solid $primary; background: $surface; }
    GoalEdit ChannelPrompt { dock: none; height: auto; max-height: 20; margin: 1 0; }
    GoalEdit HorizontalGroup { height: auto; }
    GoalEdit Button { margin-right: 1; }
    """

    def __init__(
        self,
        goal: Goal,
        candidates: tuple[MentionCandidate, ...] = (),
        *,
        on_save: Callable[[str], Awaitable[None]],
    ):
        super().__init__()
        self.goal = goal
        self.on_save = on_save
        self.saving = False
        self.editor = ChannelPrompt(simple_input=True)
        self.editor.set_mention_candidates(candidates)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(
                "Edit goal · @ mentions · Tab completes · Enter saves", markup=False
            )
            yield self.editor
            yield Static("", markup=False, id="goal-edit-error")
            with HorizontalGroup():
                yield Button("Save", id="goal-save", variant="primary")
                yield Button("Cancel", id="goal-cancel")

    def on_mount(self) -> None:
        self.editor.agent_ready = True
        self.editor.text = self.goal.text

    @on(UserInputSubmitted)
    async def submit(self, event: UserInputSubmitted) -> None:
        event.stop()
        await self.save(event.body)

    async def save(self, text: str) -> None:
        if not text.strip() or self.saving:
            return
        self.saving = True
        save_button = self.query_one("#goal-save", Button)
        save_button.disabled = True
        try:
            await self.on_save(text.strip())
        except (OSError, ValueError) as error:
            self.query_one("#goal-edit-error", Static).update(str(error))
        else:
            self.dismiss(text.strip())
        finally:
            self.saving = False
            save_button.disabled = False

    @on(Button.Pressed, "#goal-save")
    async def save_clicked(self) -> None:
        await self.save(self.editor.text)

    @on(Button.Pressed, "#goal-cancel")
    def action_cancel(self) -> None:
        if not self.saving:
            self.dismiss(None)
