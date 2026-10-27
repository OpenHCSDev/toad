from __future__ import annotations

import asyncio
import shlex
from dataclasses import replace
from pathlib import Path
from agent_comms.repo import Checkout
from typing import TYPE_CHECKING, ClassVar, Literal, Self

from agent_comms.acp_extension import QueueItem

from rich.cells import cell_len
from rich.text import Text as RichText
from textual import containers, events, getters, on, work
from textual._activation import PrimaryActivation
from toad.widget_actions import Activates
from textual._paint_state import PaintState
from textual.actions import SkipAction
from textual.app import ComposeResult
from textual.binding import Binding, ModeBinding
from textual.widgets.text_area import VimMode
from textual.content import Content, Span
from textual.css.scalar import Scalar
from textual.geometry import Size, Spacing
from textual.reactive import Initialize, Required, var
from textual.strip import Strip
from textual.style import Style
from textual.widgets import Label, OptionList, TextArea
from textual.widgets.option_list import Option
from textual.widgets.text_area import Selection
from ui_theme.scheme import PrimaryColour, PromptToneColour

from toad import messages
from toad.agent_binding import NoAgentConnection
from toad.conversation_turn import ConversationTurn
from toad.core import input_events
from toad.core.input_events import UserInputSubmitted
from toad.core_event_carrier import CoreEventReceiver
from toad.tone_paint import TonePaint
from toad.path_complete import PathComplete
from toad.prompt_actions import PromptAction, SubmitNowAction
from toad.prompt_cursor import (
    CommandText,
    NextHistoryCursor,
    PreviousHistoryCursor,
    PromptCursor,
)
from toad.setting_widget import SettingVisibility
from toad.slash_command import SlashCommand
from toad.widget_actions import (
    DeclaredWidgetActions, DismissibleControl, HiddenActions, NativeMethodKeys,
)
from toad.widget_view import AUTO, WidgetView
from toad.widgets.condensed_path import CondensedPath
from toad.widgets.highlighted_textarea import HighlightedTextArea
from toad.widgets.model_switcher import ModelSwitcher
from toad.widgets.path_search import PathSearch
from toad.widgets.prompt_popup import CompletionPopup, InfoPopup, PromptPopup
from toad.widgets.question import Ask, Question
from toad.widgets.selection import ChangingText, InlineSelection, SelectionOptionList
from toad.widgets.slash_complete import SlashComplete

if TYPE_CHECKING:
    from toad.app import ToadApp


class ModeSwitcher(DismissibleControl, CoreEventReceiver, SelectionOptionList):
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
            base = paint.component_style(self, "option-list--option")
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
        return (
            super().padding
            if self.app.settings.ui.compact_input
            else Spacing(0, 1, 0, 1)
        )

    @property
    def primary_activation(self):
        return self.query_ancestor(Prompt).on_agent_info_click


class SendNow(InlineSelection, Activates, Label, can_focus=True):

    def activate(self):
        self.post_message(messages.SendPromptNow())

class ModeInfo(PrimaryActivation, Label):
    @property
    def primary_activation(self):
        return self.query_ancestor(Prompt).on_mode_info_click


class StatusLine(SettingVisibility, ChangingText, Label, setting="ui.status_line"):
    status: var[str | Content | RichText] = var("")

    def watch_status(self, status: str | Content | RichText) -> None:
        self.set_class(not bool(status), "-hidden")
        self.update(status)
        self.tooltip = status


class QueueSummary(Activates, ChangingText, Label, can_focus=True):
    """Shows the remote queue; activation reports available control support."""


    def activate(self) -> None:
        from toad.widgets.conversation import Conversation

        self.query_ancestor(Conversation).open_queue_menu()

class InfoBar(
    SettingVisibility, WidgetView, containers.HorizontalGroup, setting="ui.info_bar"
):
    height = Scalar.parse("1")

    @property
    def margin(self):
        ui = self.app.settings.ui
        space = 0 if ui.compact_input else int(ui.footer)
        return Spacing(0, space, 0, space)


