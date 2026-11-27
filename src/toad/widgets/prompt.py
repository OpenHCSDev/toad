from __future__ import annotations

import asyncio
import shlex
from abc import abstractmethod
from dataclasses import dataclass, replace
from pathlib import Path
from types import FunctionType
from agent_comms.projects.checkouts import Checkout
from typing import ClassVar, Self


from rich.text import Text as RichText
from textual import containers, events, getters, on, work
from textual._activation import PrimaryActivation
from textual.view import (
    AUTO,
    FocusWithinView,
    WidgetView,
)
from toad.settings_scope import SettingsReader
from toad.visuals.columns import Columns
from toad.widget_actions import Activates
from textual._paint_state import PaintState
from textual.actions import SkipAction
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets.text_area import EditingMode, VimMode
from toad.neovim_editing import NeovimUpdated
from textual.document._editing import EditingFailure
from textual.content import Content, Span
from textual.css.native import DeclaresTheme, NativeDeclaration, Percent, TextVariable, Variable
from textual.css.scalar import Scalar
from textual.css.styles import Styles
from textual.geometry import Spacing
from textual.reactive import Initialize, Required, var
from textual.strip import Strip
from textual.style import Style
from textual.widgets import Button, Label, OptionList, TextArea
from textual.widgets.option_list import Option, OptionListComponent
from textual.widgets.text_area import Selection, TextAreaComponent, TextAreaState
from ui_theme.scheme import ErrorColour, MutedColour, PrimaryColour, SecondaryColour

from toad import danger, messages
from toad.clipboard_image import PastesClipboard, read_clipboard, save_clipboard_png
from toad.agent_binding import NoAgentConnection
from toad.core import input_events
from toad.core_event_carrier import CoreEventReceiver
from toad.client.composer_pool import ComposerDraft, ComposerPoolHost, DraftEditorState
from toad.client.input_decision import InputDecision, InputAccepted, RefusalFeedback
from toad.client.message_files import AttachedFileChip, MessagePromptComposer
from toad.screens.file_picker import FileBrowserScreen, PathSearchScreen
from toad.client.prompt_composer import PromptComposer
from toad.client.prompt_stack import EditingModeBadge
from toad.client.queue_inspection import QueueDeliveryControls
from toad.native_style import (
    AutoHeight,
    AutoWidth,
    Borderless,
    ComposedWhenShown,
    EllipsisOverflow,
    FillWidth,
    HiddenOverflow,
    MutedText,
    NoMargin,
    NoPadding,
    NoWrap,
    OneRow,
    PointerCursor,
    RightMargin,
    RightPadding,
    ScreenOverlay,
    SecondaryText,
    SideMargin,
    SidePadding,
    SpacedAround,
    StartsHidden,
    TransparentBackground,
)
from toad.tone_paint import TonePaint
from toad.path_complete import AnyPath, CompletingEditor, DirectoriesOnly, FilesOnly, PathComplete
from toad.prompt_actions import MessageAction, PromptAction, SubmitInputAction, SubmitNowAction
from toad.app_node import ToadNode
from toad.prompt_cursor import (
    CommandText,
    HistoryCursor,
    NextHistoryCursor,
    PreviousHistoryCursor,
    PromptCursor,
)
from toad.client.prompt_composer import PromptSettingEffects
from toad.setting_widget import SettingVisibility
from toad.slash_command import SlashCommand
from toad.widget_actions import (
    Action, DismissibleControl, HiddenActions, LocalMethodKeys, NativeMethodKeys,
)
from toad.widgets.condensed_path import CondensedPath
from toad.widgets.highlighted_textarea import HighlightedTextArea
from toad.widgets.inline_message import span_content
from toad.widgets.model_switcher import ModelSwitcher
from toad.widgets.path_search import PathSearch
from toad.widgets.prompt_popup import CompletionPopup, InfoPopup, PaddedOptionRows, PromptPopup
from toad.answer import Ask
from toad.widgets.interactive_dialog import PromptDialog
from toad.widgets.question import PromptQuestion, Question
from toad.widgets.selection import ChangingText, InlineSelection, SelectionOptionList
from toad.widgets.slash_complete import SlashComplete

