"""Experimental viewport-rendered roster for very large channel catalogs.

Rows are OptionList data rather than Textual Widgets with independent timers,
CSS matching, and event pumps. All semantic membership and unread facts still
come from CommsSidebar's ordinary CoordinationSnapshot.
"""

from dataclasses import dataclass

from rich.segment import Segment

from textual import events
from textual.binding import Binding
from textual.content import Content
from textual.geometry import clamp
from textual.strip import Strip
from textual.style import Style
from textual.visual import VisualType
from textual.visual import Padding
from textual.widgets import OptionList


@dataclass(frozen=True, slots=True)
class VirtualChoice:
    kind: str
    target: str
    channel: str
    mode: str | None = None


class VirtualChannelList(OptionList):
    BINDINGS = [Binding("space", "toggle_expansion", "Members", show=False)]
    DEFAULT_CSS = """
    VirtualChannelList, VirtualChannelList:focus {
        height: auto;
        width: 1fr;
        border: none;
        padding: 0;
        background: transparent;
        background-tint: transparent;
        scrollbar-size: 0 0;
        text-wrap: nowrap;
        text-overflow: clip;
    }
    VirtualChannelList > .option-list--option { padding: 0; }
    VirtualChannelList > .option-list--option-highlighted,
    VirtualChannelList:focus > .option-list--option-highlighted {
        background: transparent;
        text-style: underline;
    }
    VirtualChannelList > .option-list--option-hover {
        background: transparent;
        text-style: underline;
    }
    """

    def __init__(self):
        super().__init__(compact=True, markup=False, id="virtual-channels")
        self.horizontal_content_width = 0
        self.horizontal_offset = 0

    @property
    def horizontal_max(self) -> int:
        return max(0, self.horizontal_content_width - self.scrollable_content_region.width)

    def set_horizontal_content_width(self, width: int) -> None:
        """Retain full source rows; only the painted viewport is cropped."""
        width = max(0, min(width, 4096))
        if width != self.horizontal_content_width:
            self.horizontal_content_width = width
            self._option_render_cache.clear()
            self.refresh()
        self.set_horizontal_offset(self.horizontal_offset)

    def set_horizontal_offset(self, offset: int) -> None:
        offset = int(clamp(offset, 0, self.horizontal_max))
        if offset != self.horizontal_offset:
            self.horizontal_offset = offset
            self.refresh()

    def _get_option_render(self, option, style: Style) -> list[Strip]:
        """Cache full unwrapped strips so moving the bottom scrollbar is paint-only."""
        if self.horizontal_content_width <= self.scrollable_content_region.width:
            return super()._get_option_render(option, style)
        padding = self.get_component_styles("option-list--option").padding
        width = self.horizontal_content_width - self._get_left_gutter_width()
        cache_key = (option, style, padding)
        strips = self._option_render_cache.get(cache_key)
        if strips is None:
            visual = self._get_visual(option)
            if padding:
                visual = Padding(visual, padding)
            strips = visual.to_strips(self, visual, width, None, style)
            meta = {"option": self._option_to_index[option]}
            strips = [strip.extend_cell_length(width, style.rich_style).apply_meta(meta)
                      for strip in strips]
            if option._divider:
                rule = self.get_visual_style("option-list--separator")
                strips.append(Strip([Segment("─" * width, rule.rich_style)], width))
            self._option_render_cache[cache_key] = strips
        return strips

    def render_line(self, y: int) -> Strip:
        viewport = self.scrollable_content_region.width
        return (super().render_line(y)
                .crop(self.horizontal_offset, self.horizontal_offset + viewport)
                .extend_cell_length(viewport))

    def on_resize(self) -> None:
        from toad.widgets.side_bar import SideBar

        self.set_horizontal_offset(self.horizontal_offset)
        sidebar = next((node for node in self.ancestors if isinstance(node, SideBar)), None)
        if sidebar is not None:
            sidebar._sync_horizontal_slider()

    def _replace_option_prompt(self, index: int, prompt: VisualType) -> None:
        """Keep the retained row geometry when only its text/style changed.

        OptionList normally drops every row's render and line caches on a
        prompt update. This roster has a parent-assigned width and unwrapped
        Content rows, so equal-height replacements only damage their own
        strips. Structural changes keep the framework's full invalidation.
        """
        option = self.get_option_at_index(index)
        height = self._line_cache.heights.get(index)
        width = self.scrollable_content_region.width
        if (height is None or width <= 0 or self.styles.text_wrap != "nowrap"
                or not isinstance(prompt, Content)):
            super()._replace_option_prompt(index, prompt)
            return
        padding = self.get_component_styles("option-list--option").padding
        new_height = (prompt.get_height(self.styles, width - padding.width)
                      + option._divider)
        if new_height != height:
            super()._replace_option_prompt(index, prompt)
            return
        option._set_prompt(prompt)
        cache = self._option_render_cache
        for key in tuple(cache.keys()):
            if key[0] is option:
                cache.discard(key)
        self.refresh_lines(self._line_cache.index_to_line[index], height)

    def action_toggle_expansion(self) -> None:
        from toad.widgets.comms_sidebar import CommsSidebar

        option = self.highlighted_option
        if option is None:
            return
        sidebar = self.query_ancestor(CommsSidebar)
        choice = sidebar._virtual_targets.get(option.id)
        if choice is not None and choice.kind in {"irc", "channel"}:
            sidebar._virtual_toggle(choice.channel)

    def on_click(self, event: events.Click) -> None:
        index = event.style.meta.get("option")
        if not isinstance(index, int) or not 0 <= index < self.option_count:
            return
        option_id = self.get_option_at_index(index).id
        from toad.widgets.comms_sidebar import CommsSidebar

        sidebar = self.query_ancestor(CommsSidebar)
        choice = sidebar._virtual_targets.get(option_id)
        if choice is None:
            return
        if event.button == 3:
            event.prevent_default()
            event.stop()
            sidebar._virtual_context_menu(choice, event.screen_offset)
        elif event.button == 1 and event.x == 0 and choice.kind in {"irc", "channel"}:
            event.prevent_default()
            event.stop()
            sidebar._virtual_toggle(choice.channel)


def styled_row(
    content: str, *, selected: bool, ansi: bool, busy: bool = False,
    muted: bool = False, unread: bool = False,
) -> Content:
    """One palette-derived selected row; hover/cursor remains unfilled."""
    if selected:
        color = "ansi_black on ansi_magenta bold" if ansi else "#161021 on #ad8bf5 bold"
        return Content.assemble((content, color))
    if busy:
        return Content.assemble((content, "$warning bold"))
    if unread:
        return Content.assemble((content, "$text-muted bold"))
    if muted:
        return Content.assemble((content, "$text-muted"))
    return Content(content)
