"""Channel mention completion uses model-provided members and mention syntax."""

from agent_comms import MentionCandidate, MentionQuery
from textual import on
from textual.app import ComposeResult
from textual.widgets import OptionList, TextArea
from textual.widgets.option_list import Option
from textual.widgets.text_area import Selection

from toad.widgets.prompt import Prompt, PromptTextArea
from toad.widgets.selection import SelectionOptionList


class MentionList(SelectionOptionList):
    DEFAULT_CSS = "MentionList { height: auto; max-height: 7; margin-bottom: 1; }"


class ChannelTextArea(PromptTextArea):
    async def action_tab_complete(self) -> None:
        prompt = self.query_ancestor(ChannelPrompt)
        prompt.refresh_mentions(force=True)
        prompt.accept_mention()

    def action_cursor_up(self, select: bool = False):
        prompt = self.query_ancestor(ChannelPrompt)
        if prompt.mention_list.display and not select:
            prompt.mention_list.action_cursor_up()
        else:
            super().action_cursor_up(select)

    def action_cursor_down(self, select: bool = False):
        prompt = self.query_ancestor(ChannelPrompt)
        if prompt.mention_list.display and not select:
            prompt.mention_list.action_cursor_down()
        else:
            super().action_cursor_down(select)

    async def watch_selection(self, previous_selection: Selection, selection: Selection) -> None:
        await super().watch_selection(previous_selection, selection)
        if self.is_mounted:
            self.query_ancestor(ChannelPrompt).refresh_mentions()


class ChannelPrompt(Prompt):
    TEXT_AREA_CLASS = ChannelTextArea

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mention_list = MentionList()
        self.mention_list.border_title = "Mention a thread · Tab to insert"
        self.mention_list.display = False
        self._candidates: tuple[MentionCandidate, ...] = ()
        self._options: tuple[MentionCandidate, ...] = ()
        self._query: MentionQuery | None = None
        self._query_row = 0
        self._dismissed_text: str | None = None

    def compose(self) -> ComposeResult:
        yield self.mention_list
        yield from super().compose()

    def set_mention_candidates(self, candidates: tuple[MentionCandidate, ...]) -> None:
        if candidates != self._candidates:
            self._candidates = candidates
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
        self._query_row = row
        self._query = MentionQuery.at_cursor(area.document.get_line(row), column)
        options = self._query.candidates(self._candidates) if self._query else ()
        if not area.selection.is_empty or area.text == self._dismissed_text:
            options = ()
        if options != self._options:
            self._options = options
            self.mention_list.set_options([
                Option(f"@{item.name}" + (f" — {item.title}" if item.title != item.name else ""), id=item.name)
                for item in options
            ])
            self.mention_list.highlighted = 0 if options else None
        self.mention_list.display = bool(options)

    def accept_mention(self) -> None:
        index = self.mention_list.highlighted
        if not self.mention_list.display or self._query is None or index is None:
            return
        name = self._options[index].name
        area = self.prompt_text_area
        following = area.document.get_line(self._query_row)[self._query.end:]
        suffix = " " if not following or (not following[0].isspace() and following[0] not in ".,:;!?)]}") else ""
        area.replace(
            f"@{name}{suffix}", (self._query_row, self._query.start),
            (self._query_row, self._query.end), maintain_selection_offset=False,
        )
        self.mention_list.display = False
        area.focus()

    @on(OptionList.OptionSelected, "MentionList")
    def mention_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.accept_mention()

    def action_dismiss(self) -> None:
        if self.mention_list.display:
            self._dismissed_text = self.text
            self.mention_list.display = False
        else:
            super().action_dismiss()