class PromptLabel(WidgetView, Label):
    width = AUTO
    AI = Content.styled("❯", "$text-secondary")
    SHELL = Content.styled("$", "$text-primary")
    MULTILINE = Content.styled("☰", "$text-secondary")

    @property
    def padding(self):
        return Spacing(0, 1, 0, 0 if self.app.settings.ui.compact_input else 1)

    def render(self):
        return self.query_ancestor(Prompt).label_glyph()


class PromptContainer(WidgetView, containers.HorizontalGroup):
    def on_mouse_down(self, event: events.MouseUp) -> None:
        self.query_ancestor(Prompt).focus()


class PromptSubmission:
    """Admit model and local command submission through the current prompt."""

    def schedule_submission(self, *, immediate: bool = False) -> None:
        self._submit_immediate |= immediate
        # The callback is queued behind this widget's input events. Unlike a
        # timer, it preserves paste/typing order without adding a fixed latency.
        if not self._submit_pending:
            self._submit_pending = True
            self.call_later(self._submit)


class PromptTextArea(
    CoreEventReceiver, DeclaredWidgetActions, PromptSubmission, HighlightedTextArea,
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

    BINDINGS = [
        Binding("ctrl+v", "paste_clipboard", "Paste", priority=True, show=False),
        Binding("ctrl+j", "newline", "New line", priority=True, show=False),
        Binding(
            "shift+enter",
            "newline",
            "Line",
            key_display="⇧+⏎",
            tooltip="Insert a new line character",
        ),
        Binding(
            "tab",
            "tab_complete",
            "Complete",
            tooltip="Complete path (if possible)",
            priority=True,
            show=False,
        ),
    ]

    app: ToadApp

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
        self.set_reactive(PromptTextArea.project_path, prompt.project_path)
        self._submit_pending = False
        self._submit_immediate = False

    @property
    def agent_busy(self) -> bool:
        return self.prompt.agent_busy

    @property
    def agent_ready(self) -> bool:
        return self.shell_mode or self.prompt.agent_ready

    @property
    def can_enter_shell(self) -> bool:
        return self.submission_allowed and not self.text and not self.shell_mode

    def watch_slash_commands(self, slash_commands: list[SlashCommand]) -> None:
        self._clear_caches()
        self.notify_style_update()
        self.refresh()

    def highlight_slash_command(self, text: str) -> Content:
        return CommandText.decode_input(text, self.slash_commands).highlight()

    def highlight_shell(self, text: str) -> Content:
        """Override shell highlighting with additional danger detection."""
        content = super().highlight_shell(text)

        if not self.app.settings.shell.warn_dangerous:
            return content

        from toad import danger

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

    def on_mount(self) -> None:
        self.highlight_cursor_line = False
        self.hide_suggestion_on_blur = False
        self.apply_keyboard_profile()
        self.call_after_refresh(lambda: self.show_editing_mode(self.editing_mode))

    def show_editing_mode(self, mode) -> None:
        # The mode label is painted on the last text row, so a new label can move it.
        if self.is_mounted:
            self._refresh_size()
            self.refresh()

    @property
    def mode_label(self) -> Content:
        label = self.editing_mode.label
        styled = Content.styled(f" {label} ", "reverse") if label else Content()
        # Never wider than the box: at width 0 the label is empty and nothing wraps.
        return styled.truncate(self.content_size.width)

    @property
    def text_width(self) -> int:
        """Columns left for text on the row the mode label shares."""
        return self.content_size.width - self.mode_label.cell_length

    @property
    def mode_row_below(self) -> bool:
        """The last text row reaches the label, so the label takes the next row."""
        if not self.mode_label.cell_length:
            return False
        if not self.text and self.placeholder:
            rows = Content.from_text(self.placeholder, markup=False).wrap(self.content_size.width)
            last = rows[-1].cell_length if rows else 0
        else:
            sections = self.wrapped_document.get_sections(self.document.line_count - 1)
            last = cell_len(sections[-1]) if sections else 0
        # One cell stays free for the cursor resting after the text.
        return last + 1 > self.text_width

    def _refresh_size(self) -> None:
        super()._refresh_size()
        if self.mode_row_below:
            width, height = self.virtual_size
            self.virtual_size = Size(width, height + 1)

    def render_line(self, y: int, paint: PaintState) -> Strip:
        line = super().render_line(y, paint)
        label = self.mode_label
        if not label.cell_length or self.scroll_offset.y + y != self.virtual_size.height - 1:
            return line
        return Strip.join((
            line.crop_extend(0, self.text_width, paint.visual_style.rich_style),
            Strip(label.render_segments(paint.visual_style), label.cell_length),
        ))

    def apply_keyboard_profile(self) -> None:
        self.editing_mode = self.screen.key_mode()

    @property
    def submission_allowed(self) -> bool:
        return (
            self.editing_mode.accepts_text
            and not self.prompt.active_popup
        )

    def leave_modal_editor(self) -> None:
        from toad.widgets.conversation import Conversation

        self.query_ancestor(Conversation).window.focus(scroll_visible=False)

    def on_key(self, event: events.Key) -> None:
        if self.shell_mode and event.key == "tab":
            event.prevent_default()
        elif event.key != "escape":
            self.suggestions = None
            self.suggestion = ""

    def action_newline(self) -> None:
        self._replace_via_keyboard("\n", *self.selection)

    def _paste_clipboard_text(self, text: str) -> None:
        # A fresh Paste event posted directly here would bubble to App and be
        # forwarded back to the focused TextArea, inserting it a second time.
        self.editing_mode = self.editing_mode.pasted()
        if result := self._replace_via_keyboard(text, *self.selection):
            self.move_cursor(result.end_location)

    @work(group="clipboard-paste", exclusive=True)
    async def action_paste_clipboard(self) -> None:
        from toad.clipboard_image import read_clipboard_png, save_clipboard_png

        if self.read_only:
            return
        try:
            image = await read_clipboard_png()
            if not self.is_attached:
                return
            if image is not None:
                if self.shell_mode:
                    self.notify(
                        "Leave shell mode to attach an image to a message.",
                        title="Image attachment",
                        severity="warning",
                    )
                    return
                path = await asyncio.to_thread(save_clipboard_png, image)
                reference = (
                    f'@"{path}"'
                    if any(char.isspace() for char in str(path))
                    else f"@{path}"
                )
                self._paste_clipboard_text(" " + reference + " ")
                self.notify(
                    f"PNG attached ({len(image):,} bytes). Enter sends it with your prompt.",
                    title="Image attachment",
                )
                return
            text = (await self.app.clipboard_transport.paste(self.app)).text
            if text:
                self._paste_clipboard_text(text)
            else:
                self.notify(
                    "No text or supported image in the clipboard", title="Paste"
                )
        except (OSError, ValueError, TimeoutError) as error:
            self.app.show_error(error, "Paste failed")

    def _submit(self) -> None:
        self._submit_pending = False
        immediate, self._submit_immediate = self._submit_immediate, False
        if not self.has_focus or not self.submission_allowed:
            return
        input_text = CommandText.decode_input(self.text, self.slash_commands)
        local_command = not input_text.requires_agent
        if not self.agent_ready and not self.shell_mode and not local_command:
            self.app.bell()
            self.post_message(
                messages.Flash(
                    self.query_ancestor(
                        Prompt
                    ).operational_submissions.unavailable_reason,
                    "error",
                )
            )
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
        self.publish_core(UserInputSubmitted(text, shell, immediate=immediate))
        if shell:
            self.prompt.shell_mode = False

    def action_cursor_up(self, select: bool = False):
        PreviousHistoryCursor.move(self, select, super().action_cursor_up)

    def action_cursor_down(self, select: bool = False):
        NextHistoryCursor.move(self, select, super().action_cursor_down)

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
            from toad.widgets.conversation import Conversation

            self.query_ancestor(Conversation).jump_to_latest()
        else:
            self.move_cursor(location, select=select)

    async def action_tab_complete(self) -> None:
        if not self.editing_mode.accepts_text or not self.shell_mode:
            return

        import shlex

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

        exclude_node_type: Literal["file"] | Literal["dir"] | None = None
        if command in self.app.settings.shell.directory_commands.splitlines():
            exclude_node_type = "file"
        elif command in self.app.settings.shell.file_commands.splitlines():
            exclude_node_type = "dir"

        tab_complete, suggestions = await self.path_complete(
            Path(prompt.working_directory),
            shlex_tokens[-1],
            exclude_type=exclude_node_type,
        )

        if tab_complete is not None:
            shlex_tokens = shlex_tokens[:-1] + [shlex_tokens[-1] + tab_complete]
            path_component = Path(prompt.working_directory) / shlex_tokens[-1]
            if path_component.is_file():
                spaces = " "
            else:
                spaces = ""

            self.clear()
            self.insert(
                " ".join(token.replace(" ", "\\ ") for token in shlex_tokens)
                + post_complete
                + spaces
            )
            self.suggestions = None
        else:
            if suggestions != self.suggestions:
                self.suggestions = suggestions or None
                self.suggestions_index = 0
                if suggestions:
                    self.suggestion = suggestions[0]
            elif self.suggestions:
                self.suggestions_index = (self.suggestions_index + 1) % len(
                    self.suggestions
                )
                self.suggestion = self.suggestions[self.suggestions_index]

    def watch_selection(
        self, previous_selection: Selection, selection: Selection
    ) -> None:
        if self.is_mounted:
            self.input_cursor.changed(previous_selection, selection)


class MessageTextArea(PromptTextArea):
    @property
    def can_enter_shell(self) -> bool:
        return False


class Prompt(NativeMethodKeys, HiddenActions, DismissibleControl, TonePaint, containers.VerticalGroup):
    tone = PromptToneColour

    DEFAULT_CSS = """
    Prompt .queue-summary { display: none; height: auto; max-height: 3; color: $text-muted; }
    Prompt.-has-queue .queue-summary { display: block; }
    Prompt .delivery-controls { display: none; height: 1; padding-left: 1; }
    Prompt.-queue-mode .delivery-controls { display: block; }
    Prompt SendNow { color: $text-secondary; pointer: pointer; }
    """


    TEXT_AREA_CLASS = PromptTextArea

    prompt_container = getters.query_one(PromptContainer)
    prompt_text_area = getters.query_one(PromptTextArea)
    prompt_label = getters.query_one(PromptLabel)
    current_directory = getters.query_one(CondensedPath)
    path_search = getters.query_one(PathSearch)
    slash_complete = getters.query_one(SlashComplete)
    question = getters.query_one(Question)
    mode_switcher = getters.query_one(ModeSwitcher)
    model_switcher = getters.query_one(ModelSwitcher)

    slash_commands: var[list[SlashCommand]] = var(list)
    shell_mode = var(False)
    project_path = var[Checkout](Required(), init=False)
    working_directory = var("")
    display_directory = var("")
    agent_info = var(Content(""))
    _ask: var[Ask | None] = var(None)
    agent_binding = var(NoAgentConnection)
    model_history_scope = var("")
    status: var[str | Content | RichText] = var("")

    app: ToadApp

    def __init__(
        self,
        *,
        project: Checkout,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
        turns: ConversationTurn | None = None,
        submissions=None,
    ):
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self.set_reactive(Prompt.project_path, project)
        self.ask_queue: list[Ask] = []
        self.turns = turns
        self.submissions = submissions

    @property
    def agent_busy(self) -> bool:
        return self.turns.owner.busy if self.turns is not None else False

    @property
    def operational_submissions(self):
        if self.submissions is None:
            raise RuntimeError("Operational prompt requires its submission owner")
        return self.submissions

    @property
    def agent_ready(self) -> bool:
        return self.shell_mode or self.operational_submissions.ready

    @property
    def text(self) -> str:
        return self.prompt_text_area.text

    @text.setter
    def text(self, text: str) -> None:
        self.prompt_text_area.text = text
        self.prompt_text_area.selection = Selection.cursor(
            self.prompt_text_area.get_cursor_line_end_location()
        )

    @property
    def supports_completion(self) -> bool:
        """This composer owns whether its current input mode admits completion."""
        return not self.shell_mode and self.prompt_text_area.editing_mode.accepts_text

    @property
    def active_popup(self) -> PromptPopup | None:
        return next((popup for popup in self.query(PromptPopup) if popup.is_open), None)

    def restore_draft(self, text: str) -> None:
        """Recover local input as an edit of the retained document and undo history."""
        current = self.text
        if text and current != text and not current.endswith("\n\n" + text):
            editor = self.prompt_text_area
            editor.history.checkpoint()
            editor.insert(("\n\n" if current else "") + text,
                          editor.document.end, maintain_selection_offset=True)
            editor.history.checkpoint()

    def watch_agent_binding(self) -> None:
        if self.is_mounted:
            self.sync_configuration()
            self.sync_session()

    def sync_configuration(self) -> None:
        """Render the original operational owners; no accepted selection lives here."""
        agent = self.agent_binding
        mode = agent.current_mode
        self.set_class(mode is not None, "-has-mode")
        info = self.query_one(ModeInfo)
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
        self.set_class(model is not None, "-has-model")
        self.query_one(AgentInfo).tooltip = (
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

    @on(events.Click, "ModeInfo")
    def on_mode_info_click(self):
        self.mode_switcher.focus()

    @on(events.Click, "AgentInfo")
    def on_agent_info_click(self):
        if self.agent_binding.configuration.model.available:
            self.model_switcher.focus()

    def update_modes(self) -> None:
        from toad.visuals.columns import Columns

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
        self.set_class(SubmitNowAction().available(editor), "-queue-mode")
        editor.refresh_bindings()
        from toad.widgets.conversation import Conversation

        self.query_ancestor(Conversation).goal_bar._queue_separator_update()

    def sync_queue(self) -> None:
        if self.is_mounted:
            self.sync_session()
            self._update_queue_summary()

    def on_mount(self) -> None:
        self.sync_configuration()
        self.sync_session()
        self.call_after_refresh(self.sync_queue)

    def _update_queue_summary(self) -> None:
        submissions = self.operational_submissions
        projection = submissions.queue_projection
        queued = [row.preview for row in submissions.queued_inputs]
        restored = [row.preview for row in projection.restored]
        feedback = projection.feedback(self.agent_binding.presentation.queue_supported)
        delivering = [QueueItem.summarize(text) for text in submissions.delivering]
        self.set_class(bool(queued or restored or delivering or feedback), "-has-queue")
        parts: list[str] = []
        if feedback:
            parts.append(feedback)
        for label, texts, detail in (
            ("Submitting", delivering, ""),
            ("Queued", queued, ""),
            ("Restored", restored, ", read-only"),
        ):
            if texts:
                parts.append(
                    f"{label} ({len(texts)}{detail}): "
                    + " · ".join(texts[:3])
                )
        summary = self.query_one(".queue-summary", Label)
        summary.tooltip = "Submitting is an outstanding local request, not acceptance. Queued is the producer's accepted input, not consumption or completion. Restored rows are not local drafts."
        summary.update(Content(" | ".join(parts)))

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
        self.set_class(not self.agent_ready, "-not-ready")
        self.watch_agent_info(self.agent_info)
        self.sync_turn()

    def watch_agent_info(self, agent_info: Content) -> None:
        if not self.is_mounted:
            return
        if self.agent_ready:
            self.query_one(AgentInfo).update(agent_info)
        else:
            self.query_one(AgentInfo).update(
                self.operational_submissions.unavailable_reason
            )

    def watch_shell_mode(self) -> None:
        self.update_prompt()
        self.prompt_container.refresh_paint()
        self.watch_working_directory(self.working_directory)

    def compute_display_directory(self) -> str:
        return self.working_directory if self.shell_mode else str(self.project_path.path)

    def watch_working_directory(self, working_directory: str) -> None:
        if not working_directory:
            return
        out_of_bounds = self.shell_mode and not Path(working_directory).is_relative_to(
            self.project_path.path
        )
        if out_of_bounds and not self.has_class("-working-directory-out-of-bounds"):
            self.post_message(
                messages.Flash(
                    "You have navigated away from the project directory",
                    style="error",
                    duration=5,
                )
            )
        self.set_class(
            out_of_bounds,
            "-working-directory-out-of-bounds",
        )

    def on_unmount(self) -> None:
        self.app.terminal_attention.release(self)

    def watch__ask(self, ask: Ask | None) -> None:
        self.set_class(ask is not None, "-mode-ask")
        self.refresh(layout=True)
        if ask is None:
            self.app.terminal_attention.release(self)
            self.prompt_text_area.focus()
        else:
            self.app.terminal_attention.require(self)
            self.question.update(ask)
            self.question.focus()

    def update_prompt(self):
        editor = self.prompt_text_area
        shell = self.shell_mode
        editor.placeholder = (
            Content.from_markup(
                "Enter shell command\t[r]▌esc▐[/r] prompt mode"
            ).expand_tabs(8)
            if shell
            else ""
        )
        editor.highlight_language = "shell" if shell else "markdown"
        self.prompt_label.refresh()

    def enter_insert(self) -> None:
        """Vim `i`: show the latest prompt, ready for text entry.

        Textual composes the editor before it marks the prompt mounted, so a key
        pressed while a tab is still opening has no editor to act on yet.
        """
        if not self.is_mounted:
            return
        from toad.key_modes import VimInsert
        from toad.widgets.conversation import Conversation

        self.prompt_text_area.editing_mode = VimInsert()
        self.query_ancestor(Conversation).focus_prompt()

    MODE_BINDINGS = (
        ModeBinding("i", enter_insert, "Focus prompt", mode=VimMode, show=False),
    )

    def focus(self, scroll_visible: bool = True) -> Self:
        if self._ask is not None:
            self.question.focus(scroll_visible=scroll_visible)
        else:
            self.prompt_text_area.focus(scroll_visible=scroll_visible)
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
        if self.shell_mode:
            return PromptLabel.SHELL
        return (
            PromptLabel.MULTILINE
            if "\n" in self.text or "```" in self.text
            else PromptLabel.AI
        )

    def compose_completions(self) -> ComposeResult:
        for kind in CompletionPopup.members():
            if (popup := kind.for_prompt(self)) is not None:
                yield popup

    def compose_delivery_controls(self) -> ComposeResult:
        yield QueueSummary("", classes="queue-summary", markup=False)
        with containers.HorizontalGroup(classes="delivery-controls"):
            yield Label("Enter queues · ")
            yield SendNow("Send now (Ctrl+Enter / Ctrl+Y)")

    def compose_info_popups(self) -> ComposeResult:
        for kind in InfoPopup.members():
            if (popup := kind.for_prompt(self)) is not None:
                yield popup

    def compose_agent_info(self) -> ComposeResult:
        yield AgentInfo()
        yield CondensedPath().data_bind(path=Prompt.display_directory)

    def compose_mode_controls(self) -> ComposeResult:
        yield ModeSwitcher()
        yield ModeInfo("mode")

    def compose(self) -> ComposeResult:
        yield from self.compose_completions()
        yield from self.compose_delivery_controls()
        with PromptContainer(id="prompt-container"):
            yield Question()
            with containers.HorizontalGroup(id="text-prompt"):
                yield PromptLabel(id="prompt", markup=False)
                yield self.TEXT_AREA_CLASS(prompt=self).data_bind(
                    shell_mode=Prompt.shell_mode,
                    project_path=Prompt.project_path,
                    working_directory=Prompt.working_directory,
                    slash_commands=Prompt.slash_commands,
                )
        yield from self.compose_info_popups()
        with InfoBar(id="info-container"):
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


class MessagePrompt(Prompt):
    TEXT_AREA_CLASS = MessageTextArea

    def __init__(self, *, placeholder: str | None = None, **kwargs):
        self.simple_placeholder = placeholder
        super().__init__(**kwargs)

    @property
    def agent_ready(self) -> bool:
        return True

    @property
    def supports_completion(self) -> bool:
        return False

    def sync_turn(self) -> None:
        # Message composers have no delivery controls or operational turn.
        pass

    def sync_configuration(self) -> None:
        pass

    def _update_queue_summary(self) -> None:
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

    def label_glyph(self) -> Content:
        return PromptLabel.AI

    def compose_delivery_controls(self) -> ComposeResult:
        return ()

    def compose_info_popups(self) -> ComposeResult:
        return ()

    def compose_agent_info(self) -> ComposeResult:
        return ()

    def compose_mode_controls(self) -> ComposeResult:
        return ()

    def compose_completions(self) -> ComposeResult:
        if (popup := SlashComplete.for_prompt(self)) is not None:
            yield popup


class MailboxPrompt(MessagePrompt):
    """A CLI thread's composer shows its project; Core's status line names the model, read-only."""

    def compose_agent_info(self) -> ComposeResult:
        yield CondensedPath().data_bind(path=Prompt.display_directory)
