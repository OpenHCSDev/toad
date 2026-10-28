"""Edit the current goal as a draft without replacing its identity."""

from collections.abc import Awaitable, Callable

from agent_comms.coordination_errors import Refused
from agent_comms.goals import Goal
from agent_comms.mentions import MentionCandidate
from agent_comms.repo import Checkout
from textual import on
from textual.app import ComposeResult
from textual.containers import HorizontalGroup, Vertical
from toad.screens.modal import DismissibleScreen
from toad.widget_actions import DismissAction
from textual.widgets import Button, Static

from toad.core.input_events import UserInputSubmitted
from toad.core_event_carrier import CoreEventReceiver, CoreEventMessage
from metaclass_registry.mro_dispatch import handles
from toad.widgets.channel_prompt import ChannelPrompt


class GoalEdit(CoreEventReceiver, DismissibleScreen[str | None]):
    AUTO_FOCUS = "ChannelTextArea"
    DEFAULT_CSS = """
    GoalEdit { align: center middle; background: $background 40%; }
    GoalEdit > Vertical { width: 85%; height: auto; max-height: 90%; padding: 1;
        border: solid $primary; background: $surface; }
    GoalEdit ChannelPrompt { dock: none; height: auto; max-height: 20; margin: 1 0; }
    GoalEdit .goal-edit-progress { height: auto; max-height: 3; color: $text-muted; margin-bottom: 1; }
    GoalEdit HorizontalGroup { height: auto; }
    GoalEdit Button { margin-right: 1; }
    """

    def __init__(
        self,
        goal: Goal,
        candidates: tuple[MentionCandidate, ...] = (),
        *,
        project: Checkout,
        on_save: Callable[[str], Awaitable[None]],
    ):
        super().__init__()
        self.goal = goal
        self.on_save = on_save
        self.saving = False
        self.editor = ChannelPrompt(project=project)
        self.editor.set_mention_candidates(candidates)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(
                "Edit objective · @ mentions · Tab completes · Enter saves",
                markup=False,
            )
            yield self.editor
            if self.goal.progress:
                yield Static(
                    f"Progress (read-only): {self.goal.progress}",
                    markup=False,
                    classes="goal-edit-progress",
                )
            yield Static("", markup=False, id="goal-edit-error")
            with HorizontalGroup():
                yield Button("Save", id="goal-save", variant="primary")
                yield Button("Cancel", id="goal-cancel", action=f"screen.{DismissAction.binding_name()}")

    def on_mount(self) -> None:
        self.editor.text = self.goal.text

    @handles(UserInputSubmitted)
    async def submit(self, event: UserInputSubmitted, message: CoreEventMessage) -> None:
        message.stop()
        await self.save(event.body)

    async def save(self, text: str) -> None:
        if not text.strip() or self.saving:
            return
        self.saving = True
        save_button = self.query_one("#goal-save", Button)
        save_button.disabled = True
        try:
            await self.on_save(text.strip())
        except (Refused, ValueError) as error:
            self.query_one("#goal-edit-error", Static).update(str(error))
        else:
            self.dismiss(text.strip())
        finally:
            self.saving = False
            save_button.disabled = False

    @on(Button.Pressed, "#goal-save")
    async def save_clicked(self) -> None:
        await self.save(self.editor.text)

    def dismiss_control(self) -> None:
        if not self.saving:
            super().dismiss_control()
