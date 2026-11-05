"""Edit the current goal as a draft without replacing its identity."""

from collections.abc import Awaitable, Callable

from agent_comms.coordination.errors import Refused
from agent_comms.goals import Goal
from agent_comms.mentions import MentionCandidate
from agent_comms.repo import Checkout
from textual.app import ComposeResult
from textual.containers import HorizontalGroup
from toad.widgets.acting_button import ConfirmButton, Confirms, DismissButton
from toad.native_style import (
    AutoHeight,
    MutedText,
    RightMargin,
    SpacedAround,
    SpacedBelow,
)
from toad.screens.modal import CenteredScreen, DismissibleScreen, ModalPanel, ShadedScreen

from textual.widgets import Button, Static

from toad.core.input_events import UserInputSubmitted
from toad.core_event_carrier import CoreEventReceiver, CoreEventMessage
from metaclass_registry.mro_dispatch import handles
from toad.widgets.channel_prompt import DraftPrompt


class GoalEditPanel(AutoHeight, ModalPanel):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = "85%"
        self.styles.max_height = "90%"
        self.styles.padding = 1


class GoalEditor(SpacedAround, DraftPrompt, AutoHeight):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.dock = "none"
        self.styles.max_height = 20


class GoalEditProgress(SpacedBelow, MutedText, AutoHeight, Static):

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.max_height = 3


class GoalEditError(Static):
    """Why the backend refused the edit."""


class GoalEditButtons(AutoHeight, HorizontalGroup):
    """Its look is its bases."""


class GoalEditButton(RightMargin, Button):
    """Its look is its bases."""


class GoalSave(ConfirmButton, GoalEditButton):
    """Saves the edited objective."""


class GoalCancel(DismissButton, GoalEditButton):
    """Leaves the objective as it was."""


class GoalEdit(Confirms, ShadedScreen, CenteredScreen, CoreEventReceiver, DismissibleScreen[None]):
    AUTO_FOCUS = "ChannelTextArea"

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
        self.editor = GoalEditor(project=project)
        self.editor.set_mention_candidates(candidates)

    def compose(self) -> ComposeResult:
        with GoalEditPanel():
            yield Static(
                "Edit objective · @ mentions · Tab completes · Enter saves",
                markup=False,
            )
            yield self.editor
            if self.goal.progress:
                yield GoalEditProgress(
                    f"Progress (read-only): {self.goal.progress}",
                    markup=False,
                )
            yield GoalEditError("", markup=False)
            with GoalEditButtons():
                yield GoalSave("Save", variant="primary")
                yield GoalCancel("Cancel")

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
        save_button = self.query_one(GoalSave)
        save_button.disabled = True
        try:
            await self.on_save(text.strip())
        except Refused as error:
            self.query_one(GoalEditError).update(str(error))
        else:
            self.dismiss()
        finally:
            self.saving = False
            save_button.disabled = False

    async def confirm(self) -> None:
        await self.save(self.editor.text)

    def dismiss_control(self) -> None:
        if not self.saving:
            super().dismiss_control()
