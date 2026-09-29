"""Shared rendering of the owning ANSI model; no terminal process lifetime."""
from textual.geometry import Region, Size


class TerminalStateProjection:
    def project_state(
        self, scrollback_delta: set[int] | None, alternate_delta: set[int] | None
    ) -> None:
        """Paint the owning ANSI state without decoding or replaying output."""
        self._update_from_state(scrollback_delta, alternate_delta)
        self.display = self.state.alternate_screen or not self.state.scrollback_buffer.is_blank
        if self._alternate_screen != self.state.alternate_screen:
            self.post_message(
                self.AlternateScreenChanged(self, enabled=self.state.alternate_screen)
            )
        self._alternate_screen = self.state.alternate_screen

    def _update_from_state(
        self, scrollback_delta: set[int] | None, alternate_delta: set[int] | None
    ) -> None:
        if self.state.current_directory:
            self.current_directory = self.state.current_directory
            self.finalize()
        width = self.state.width
        height = self.state.scrollback_buffer.height

        if self.state.alternate_screen:
            height += self.state.alternate_buffer.height
        self.virtual_size = Size(min(self.state.buffer.max_line_width, width), height)
        if self._anchored and not self._anchor_released:
            self.scroll_y = self.max_scroll_y

        scroll_y = int(self.scroll_y)
        visible_lines = frozenset(range(scroll_y, scroll_y + height))

        if scrollback_delta is None and alternate_delta is None:
            self.refresh()
        else:
            window_width = self.region.width
            scrollback_height = self.state.scrollback_buffer.height
            if scrollback_delta is None:
                self.refresh(Region(0, 0, window_width, scrollback_height))
            else:
                refresh_lines = [
                    Region(0, y - scroll_y, window_width, 1)
                    for y in sorted(scrollback_delta & visible_lines)
                ]
                if refresh_lines:
                    self.refresh(*refresh_lines)
            alternate_height = self.state.alternate_buffer.height
            if alternate_delta is None:
                self.refresh(
                    Region(
                        0,
                        scrollback_height - scroll_y,
                        window_width,
                        scrollback_height + alternate_height,
                    )
                )
            else:
                alternate_delta = {
                    line_no + scrollback_height for line_no in alternate_delta
                }
                refresh_lines = [
                    Region(0, y - scroll_y, window_width, 1)
                    for y in sorted(alternate_delta & visible_lines)
                ]
                if refresh_lines:
                    self.refresh(*refresh_lines)