class ModeSwitcher(
    SpacedAround,
    DismissibleControl,
    CoreEventReceiver,
    Borderless,
    StartsHidden,
    NoPadding,
    AutoWidth,
    AutoHeight,
    ScreenOverlay,
    HiddenOverflow,
    PaddedOptionRows,
    SelectionOptionList,
):
    """Shown only while focused: it opens on focus and closes on blur."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.min_width = 12
        self.styles.max_width = 100
        self.styles.max_height = "50vh"
        self.styles.constrain_x = "inside"
        self.styles.constrain_y = "inflect"

    def watch_has_focus(self, has_focus: bool) -> None:
        super().watch_has_focus(has_focus)
        self.display = has_focus

    def _get_option_render(
        self, option: Option, style: Style, paint: PaintState
    ) -> list[Strip]:
        if (
            self.has_focus
            and self.highlighted is not None
            and option is self.options[self.highlighted]
        ):
            background = paint.background + self.app.colours.colour(
                PrimaryColour
            ).with_alpha(0.3).multiply_alpha(paint.opacity)
            base = paint.component_style(self, OptionListComponent.OPTION)
            style = replace(
                base, foreground=style.foreground, background=background, bold=False
            )
        return super()._get_option_render(option, style, paint)

    BINDING_GROUP_TITLE = "Mode switcher"

    @on(OptionList.OptionSelected)
    def on_option_selected(self, event: OptionList.OptionSelected):
        self.publish_core(input_events.ChangeMode(event.option_id))
        self.blur()

    def dismiss_control(self) -> None:
        self.blur()


class AgentInfo(
    SettingVisibility, WidgetView, PrimaryActivation, Label, setting="ui.agent_title"
):
    width = AUTO
    # Any agent state, connected or not, leaves the status line its room.
    max_width = Scalar.parse("60%")
    margin = Spacing(0, 1, 0, 0)

    @property
    def padding(self):
        return self.settings.ui.input.box.agent_info_padding

    @property
    def primary_activation(self):
        return self.query_ancestor(Prompt).on_agent_info_click


class SendNow(
    InlineSelection,
    Activates,
    SecondaryText,
    PointerCursor,
    Label,
    can_focus=True,
):


    def activate(self):
        self.post_message(messages.SendPromptNow())

class ModeInfo(
    InlineSelection,
    PrimaryActivation,
    SecondaryText,
    StartsHidden,
    SidePadding,
    NoMargin,
    PointerCursor,
    Label,
):
    """Shown while the agent has a current mode; hover underlines it."""

    native_theme = (NativeDeclaration.of(Styles.background, Variable(SecondaryColour.name), Percent(10)),)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.dock = "right"

    @property
    def primary_activation(self):
        return self.query_ancestor(Prompt).on_mode_info_click


class StatusLine(
    SettingVisibility,
    ChangingText,
    SecondaryText,
    SideMargin,
    AutoWidth,
    OneRow,
    NoWrap,
    EllipsisOverflow,
    Label,
    setting='ui.status_line',
):
    status: var[str | Content | RichText] = var("")

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.text_align = "right"

    def watch_status(self, status: str | Content | RichText) -> None:
        self.update(status)
        self.tooltip = status


class OpensQueue(Activates):
    """A prompt control whose activation opens the conversation's queue menu."""

    def activate(self) -> None:
        self.query_ancestor(Prompt).conversation.open_queue_menu()


class QueueSummary(
    OpensQueue,
    ChangingText,
    MutedText,
    StartsHidden,
    AutoHeight,
    TonePaint,
    Label,
    can_focus=True,
):
    """Shows queued messages and opens their delivery status when selected."""
    tone = PromptComposer.queue_tone


    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.max_height = PromptComposer.queue_summary_lines


class QueueHint(OpensQueue, SecondaryText, StartsHidden, SideMargin, AutoWidth, OneRow, NoWrap, Label,
                can_focus=True):
    """The held count in the info bar while the delivery preview is off; selecting it
    opens the queue, as the summary does."""


class DeliveryControls(TonePaint, QueueDeliveryControls, ComposedWhenShown, StartsHidden, OneRow, containers.HorizontalGroup):
    tone = PromptComposer.queue_tone
    """Shown while Enter queues behind a running turn; `QueueDeliveryControls` owns its text."""

    def shown_children(self) -> tuple[Widget, ...]:
        return Label(self.notice), SendNow(self.send_now_label)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.padding = (0, 0, 0, 1)


class EditingModeLabel(EditingModeBadge, AutoWidth, OneRow, SidePadding, NoWrap, Label):
    """The info bar's badge; `EditingModeBadge` decides its text."""

    def show_mode_label(self, label: str) -> None:
        self.update(label)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.dock = "right"
        self.styles.text_style = "reverse"


class DirectoryBounds(DeclaresTheme):
    """Where the shown directory lies relative to the project; each member owns its ink."""

    native_theme: ClassVar[tuple[NativeDeclaration, ...]] = (
        NativeDeclaration.of(Styles.color, TextVariable(SecondaryColour.name)),
    )

    @classmethod
    def entered(cls, prompt: Prompt) -> None:
        """Staying inside the project needs no notice."""


class InsideProject(DirectoryBounds):
    pass


class OutsideProject(DirectoryBounds):
    native_theme = (NativeDeclaration.of(Styles.color, TextVariable(ErrorColour.name)),)

    @classmethod
    def entered(cls, prompt: Prompt) -> None:
        prompt.post_message(
            messages.Flash(
                "You have navigated away from the project directory",
                style="error",
                duration=5,
            )
        )


class PromptPath(RightMargin, FillWidth, NoWrap, CondensedPath):
    """The info bar's directory, inked by where it lies relative to the project."""

    def native_declarations(self) -> tuple[NativeDeclaration, ...]:
        """The ink of the prompt's own directory bounds; the prompt owns that state."""
        return (*super().native_declarations(), *self.query_ancestor(Prompt).directory_bounds.declared_theme())


class InfoBar(
    SettingVisibility, WidgetView, containers.HorizontalGroup, setting="ui.info_bar"
):
    height = Scalar.parse("1")

    @property
    def margin(self):
        ui = self.settings.ui
        return ui.input.box.info_bar_margin(ui.footer)


class PromptLabel(SettingsReader, WidgetView, Label):
    width = AUTO

    @property
    def padding(self):
        return self.settings.ui.input.box.label_padding

    def render(self):
        return self.query_ancestor(Prompt).label_glyph()


class PromptContainer(TonePaint, SettingsReader, FocusWithinView, containers.HorizontalGroup):
    # The field typed into: the composer's input tone, a tier off the prompt and its band.
    tone = PromptComposer.input_tone

    @property
    def margin(self):
        return self.settings.ui.input.box.frame_margin

    @property
    def padding(self):
        return self.settings.ui.input.box.frame_padding

    @property
    def border(self):
        colour = self.app.colours.colour(PrimaryColour if self.has_focus_within else MutedColour)
        return self.settings.ui.input.box.frame_border(colour)

    @on(events.MouseDown)
    def on_mouse_down(self, event: events.MouseUp) -> None:
        self.query_ancestor(Prompt).focus()


class TextPrompt(containers.HorizontalGroup):
    """The label and editor; hidden while the prompt asks a question."""


