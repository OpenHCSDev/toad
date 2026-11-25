"""Channel mention completion uses model-provided members and mention syntax."""

from agent_comms.messaging.mentions import MentionCandidate
from textual import on
from textual.app import ComposeResult
from textual.widgets import OptionList, TextArea
from textual.widgets.option_list import Option
from textual.widgets.text_area import Selection

from toad.client.mention_completion import MentionCompletion, MentionEditor
from toad.native_style import AutoHeight, SpacedBelow
from toad.widgets.prompt import MessagePrompt, MessageTextArea
from toad.widgets.selection import SelectionOptionList


class MentionList(SpacedBelow, AutoHeight, SelectionOptionList):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.max_height = 7


class ChannelTextArea(MessageTextArea):
    prompt: ChannelPrompt

    async def tab_complete(self) -> None:
        prompt = self.prompt
        prompt.refresh_mentions(force=True)
        prompt.accept_mention()

    def action_cursor_up(self, select: bool = False):
        prompt = self.prompt
        if prompt.mention_list.display and not select:
            prompt.mention_list.action_cursor_up()
        else:
            super().action_cursor_up(select)

    def action_cursor_down(self, select: bool = False):
        prompt = self.prompt
        if prompt.mention_list.display and not select:
            prompt.mention_list.action_cursor_down()
        else:
            super().action_cursor_down(select)

    def watch_selection(self, previous_selection: Selection, selection: Selection) -> None:
        super().watch_selection(previous_selection, selection)
        if self.is_mounted:
            self.prompt.refresh_mentions()


class ChannelPrompt(MentionEditor, MessagePrompt):
    TEXT_AREA_CLASS = ChannelTextArea

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mention_list = MentionList()
        self.mention_list.border_title = MentionCompletion.title
        self.mention_list.display = False
        self.mention_candidates: tuple[MentionCandidate, ...] = ()
        self._options: tuple[MentionCandidate, ...] = ()
        self._mention: MentionCompletion = MentionCompletion()
        self._dismissed_text: str | None = None

    def compose(self) -> ComposeResult:
        yield self.mention_list
        yield from super().compose()

    def mention_candidates_changed(self) -> None:
        self.refresh_mentions()

    @on(TextArea.Changed)
    def mention_text_changed(self, event: TextArea.Changed) -> None:
        self.refresh_mentions()

    def refresh_mentions(self, *, force: bool = False) -> None:
        if not self.is_mounted:
            return
        area = self.prompt_text_area
        if force:
            self._dismissed_text = None
        row, column = area.cursor_location
        self._mention = MentionCompletion.at_cursor(area.document.get_line(row), row, column)
        options = self._mention.options(self.mention_candidates)
        if not area.selection.is_empty or area.text == self._dismissed_text:
            options = ()
        if options != self._options:
            self._options = options
            self.mention_list.set_options([Option(MentionCompletion.label(item), id=item.name) for item in options])
            self.mention_list.highlighted = 0 if options else None
        self.mention_list.display = bool(options)

    def accept_mention(self) -> None:
        index = self.mention_list.highlighted
        if not self.mention_list.display or index is None:
            return
        self._mention.accept(self, self._options[index].name)
        self.mention_list.display = False
        self.prompt_text_area.focus()

    def replace_span(self, row: int, start: int, end: int, text: str) -> None:
        self.prompt_text_area.replace(text, (row, start), (row, end), maintain_selection_offset=False)

    @on(OptionList.OptionSelected, "MentionList")
    def mention_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.accept_mention()

    def dismiss_control(self) -> None:
        if self.mention_list.display:
            self._dismissed_text = self.text
            self.mention_list.display = False
        else:
            super().dismiss_control()


class DraftPrompt(ChannelPrompt):
    """Mention-enabled editing without a conversation or delivery authority."""

    def compose_delivery_controls(self) -> ComposeResult:
        return ()

    @property
    def holds_input(self) -> bool:
        return False

    def sync_turn(self) -> None:
        """A draft has no delivery controls to show."""

    def _update_queue_summary(self) -> None:
        pass
