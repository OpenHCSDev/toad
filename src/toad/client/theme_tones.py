"""Shared UI colour tones and chrome role declarations for both Textual and Qt.

Every surface tone, tab chrome role, sidebar toggle tint, scrollbar role, and floating
surface tone is declared here once on `ui_theme.scheme.ThemeColour` / `ToneColour`.
Because `ToneColour` subclasses register with `ui_theme`'s `BlendColour` family at import
time, Textual's `TextualColours` and Qt's `QtLineRenderer` resolve identical 24-bit RGB
values for every scheme (including pywal's `wal` palette) with zero parallel colour
copies between frontends.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from ui_theme.colour import Rgb
from ui_theme.scheme import (
    AccentColour,
    BackgroundColour,
    ErrorColour,
    FloatHoverToneColour,
    FloatToneColour,
    ForegroundColour,
    HeaderToneColour,
    MutedColour,
    PrimaryColour,
    SelectedTabToneColour,
    SidebarToneColour,
    SurfaceHoverColour,
    ThemeColour,
    ToneColour,
)


class HueToneColour(ToneColour):
    """A sidebar surface stepped toward a theme hue instead of toward the foreground.

    Rows on it read as a different family from rows on the neutral sidebar tones.
    Without RGB (a native ANSI palette) it resolves to the background, like every
    derived tone.
    """

    hue: ClassVar[type[ThemeColour]] = PrimaryColour
    amount: ClassVar[float]

    @classmethod
    def resolve_rgb(cls, read: Callable[[type[ThemeColour]], Rgb]) -> Rgb:
        return SidebarToneColour.resolve_rgb(read).blend(read(cls.hue), cls.amount)


class ChannelRowTone(HueToneColour):
    """Alternating sidebar channel row surfaces stepped toward the theme hue."""


class ChannelRowToneColour(ChannelRowTone):
    """A channel row of the channel list."""

    name = "tone-channel-row"
    amount = 0.13


class ChannelAlternateRowToneColour(ChannelRowTone):
    """Every other channel row, one more step toward the hue."""

    name = "tone-channel-row-alternate"
    amount = 0.2


class SidebarToggleToneColour(HueToneColour):
    """The sidebar collapse/resize edge bar, tinted 8% toward PrimaryColour over the sidebar."""

    name = "tone-sidebar-toggle"
    amount = 0.08


class TabHoverToneColour(ToneColour):
    """An inactive tab hover fill and tab underline track: HeaderToneColour stepped 10%
    toward ForegroundColour."""

    name = "tone-tab-hover"
    amount = 0.1

    @classmethod
    def resolve_rgb(cls, read: Callable[[type[ThemeColour]], Rgb]) -> Rgb:
        return HeaderToneColour.resolve_rgb(read).blend(read(ForegroundColour), cls.amount)


class WorkspaceTabTones:
    """Single colour declaration for the workspace navigation bar and session tabs across
    Textual (`WorkspaceHeader`, `SessionLabel`, `SessionTabClose`, `Underline`) and Qt
    (`QtToadApp.paint_chrome_colours`, `QtSessionTabBar`).

    Three stepped tiers keep inter-tab gaps and active/inactive tabs visually distinct:
    `bar_tone` (strip + gaps) -> `inactive_tab_tone` -> `selected_tab_tone`."""

    bar_tone: ClassVar[type[ThemeColour]] = SidebarToneColour
    inactive_tab_tone: ClassVar[type[ThemeColour]] = HeaderToneColour
    selected_tab_tone: ClassVar[type[ThemeColour]] = SelectedTabToneColour
    hover_tone: ClassVar[type[ThemeColour]] = TabHoverToneColour
    underline_colour: ClassVar[type[ThemeColour]] = AccentColour
    active_text_colour: ClassVar[type[ThemeColour]] = ForegroundColour
    inactive_text_colour: ClassVar[type[ThemeColour]] = MutedColour
    close_idle_colour: ClassVar[type[ThemeColour]] = MutedColour
    close_hover_colour: ClassVar[type[ThemeColour]] = ErrorColour
    unread_badge_colour: ClassVar[type[ThemeColour]] = AccentColour


class ScrollbarTones:
    """Single colour declaration for scrollbars across frontends."""

    track_colour: ClassVar[type[ThemeColour]] = BackgroundColour
    thumb_colour: ClassVar[type[ThemeColour]] = SurfaceHoverColour
    active_colour: ClassVar[type[ThemeColour]] = PrimaryColour


class FloatSurfaceTones:
    """Single colour declaration for floating surfaces (toasts, notices, pending overlays)."""

    background_tone: ClassVar[type[ThemeColour]] = FloatToneColour
    hover_tone: ClassVar[type[ThemeColour]] = FloatHoverToneColour