class PromptSubmissionState:
    """A coalesced editor request owns its intent until its callback takes it."""

    def request(self, editor: PromptSubmission, action: SubmitInputAction) -> PromptSubmissionState:
        # Queue behind the widget's earlier input events, never a timer.
        if editor.call_later(editor.submit_pending):
            return PendingPromptSubmission(action, editor.editing_mode)
        return self

    async def submit(self, editor: PromptSubmission) -> None:
        pass


@dataclass(frozen=True)
class PendingPromptSubmission(PromptSubmissionState):
    action: SubmitInputAction
    mode: EditingMode

    def request(self, editor: PromptSubmission, action: SubmitInputAction) -> PromptSubmissionState:
        if self.mode is editor.editing_mode:
            action = self.action.coalesce(action)
        return PendingPromptSubmission(action, editor.editing_mode)

    async def submit(self, editor: PromptSubmission) -> None:
        await editor._submit(self.action, self.mode)


class PromptSubmission(HighlightedTextArea):
    """Admit model and local command submission through the current prompt."""

    def __init__(self) -> None:
        self._submission: PromptSubmissionState = PromptSubmissionState()
        super().__init__()

    def schedule_submission(self, action: SubmitInputAction) -> None:
        self._submission = self._submission.request(self, action)

    async def submit_pending(self) -> None:
        request, self._submission = self._submission, PromptSubmissionState()
        await request.submit(self)

    @abstractmethod
    async def _submit(self, action: SubmitInputAction, mode: EditingMode) -> None: ...


class PromptTextArea(
    RefusalFeedback,
    CompletingEditor,
    PastesClipboard,
    RightPadding,
    CoreEventReceiver,
    LocalMethodKeys,
    TransparentBackground,
    Borderless,
    AutoHeight,
    PromptSubmission,
    ToadNode,
    actions=(PromptAction,),
):
    HELP = """\
## Prompt

Talk to your agent in natural language.
See on-screen instructions for details.

- Be simple
- Be direct
- Nothing fancy
"""

    BINDING_GROUP_TITLE = "Prompt"

    native_components = {
        TextAreaComponent.PLACEHOLDER: (NativeDeclaration.of(Styles.color, TextVariable(MutedColour.name)),),
    }

    auto_completes: var[list[Option]] = var(list)
    shell_mode = var(False, bindings=True)
    path_complete: var[PathComplete] = var(Initialize(lambda obj: PathComplete()))
    suggestions: var[list[str] | None] = var(None)
    suggestions_index: var[int] = var(0)

    project_path = var[Checkout](Required())
    working_directory = var("")

    slash_commands: var[list[SlashCommand]] = var([])

    def __init__(self, *, prompt: Prompt) -> None:
        self.input_cursor = PromptCursor(self)
        super().__init__()
        # The composer that built this editor owns its turns, popups and modes.
        self.prompt = prompt
        self.editing_mode_label = EditingModeLabel("", markup=False)
        self.set_reactive(TextArea.editing_mode, prompt.initial_editing_mode)
        self.set_reactive(PromptTextArea.project_path, prompt.project_path)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.max_height = f"{PromptComposer.maximum_editor_viewport_percent}vh"

    def refuse_input(self, message: str) -> None:
        self.app.bell()
        self.post_message(messages.Flash(message, "error"))

    @property
    def can_enter_shell(self) -> bool:
        return self.submission_allowed and not self.text and not self.shell_mode

    def watch_slash_commands(self, slash_commands: list[SlashCommand]) -> None:
        self._clear_caches()
        self.notify_style_update()
        self.refresh()

    def highlight_slash_command(self, text: str) -> Content:
        return span_content(CommandText.decode_input(text, self.slash_commands).highlight(), self.app.colours)

    def highlight_shell(self, text: str) -> Content:
        """Override shell highlighting with additional danger detection."""
        content = super().highlight_shell(text)

        if not self.app.settings.shell.warn_dangerous:
            return content


        styles = danger.DangerStyles("bold $error", "bold reverse $error")
        spans = tuple(
            Span(*atom.span, style)
            for atom in danger.analyze(
                str(self.project_path.path), self.working_directory, content.plain
            )
            if (style := atom.level.highlight(styles))
        )
        content = content.add_spans(spans)
        return content

    @on(events.Mount)
    def on_mount(self) -> None:
        self.highlight_cursor_line = False
        self.hide_suggestion_on_blur = False
        self.editing_mode.attach(self)
        self.apply_keyboard_profile()
        self.call_after_refresh(lambda: self.show_editing_mode(self.editing_mode))

    def show_editing_mode(self, mode: EditingMode) -> None:
        """The editor owns its label before either widget is mounted."""
        if self.is_mounted:
            self.editing_mode_label.present_editing_mode(mode, self.has_focus)

    def watch_has_focus(self, focus: bool) -> None:
        self.show_editing_mode(self.editing_mode)

    def apply_keyboard_profile(self) -> None:
        self.call_later(self._apply_keyboard_profile)

    async def _apply_keyboard_profile(self) -> None:
        mode = self.screen.key_mode
        if self.key_mode is not mode:
            await self.switch_editing_mode(mode())

    @on(NeovimUpdated)
    async def on_neovim_updated(self, event: NeovimUpdated) -> None:
        event.stop()
        event.owner.paint(self)
        # A requested profile can outlive a refused transfer while RPC is pending.
        # The existing completion update retries from the saved preference.
        await self._apply_keyboard_profile()

    @property
    def submission_allowed(self) -> bool:
        return (
            self.editing_mode.accepts_text
            and not self.prompt.active_popup
        )

    def leave_modal_editor(self) -> None:

        self.prompt.conversation.window.focus(scroll_visible=False)

    def clear_suggestions(self) -> None:
        self.suggestions = None
        self.suggestion = ""

    def _paste_clipboard_text(self, text: str) -> None:
        # A fresh Paste event posted directly here would bubble to App and be
        # forwarded back to the focused TextArea, inserting it a second time.
        self.editing_mode.paste(self, text)

    @work(group='clipboard-paste', exclusive=True)
    async def paste_clipboard(self) -> None:
        if self.read_only:
            return
        try:
            content = await read_clipboard()
            if self.is_attached:
                await content.paste_into(self)
        except (OSError, ValueError, TimeoutError) as error:
            self.app.show_error(error, 'Paste failed')

    async def attach_png(self, data: bytes) -> None:
        if self.shell_mode:
            self.notify('Leave shell mode to attach an image to a message.', title='Image attachment', severity='warning')
            return
        if (reference := await self.prompt.png_pasted(data)):
            self._paste_clipboard_text(reference)
            self.notify(f'PNG attached ({len(data):,} bytes). Enter sends it with your prompt.', title='Image attachment')

    async def paste_clipboard_text(self) -> None:
        text = (await self.app.clipboard_transport.paste(self.app)).text
        if text:
            self._paste_clipboard_text(text)
        else:
            self.notify('No text or supported image in the clipboard', title='Paste')

    async def tab_complete(self) -> None:
        if not self.editing_mode.accepts_text or not self.shell_mode:
            return
        prompt = self.prompt
        if not self.cursor_at_end_of_text:
            return
        _cursor_row, cursor_column = prompt.prompt_text_area.selection.end
        pre_complete = self.text[:cursor_column]
        post_complete = self.text[cursor_column:]
        shlex_tokens = shlex.split(pre_complete)
        if not shlex_tokens:
            return
        command = shlex_tokens[0]
        shell = self.app.settings.shell
        kinds = (DirectoriesOnly() if command in shell.directory_commands.splitlines()
                 else FilesOnly() if command in shell.file_commands.splitlines() else AnyPath())
        working_directory = Path(prompt.working_directory)
        completion = await self.path_complete(working_directory, shlex_tokens[-1], kinds=kinds)
        completion.apply(self, working_directory, shlex_tokens, post_complete)

    def replace_text(self, text: str) -> None:
        self.clear()
        self.insert(text)
        self.clear_suggestions()

    def offer(self, options: list[str]) -> None:
        if not options:
            self.clear_suggestions()
        elif options != self.suggestions:
            self.suggestions = options
            self.suggestions_index = 0
            self.suggestion = options[0]
        else:
            self.suggestions_index = (self.suggestions_index + 1) % len(options)
            self.suggestion = options[self.suggestions_index]

    async def _submit(self, action: SubmitInputAction, mode: EditingMode) -> None:
        """A refused or superseded transfer consumes no text and retains no intent."""
        if mode is not self.editing_mode:
            return
        try:
            if not await mode.flush(self):
                return
        except EditingFailure:
            return  # The engine already reported its failure; never submit stale text.
        if mode is not self.editing_mode:
            return
        if not self.has_focus or not self.submission_allowed:
            return
        input_text = CommandText.decode_input(self.text, self.slash_commands)
        if input_text.requires_agent:
            decision = self.prompt.input_decision
            decision.announce(self)
            if not decision.allows:
                return
        if self.suggestion:
            if " " not in self.text:
                self.insert(self.suggestion + " ")
            else:
                prompt = self.prompt
                last_token = shlex.split(self.text + self.suggestion)[-1]
                last_token_path = Path(prompt.working_directory) / last_token
                if last_token_path.is_dir():
                    self.insert(self.suggestion)
                else:
                    self.insert(self.suggestion + " ")
                self.suggestion = ""
            return
        shell = self.shell_mode
        text = self.text
        self.clear()
        self.publish_core(action.submission_event(text, shell, self.prompt.take_files()))
        if shell:
            self.prompt.shell_mode = False

    def before_engine_input(self, action: FunctionType) -> bool:
        return HistoryCursor.try_input(self, action)

    def action_cursor_up(self, select: bool = False):
        PreviousHistoryCursor.move(self, select)

    def action_cursor_down(self, select: bool = False):
        NextHistoryCursor.move(self, select)

    def action_delete_left(self) -> None:
        if not self.editing_mode.accepts_text:
            return super().action_delete_left()
        selection = self.selection
        if selection.start == selection.end and self.selection.end == (0, 0):
            self.prompt.shell_mode = False
            return
        return super().action_delete_left()

    def action_cursor_line_end(self, select: bool = False) -> None:
        """Move the cursor to the end of the line."""
        if not self.editing_mode.accepts_text:
            return super().action_cursor_line_end(select)
        if not self._has_cursor:
            self.scroll_end()
            return
        location = self.get_cursor_line_end_location()
        if location == self.cursor_location:
            # If the cursor is already at the end, then we assume the user wants to
            # scroll the conversation to the end

            self.prompt.conversation.jump_to_latest()
        else:
            self.move_cursor(location, select=select)

    def watch_selection(
        self, previous_selection: Selection, selection: Selection
    ) -> None:
        if self.is_mounted:
            self.input_cursor.changed(previous_selection, selection)


class MessageTextArea(PromptTextArea, actions=(MessageAction,)):
    @property
    def can_enter_shell(self) -> bool:
        return False


class PromptFrameAction(Action, affix="Action"):
    """Keys the prompt frame answers, whether or not its editor exists yet."""


class EnterInsertAction(PromptFrameAction):
    """Show the latest prompt, ready for text entry."""

    title = "Focus prompt"
    keys = {VimMode: ("i",)}

    def apply(self, prompt: Prompt) -> None:
        prompt.enter_insert()


@dataclass(frozen=True)
class TextAreaDraftState(DraftEditorState):
    """Captured Textual `TextAreaState` (document, history, selection, and live `EditingMode`
    such as an embedded `NeovimEditing` buffer) retained while a pooled `Prompt` serves
    another tab."""

    state: TextAreaState

    def restore_into(self, composer: Prompt, host: ComposerPoolHost, text: str) -> None:
        editor = composer.prompt_text_area
        state = self.state
        previous_mode = editor.editing_mode
        editor._languages = {language.name: language for language in state.languages}
        editor.set_reactive(TextArea.language, state.language)
        editor.history = state.history
        editor._highlight_query = state.highlight_query
        editor.set_document(state.document)
        editor.paint_selection(state.selection)
        editor.editing_mode = state.editing_mode
        if previous_mode is state.editing_mode:
            state.editing_mode.attach(editor)
            editor.show_editing_mode(state.editing_mode)
        editor.record_cursor_width()
        editor.call_after_refresh(
            editor.scroll_to,
            x=state.scroll_x,
            y=state.scroll_y,
            animate=False,
            immediate=True,
        )
        editor.post_message(editor.Changed(editor).set_sender(editor))
        editor.update_suggestion()

    def discard(self) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        asyncio.ensure_future(self.state.editing_mode.close())


class Prompt(NativeMethodKeys, HiddenActions, DismissibleControl, PromptSettingEffects, TonePaint,
             containers.VerticalGroup, ToadNode, PromptComposer, actions=(PromptFrameAction,)):
    """The Textual composer; `PromptComposer` owns its submissions, queue, glyph and draft
    decisions, shared with Qt's `Composer`."""
    # `TonePaint` comes first in the bases, so its `tone` would hide the composer's own.
    tone = PromptComposer.area_tone


    TEXT_AREA_CLASS = PromptTextArea

    prompt_container = getters.query_one(PromptContainer)
    prompt_text_area = getters.query_one(PromptTextArea)
    prompt_label = getters.query_one(PromptLabel)
    editing_mode_label = getters.query_one(EditingModeLabel)
    path_search = getters.query_one(PathSearch)
    slash_complete = getters.query_one(SlashComplete)
    question = getters.query_one(Question)
    interactive_dialog = getters.query_one(PromptDialog)
    mode_switcher = getters.query_one(ModeSwitcher)
    model_switcher = getters.query_one(ModelSwitcher)

    slash_commands: var[list[SlashCommand]] = var(list)
    shell_mode = var(False)
    project_path = var[Checkout](Required(), init=False)
    working_directory = var("")
    display_directory = var("")
    directory_bounds: var[type[DirectoryBounds]] = var(lambda: InsideProject, init=False)
    agent_info = var(Content(""))
    _ask: var[Ask | None] = var(None)
    agent_binding = var(NoAgentConnection)
    model_history_scope = var("")
    status: var[str | Content | RichText] = var("")

    def __init__(
        self,
        *,
        project: Checkout,
        disabled: bool = False,
        submissions=None,
    ):
        super().__init__(disabled=disabled)
        self.set_reactive(Prompt.project_path, project)
        self.ask_queue: list[Ask] = []
        self.initial_editing_mode: EditingMode = EditingMode()
        self.submissions = submissions
        self._bound_host: ComposerPoolHost | None = None

    # ---- RebindableComposer: freeze draft on detach and rebind to another tab ----

    def pool_alive(self) -> bool:
        return self.is_mounted and self.is_attached and not self.is_leaving and not self._closing

    def _clear_conversation_watches(self, previous_host: object) -> None:
        sources = self.__dict__.get("_reactive_watch_sources")
        if sources is None or previous_host not in sources:
            return
        watched_attrs = sources.pop(previous_host)
        watchers = previous_host.__dict__.get("__watchers")
        if not watchers:
            return
        for attr in watched_attrs:
            if attr in watchers:
                watchers[attr] = [(node, cb) for node, cb in watchers[attr] if node is not self]

    def _bind_conversation_reactives(self, host: ComposerPoolHost) -> None:
        if self._bound_host is not None:
            self._clear_conversation_watches(self._bound_host)
        self._bound_host = host
        for attr in ("project_path", "working_directory", "agent_info", "agent_binding",
                     "model_history_scope", "status"):
            def _make_setter(name: str):
                def _setter(value: object) -> None:
                    setattr(self, name, value)
                return _setter
            self.watch(host, attr, _make_setter(attr), init=True)

    def capture_composer_draft(self) -> ComposerDraft:
        if (popup := self.active_popup) is not None:
            popup.dismiss()
        editor = self.prompt_text_area
        return ComposerDraft(
            text=editor.text,
            read_only_reason=str(editor.tooltip or "") if editor.disabled else "",
            commands=tuple(self.slash_commands),
            shell_mode=self.shell_mode,
            editor_state=TextAreaDraftState(editor.capture_editor_state()),
        )

    def reset_editor_draft(self, host: ComposerPoolHost, text: str) -> None:
        """Initialize the pooled `PromptTextArea` for a tab with no prior captured state.

        Never calls `editor.load_text()` or `editor.move_cursor()` before replacing
        `editing_mode`, because the previous tab's captured `NeovimEditing` buffer is
        still owned by that tab's `ComposerDraft`."""
        editor = self.prompt_text_area
        editor.history.clear()
        editor._set_document(text, editor.language)
        editor.paint_selection(Selection.cursor((0, 0)))
        editor.editing_mode = host.screen.key_mode()
        editor.post_message(editor.Changed(editor).set_sender(editor))
        editor.update_suggestion()

    def rebind_toolkit_conversation(self, host: ComposerPoolHost, draft: ComposerDraft) -> None:
        self.submissions = host.submissions
        self._bind_conversation_reactives(host)
        self.slash_commands = list(draft.commands)
        self.shell_mode = draft.shell_mode
        draft.editor_state.restore_into(self, host, draft.text)
        editor = self.prompt_text_area
        editor.disabled = bool(draft.read_only_reason)
        editor.tooltip = draft.read_only_reason or None
        self.sync_configuration()
        self.sync_session()

    @property
    def input_decision(self) -> InputDecision:
        return InputAccepted() if self.shell_mode else super().input_decision

    @property
    def text(self) -> str:
        return self.prompt_text_area.text

    @text.setter
    def text(self, text: str) -> None:
        editor = self.prompt_text_area
        editor.text = text
        editor.editing_mode.move_to_end(editor)

    @property
    def supports_completion(self) -> bool:
        """This composer owns whether its current input mode admits completion."""
        return not self.shell_mode and self.prompt_text_area.editing_mode.accepts_text

    @property
    def active_popup(self) -> PromptPopup | None:
        return next((popup for popup in self.query(PromptPopup) if popup.is_open), None)

    async def png_pasted(self, data: bytes) -> str:
        """What a pasted image leaves in the text. A prompt goes to an agent that reads files
        on this machine, so the image is kept here and the text names its path."""
        path = await asyncio.to_thread(save_clipboard_png, data)
        reference = f'@"{path}"' if any((char.isspace() for char in str(path))) else f'@{path}'
        return ' ' + reference + ' '

    def append_to_draft(self, suffix: str) -> None:
        """An edit of the retained document, between two checkpoints of its undo history."""
        editor = self.prompt_text_area
        editor.history.checkpoint()
        editor.insert(suffix, editor.document.end, maintain_selection_offset=True)
        editor.history.checkpoint()

    def show_failure(self, text: str) -> None:
        """Where this prompt's conversation tells a send failure."""
        self.conversation.show_send_failure(text)

    def watch_agent_binding(self) -> None:
        if self.is_mounted:
            self.sync_configuration()
            self.sync_session()

    def sync_configuration(self) -> None:
        """Render the original operational owners; no accepted selection lives here."""
        agent = self.agent_binding
        mode = agent.current_mode
        info = self.query_one(ModeInfo)
        info.display = mode is not None
        info.update(mode.name if mode is not None else "")
        info.tooltip = (
            Content.from_markup(
                "[b]$description[/]\n\n[dim](click to open mode switcher)",
                description=mode.description or mode.name,
            )
            if mode is not None
            else None
        )
        model = agent.configuration.model.selected
        agent_info = self.query_one(AgentInfo)
        agent_info.styles.pointer = "pointer" if model is not None else "default"
        agent_info.tooltip = (
            Content.from_markup(
                "[b]$description[/]\n\n[dim](click to search models)",
                description=model.description or model.value,
            )
            if model is not None
            else None
        )
        self.update_modes()
        self.model_switcher.configuration_changed()

    def ask(self, ask: Ask) -> None:
        """Replace the textarea prompt with a menu of options.

        Args:
            ask: An `Ask` instance which contains a question and responses.
        """
        self.ask_queue.append(ask)
        if self._ask is None:
            self._ask = self.ask_queue.pop(0)

    def remove_ask(self, ask: Ask) -> None:
        """Retire one exact request after its controller has stopped waiting."""
        if self._ask is ask:
            self._ask = self.ask_queue.pop(0) if self.ask_queue else None
        else:
            self.ask_queue = [
                pending for pending in self.ask_queue if pending is not ask
            ]

    def open_dialog(self, spec, callback=None) -> None:
        """Replace the text editor with a structured interactive dialog until answered."""
        def _done(outcome) -> None:
            self.query_one(TextPrompt).display = self._ask is None
            self.app.input_attention.release(self.interactive_dialog)
            self.refresh(layout=True)
            if self._ask is None and self.is_mounted:
                self.prompt_text_area.focus()
            if callback is not None:
                callback(outcome)

        self.query_one(TextPrompt).display = False
        self.app.input_attention.require(self.interactive_dialog)
        self.interactive_dialog.open_dialog(spec, _done)
        self.refresh(layout=True)

    def remove_dialog(self, spec) -> None:
        """Retire `spec` if it is still the active dialog."""
        if self.interactive_dialog.dialog_spec is spec:
            self.interactive_dialog.withdraw_dialog(spec)
            self.query_one(TextPrompt).display = self._ask is None
            self.app.input_attention.release(self.interactive_dialog)
            self.refresh(layout=True)
            if self._ask is None and self.is_mounted:
                self.prompt_text_area.focus()

    @on(events.Click, "ModeInfo")
    def on_mode_info_click(self):
        self.mode_switcher.focus()

    @on(events.Click, "AgentInfo")
    def on_agent_info_click(self):
        self.model_switcher.focus()

    def update_modes(self) -> None:

        agent = self.agent_binding
        mode_list = sorted(agent.available_modes, key=lambda mode: mode.name.lower())
        current = agent.current_mode
        columns = Columns("auto", "auto", "flex")
        for mode in mode_list:
            columns.add_row(
                Content.styled("✔", "$text-success") if mode is current else "",
                Content.from_markup("[bold]$mode[/]", mode=mode.name),
                Content.styled(mode.description or "", "dim"),
            )
        self.mode_switcher.set_options(
            [Option(row, id=mode.value) for row, mode in zip(columns, mode_list)]
        )
        if current is not None:
            self.mode_switcher.highlighted = self.mode_switcher.get_option_index(
                current.value
            )

    def sync_turn(self) -> None:
        if not self.is_mounted:
            return
        editor = self.prompt_text_area
        self.query_one(DeliveryControls).show(self.shows_delivery_preview and SubmitNowAction().available(editor))
        editor.refresh_bindings()

        self.conversation.queue_controls_changed()

    def sync_queue(self) -> None:
        """A queue change moves the turn's controls and the summary; the agent it talks to is unchanged."""
        if self.is_mounted:
            self.sync_turn()
            self._update_queue_summary()

    @on(events.Mount)
    def on_mount(self) -> None:
        self.sync_configuration()
        self.sync_session()
        self.call_after_refresh(self.sync_queue)

    def _update_queue_summary(self) -> None:
        text = self.queue_summary
        summary = self.query_one(QueueSummary)
        summary.display = bool(text)
        summary.tooltip = "Show queued messages and delivery status."
        summary.update(Content(text))
        hint = self.queue_hint
        held = self.query_one(QueueHint)
        held.display = bool(hint)
        held.update(Content(hint))

    @on(messages.SendPromptNow)
    async def on_send_prompt_now(self, event):
        event.stop()
        # Widget.focus() defers its focus change to the screen queue. Submission
        # can overtake it and fail the TextArea's has_focus guard after a click.
        self.screen.set_focus(self.prompt_text_area)
        await self.prompt_text_area.run_action("submit_now")

    def sync_session(self) -> None:
        if not self.is_mounted:
            return
        self.watch_agent_info(self.agent_info)
        self.sync_turn()

    def watch_agent_info(self, agent_info: Content) -> None:
        if not self.is_mounted:
            return
        self.query_one(AgentInfo).update(self.input_decision.agent_info(agent_info, Content))

    def watch_shell_mode(self) -> None:
        self.update_prompt()
        self.prompt_container.refresh_paint()
        self.watch_working_directory(self.working_directory)

    def compute_display_directory(self) -> str:
        return self.working_directory if self.shell_mode else str(self.project_path.path)

    def watch_working_directory(self, working_directory: str) -> None:
        if not working_directory:
            return
        self.directory_bounds = (
            OutsideProject
            if self.shell_mode and not Path(working_directory).is_relative_to(self.project_path.path)
            else InsideProject
        )

    def watch_directory_bounds(self, bounds: type[DirectoryBounds]) -> None:
        bounds.entered(self)
        self.query_one(PromptPath).update_node_styles()

    @on(events.Unmount)
    def on_unmount(self) -> None:
        self.app.input_attention.release(self)

    def watch__ask(self, ask: Ask | None) -> None:
        self.question.display = ask is not None
        self.query_one(TextPrompt).display = ask is None
        self.refresh(layout=True)
        if ask is None:
            self.app.input_attention.release(self)
            self.prompt_text_area.focus()
        else:
            self.app.input_attention.require(self)
            self.question.update(ask)
            self.question.focus()

    def place_input_box(self) -> None:
        """Prompt parts read their room from the input box setting when laid out."""
        for part in self.walk_children():
            part.refresh(layout=True)
        self.refresh(layout=True)

    def update_prompt(self):
        editor = self.prompt_text_area
        shell = self.shell_mode
        editor.placeholder = (
            Content.from_markup(
                "Enter shell command\t[r]▌esc▐[/r] prompt mode"
            ).expand_tabs(8)
            if shell
            else self.settings.ui.input.placeholder
        )
        editor.highlight_language = "shell" if shell else "markdown"
        self.prompt_label.refresh()

    def enter_insert(self) -> None:
        """Vim `i`: ready the prompt for text entry, where the reader already is.

        Typing is not reading: somebody scrolled up to quote or check something and
        then pressed `i` to answer it, so this keeps their place instead of jumping
        the transcript to the latest message under them.

        Textual composes the editor before it marks the prompt mounted, so a key
        pressed while a tab is still opening has no editor to act on yet.
        """
        if not self.is_mounted:
            return
        self.prompt_text_area.editing_mode.enter_text(self.prompt_text_area)
        self.conversation.focus_prompt(scroll_end=False)

    @property
    def typing_target(self) -> Widget | None:
        """The control typed text belongs to, or None while Textual is still composing this prompt.

        `question` and `prompt_text_area` are lazy queries, so asking one before the children
        exist raised `NoMatches: No nodes match 'Question' on Prompt()` out of
        `Conversation.initialize_view` while a tab was opening. Whether the controls exist yet
        is this prompt's own fact: `enter_insert` already answers it with `is_mounted`, and the
        callers below act on the same answer instead of querying a prompt that has no children.
        """
        if not self.is_mounted:
            return None
        if self.interactive_dialog.display:
            return self.interactive_dialog
        return self.question if self.question.display else self.prompt_text_area

    def focus(self, scroll_visible: bool = True) -> Self:
        """Focus the control typed text belongs to; a prompt still composing has none."""
        target = self.typing_target
        if target is not None:
            target.focus(scroll_visible=scroll_visible)
        return self

    def append(self, text: str) -> None:
        self.query_one(HighlightedTextArea).insert(
            text, maintain_selection_offset=False
        )

    def project_directory_updated(self) -> None:
        """Called when there may be new files."""
        self.path_search.invalidate_paths()

    @on(TextArea.Changed)
    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self.update_prompt()

    @on(Question.Answer)
    def on_question_answer(self, event: Question.Answer) -> None:
        """An old prompt must not select an option on a successor request."""
        event.stop()
        ask = self._ask
        if ask is None or event.ask is not ask:
            return
        if (callback := ask.callback) is not None:
            callback(event.answer)
        self.set_timer(0.3, lambda: self.remove_ask(ask))

    def suggest(self, suggestion: str) -> None:
        if suggestion.startswith(self.text) and self.text != suggestion:
            self.prompt_text_area.suggestion = suggestion[len(self.text) :]

    def label_glyph(self) -> Content:
        return Content.styled(
            self.prompt_symbol(self.text, self.shell_mode),
            "$text-primary" if self.shell_mode else "$text-secondary",
        )

    def compose_completions(self) -> ComposeResult:
        for kind in CompletionPopup.members():
            if (popup := kind.for_prompt(self)) is not None:
                yield popup

    def compose_delivery_controls(self) -> ComposeResult:
        yield QueueSummary("", markup=False)
        yield DeliveryControls()

    def compose_info_popups(self) -> ComposeResult:
        for kind in InfoPopup.members():
            if (popup := kind.for_prompt(self)) is not None:
                yield popup

    def compose_agent_info(self) -> ComposeResult:
        yield AgentInfo()
        yield PromptPath().data_bind(path=Prompt.display_directory)

    def compose_mode_controls(self) -> ComposeResult:
        yield ModeSwitcher()
        yield ModeInfo("mode")

    def compose_attached(self) -> ComposeResult:
        """What the message being written carries; an agent prompt carries nothing."""
        return ()

    def compose(self) -> ComposeResult:
        yield from self.compose_completions()
        yield from self.compose_delivery_controls()
        yield from self.compose_attached()
        with PromptContainer():
            yield PromptQuestion()
            yield PromptDialog()
            with TextPrompt():
                yield PromptLabel(markup=False)
                editor = self.TEXT_AREA_CLASS(prompt=self).data_bind(
                    shell_mode=Prompt.shell_mode,
                    project_path=Prompt.project_path,
                    working_directory=Prompt.working_directory,
                    slash_commands=Prompt.slash_commands,
                )
                yield editor
        yield from self.compose_info_popups()
        with InfoBar():
            yield editor.editing_mode_label
            yield QueueHint("", markup=False)
            yield from self.compose_agent_info()
            yield StatusLine(markup=False).data_bind(status=Prompt.status)
            yield from self.compose_mode_controls()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return True

    def dismiss_control(self) -> None:
        if self.prompt_text_area.suggestion:
            self.prompt_text_area.suggestion = ""
            return
        if self.shell_mode:
            self.shell_mode = False
            return
        for popup in self.query(PromptPopup):
            if popup.is_open:
                popup.dismiss_control()
                return
        raise SkipAction()


class FileChip(AttachedFileChip, Button):
    """One attached file as Textual draws it; pressing it takes the file off the message."""

    def __init__(self, composer: MessagePromptComposer, position: int) -> None:
        self.show_file(composer, position)
        super().__init__(f"{self.caption} ✕", compact=True, tooltip="Remove from this message")

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.take_off()


class AttachedFiles(containers.HorizontalGroup):
    """The files the message being written carries, as chips above the text."""

    def show(self, composer: MessagePromptComposer) -> None:
        self.remove_children()
        self.mount_all(FileChip(composer, position) for position in range(len(composer.attached_files)))
        self.display = bool(composer.attached_files)


class MessagePrompt(MessagePromptComposer, Prompt):
    TEXT_AREA_CLASS = MessageTextArea

    attached = getters.query_one(AttachedFiles)

    def __init__(self, *, placeholder: str | None = None, **kwargs):
        self.simple_placeholder = placeholder
        super().__init__(**kwargs)

    @property
    def supports_completion(self) -> bool:
        return False

    def show_files_offered(self) -> None:
        """Attach's key is offered (`AttachFileAction.available`) only while the bus takes files."""
        self.refresh_bindings()

    def sync_configuration(self) -> None:
        pass

    def watch_agent_info(self, agent_info: Content) -> None:
        if self.is_mounted:
            self.update_prompt()

    def project_directory_updated(self) -> None:
        pass

    def update_prompt(self) -> None:
        self.prompt_text_area.placeholder = self.simple_placeholder or (
            f"Message {self.agent_info.plain or 'thread'}"
        )
        self.prompt_text_area.highlight_language = "markdown"
        self.prompt_label.refresh()

    def compose_info_popups(self) -> ComposeResult:
        return ()

    def compose_agent_info(self) -> ComposeResult:
        return ()

    def compose_mode_controls(self) -> ComposeResult:
        return ()

    def compose_completions(self) -> ComposeResult:
        if (popup := SlashComplete.for_prompt(self)) is not None:
            yield popup

    def compose_attached(self) -> ComposeResult:
        files = AttachedFiles()
        files.display = False
        yield files

    def pick_in_window(self) -> None:
        """A terminal's window is a file browser over the whole disk, opened at the project."""
        self.app.push_screen(FileBrowserScreen(self, self.project_path.path))

    def pick_by_path_search(self) -> None:
        self.app.push_screen(PathSearchScreen(self, self.project_path.path))

    def show_attached(self) -> None:
        self.attached.show(self)

    def capture_composer_draft(self) -> ComposerDraft:
        return replace(
            super().capture_composer_draft(),
            attached_files=tuple(self.attached_files),
            takes_files=self.takes_files,
            placeholder=self.simple_placeholder or "",
        )

    def rebind_conversation(self, host: ComposerPoolHost, draft: ComposerDraft) -> None:
        self.simple_placeholder = draft.placeholder or host.composer_placeholder or None
        super().rebind_conversation(host, draft)
        self.attached_files = tuple(draft.attached_files)
        self.takes_files = draft.takes_files
        self.show_files_offered()
        self.show_attached()
        self.update_prompt()


class MailboxPrompt(MessagePrompt):
    """A CLI thread's composer shows its project; Core's status line names the model, read-only."""

    def compose_agent_info(self) -> ComposeResult:
        yield PromptPath().data_bind(path=Prompt.display_directory)
