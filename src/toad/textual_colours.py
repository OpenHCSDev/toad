"""The Textual backend for ui_theme's schemes and effects.

`ui_theme` says what the colours and effects mean; this module draws that in
Textual: each scheme becomes a registered Textual theme, each scheme's terminal
palette becomes the Rich terminal theme ANSI colours map to, the colour depth
becomes the console's colour system, the line roles' colours become Rich styles
once per theme, effect frames become strips, and the animation clock runs on
one Textual timer.
"""

from __future__ import annotations

import asyncio
import os
from abc import ABC, ABCMeta, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import lru_cache, partial
from typing import TYPE_CHECKING, ClassVar

from agent_comms.cli_result import ResultShower
from agent_comms.field_codec import FieldCodec
from rich.color import Color as RichColor
from rich.console import RenderableType
from rich.segment import Segment
from rich.style import Style as RichStyle
from rich.terminal_theme import TerminalTheme
from textual.ansi_palette import AnsiPalette, MappedAnsiPalette, NativeAnsiPalette
from textual.app import App
from textual.color import Color
from textual.content import Content
from textual.design import ColorSystem
from textual.driver import TerminalGaveNoPalette
from textual.message_pump import _MessagePumpMeta
from textual.notifications import SeverityLevel
from textual.screen import Screen
from textual.strip import Strip
from textual.style import Style as VisualStyle
from textual.theme import Theme
from ui_theme.backend import Backend, TerminalBackend
from ui_theme.catalog import SCHEMES
from ui_theme.clock import AnimationClock
from ui_theme.colour import (
    AnsiColour,
    Colour,
    Rgb,
    TerminalPalette,
    require_terminal_palette,
)
from ui_theme.depth import ColourDepth
from ui_theme.effects import Band, Gradient, Mix, PlayedText, TextFrame
from ui_theme.scheme import (
    BackgroundColour,
    BlendColour,
    ColourScheme,
    ForegroundColour,
    LayerColour,
    TextStyle,
    ThemeColour,
)
from ui_theme.splash import TextEffect
from ui_theme.wal import WalFile
from watchdog.events import FileClosedEvent, FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from toad.line_blocks import LineRole
from toad.preferences import SavedSettings, ToadSettings
from toad.render_tasks import TextEffectRenderTask
from toad.widgets.transcript_lines import LineTheme, RichLineRenderer

if TYPE_CHECKING:
    from toad.app import ToadApp


class _WalFileClosed(FileSystemEventHandler):
    """pywal rewrites `colors.json` in place; it is whole once the writer closes it."""

    def __init__(self, colours: TextualColours) -> None:
        self.colours = colours

    def on_any_event(self, event: FileSystemEvent) -> None:
        if isinstance(event, FileClosedEvent) and os.path.basename(event.src_path) == WalFile.NAME:
            self.colours.app.call_from_thread(self.colours.read_wal)


class ClockCadence:
    """The animation clock's cadence; this base is the stopped one, with no tick due."""

    def cancel(self) -> None:
        pass


class ClockRunning(ClockCadence):
    """A tick every `interval` seconds; `handle` is the one pending tick."""

    def __init__(self, interval: float, tick: Callable[[ClockRunning], object]) -> None:
        self.interval = interval
        self.handle = asyncio.get_running_loop().call_later(interval, tick, self)

    def cancel(self) -> None:
        self.handle.cancel()


class BlockInk:
    """A native block's occupied edge, independent of its theme colour."""

    GLYPHS: ClassVar[str]
    LEVELS: ClassVar[int]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        cls.LEVELS = len(cls.GLYPHS) - 1

    @classmethod
    def glyph(cls, level: int) -> str:
        return cls.GLYPHS[level]

    @classmethod
    def paint(cls, level: int, ink: Color, background: Color, style: RichStyle) -> Segment:
        return Segment(cls.glyph(level), style + RichStyle(
            color=ink.rich_color, bgcolor=background.rich_color))


class BottomInk(BlockInk):
    GLYPHS = " ▄█"


class TopInk(BlockInk):
    GLYPHS = " ▀█"


class PaletteState(AnsiPalette, ABC):
    def refresh_colours(self, colours: TextualColours) -> None:
        """Native colours already in the stylesheet need no RGB replacement."""

    @abstractmethod
    async def text_effect(self, colours: TextualColours, effect: TextEffect, scheme: ColourScheme) -> PlayedText: ...

    @abstractmethod
    def paint_rising(self, colours: TextualColours, frame: Mix, target: Strip) -> Strip: ...

    @abstractmethod
    def resolved(self, colour: RichColor, *, foreground: bool) -> Color: ...

    @abstractmethod
    def derived(self, member: type[ThemeColour], colours: dict[type[ThemeColour], Color]) -> Color: ...

    @abstractmethod
    def tint_style(self, style: RichStyle, amount: float) -> RichStyle: ...



class UnknownPalette(NativeAnsiPalette, PaletteState):
    """Native ANSI styles remain usable when the terminal cannot report RGB."""

    async def text_effect(self, colours: TextualColours, effect: TextEffect, scheme: ColourScheme) -> PlayedText:
        return PlayedText((TextFrame(tuple(tuple((character, None) for character in line)
                                           for line in effect.text.splitlines())),), effect.frames_per_second)

    def paint_rising(self, colours: TextualColours, frame: Mix, target: Strip) -> Strip:
        if frame.amount >= 0.5:
            return target
        return Strip(Segment.apply_style(target, post_style=RichStyle(dim=True)), target.cell_length)

    def resolved(self, colour: RichColor, *, foreground: bool) -> Color:
        return Color.from_rich_color(colour, foreground=foreground)

    def derived(self, member: type[ThemeColour], colours: dict[type[ThemeColour], Color]) -> Color:
        return colours[BackgroundColour if member.background else ForegroundColour]

    def tint_style(self, style: RichStyle, amount: float) -> RichStyle:
        return style



class KnownPalette(MappedAnsiPalette, PaletteState):
    def __init__(self, colours: TerminalPalette) -> None:
        self.colours = colours
        ansi = [colour.triple for colour in colours.ansi]
        super().__init__(TerminalTheme(colours.background.triple, colours.foreground.triple,
                                       ansi[:8], ansi[8:]))

    def refresh_colours(self, colours: TextualColours) -> None:
        colours.app.refresh_css(animate=False)

    async def text_effect(self, colours: TextualColours, effect: TextEffect, scheme: ColourScheme) -> PlayedText:
        return await colours.app.prepare_background(
            TextEffectRenderTask(effect, replace(scheme, terminal=self.colours)))

    def resolved(self, colour: RichColor, *, foreground: bool) -> Color:
        return Color(*colour.get_truecolor(self._terminal_theme, foreground=foreground))

    def derived(self, member: type[ThemeColour], colours: dict[type[ThemeColour], Color]) -> Color:
        def read(role: type[ThemeColour]) -> Rgb:
            value = colours[role]
            return Rgb(*value.rich_color.get_truecolor(self._terminal_theme, foreground=not role.background), value.a)
        value = member.resolve_rgb(read)
        return Color(value.red, value.green, value.blue, value.alpha)

    def tint_style(self, style: RichStyle, amount: float) -> RichStyle:
        base = Color(*self._terminal_theme.background_color)
        fill = base.blend(self.resolved(style.color or RichColor.default(), foreground=True), amount)
        return style + RichStyle(bgcolor=fill.rich_color)

    def paint_rising(self, colours: TextualColours, frame: Mix, target: Strip) -> Strip:
        if frame.amount >= 1.0:
            return target
        start = self.resolved(colours.colour(frame.start).rich_color, foreground=False)
        resting_foreground = Color(*self.colours.foreground.triple)

        def risen(segment: Segment) -> Segment:
            text, style, control = segment
            own = (self.resolved(style.color, foreground=True)
                   if style is not None and style.color is not None else resting_foreground)
            colour = start.blend(own, frame.amount).rich_color
            return Segment(text, (style or RichStyle()) + RichStyle(color=colour), control)

        return Strip([risen(segment) for segment in target], target.cell_length)


@dataclass(frozen=True)
class TextualScheme:
    scheme: ColourScheme
    palette: PaletteState


class TextualColours(Backend[Theme, Color, Strip | Content, Strip], TerminalBackend[TerminalTheme]):
    """The app's colour depth, schemes, terminal palettes, line styles and animation clock."""

    def __init__(self, app: ToadApp) -> None:
        self.app = app
        self.depth: type[ColourDepth] = ColourDepth.of_terminal(os.environ)
        self.wal_directory = WalFile.directory(os.environ)
        # Set from the theme's CSS variables, which the app builds before it runs.
        self.line_renderer: RichLineRenderer
        self.variables: dict[str, str] = {}
        self._colours: dict[type[ThemeColour], Color] = {}
        self.schemes: dict[str, TextualScheme] = {}
        self.terminal_palette: PaletteState = UnknownPalette()
        for scheme in SCHEMES:
            self._add(scheme)
        self._observer: BaseObserver | None = None
        self._cadence = ClockCadence()
        self.clock = AnimationClock(self._schedule)

    # The catalog and pywal.

    def register_catalog(self) -> None:
        """Offer ui_theme's schemes, replacing Textual's copies of the same themes."""
        self.clock.enabled = self.app.animation_level != "none"
        for entry in self.schemes.values():
            self.app.register_theme(self.theme(entry.scheme))
        if (self.wal_directory / WalFile.NAME).is_file():
            self.read_wal()

    def start(self) -> None:
        """Follow pywal's changes to its palette."""
        if not self.wal_directory.is_dir():
            return
        self._observer = Observer()
        self._observer.schedule(_WalFileClosed(self), str(self.wal_directory))
        self._observer.daemon = True
        self._observer.start()

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer = None
        self._schedule(None)

    def read_wal(self) -> None:
        try:
            scheme = WalFile.read(self.wal_directory / WalFile.NAME).scheme
        except (OSError, ValueError) as error:
            self.app.show_error(error, "pywal colours were not applied")
            return
        self.register(scheme)
        if self.app.is_running and self.app.theme == scheme.name:
            # Same theme name, new colours: apply the theme again.
            self.app.mutate_reactive(type(self.app).theme)

    def register(self, scheme: ColourScheme) -> None:
        self._add(scheme)
        self.app.register_theme(self.theme(scheme))

    def _add(self, scheme: ColourScheme) -> None:
        palette = (self.terminal_palette if scheme.from_terminal else
                   KnownPalette(scheme.terminal.resolve(require_terminal_palette)))
        self.schemes[scheme.name] = TextualScheme(scheme, palette)

    async def mount(self) -> None:
        """Resolve the initial native ANSI state before the first paint."""
        self.terminal_palette = await self.queried_palette()
        for scheme in SCHEMES:
            if scheme.from_terminal:
                self._add(scheme)
        self.terminal_palette.refresh_colours(self)

    def choose(self, name: str) -> None:
        if name not in self.schemes:
            # `wal` exists once pywal has written its palette.
            self.app.show_error(f"Theme {name!r} is not available"
                                + (f": pywal has not written {self.wal_directory / WalFile.NAME}"
                                   if name == WalFile.SCHEME else ""), "Theme")
            return
        self.app.theme = name

    @property
    def scheme(self) -> ColourScheme:
        return self.schemes[self.app.theme].scheme

    def terminal_theme(self, name: str) -> PaletteState:
        """The palette ANSI colours map to under a theme."""
        return self.schemes[name].palette

    async def queried_palette(self) -> PaletteState:
        """Read the terminal's colours once, through its existing input driver."""
        try:
            driver = self.app._driver
            assert driver is not None, "Palette query requires the running terminal driver"
            colours = await driver.query_colours(timeout=0.25)
        except TerminalGaveNoPalette:
            return UnknownPalette()
        foreground = Rgb(*colours.foreground)
        return KnownPalette(TerminalPalette(Rgb(*colours.background), foreground, foreground,
                               tuple(Rgb(*colour) for colour in colours.ansi)))

    def variables_changed(self, variables: dict[str, str], system: ColorSystem) -> None:
        palette = self.schemes[self.app.theme].palette
        variables = dict(variables)
        self._colours = {member: value.native(self)
                         for member, value in self.scheme.resolved_colours.items()}
        self._colours.update({member: system.color(member.name) for member in LayerColour.members()})

        for member in BlendColour.members():
            derived = palette.derived(member, self._colours)
            self._colours[member] = derived
            variables[member.name] = derived.css
        self.variables = variables
        self.refresh_line_renderer()

    def refresh_line_renderer(self) -> None:
        self.line_renderer = RichLineRenderer(LineTheme.of(self))

    @property
    def line_theme(self) -> LineTheme:
        return self.line_renderer.theme

    # The backend.

    def theme(self, scheme: ColourScheme) -> Theme:
        colours = {member.name: value.variable(self) for member, value in scheme.colours.items()}
        variables = {member.name: value.variable(self)
                     for member, value in scheme.resolved_elements.items()}
        return FieldCodec.decode(Theme, {
            "name": scheme.name, "dark": scheme.dark, "ansi": scheme.from_terminal,
            "variables": variables, **colours,
        })

    def palette(self, palette: TerminalPalette) -> TerminalTheme:
        ansi = [colour.triple for colour in palette.ansi]
        return TerminalTheme(palette.background.triple, palette.foreground.triple, ansi[:8], ansi[8:])

    def rgb(self, colour: Rgb) -> Color:
        return Color(colour.red, colour.green, colour.blue, colour.alpha)

    def ansi(self, colour: AnsiColour) -> Color:
        return Color(0, 0, 0, ansi=colour.index)

    def terminal_default(self) -> Color:
        return Color(0, 0, 0, ansi=-1)

    def text_style(self, style: TextStyle) -> str:
        return style.value

    def colour_variable(self, colour: Colour) -> str:
        return colour.native(self).css

    def colour(self, colour: type[ThemeColour]) -> Color:
        """The resolved value for a declared colour in the active theme."""
        return self._colours[colour]

    def style(self, role: type[LineRole]) -> VisualStyle:
        """The same resolved line role for Textual content as for rendered rows."""
        return self.schemes[self.app.theme].palette.rich_style(self.line_theme.style(role))

    def mixed(self, start: type[ThemeColour], end: type[ThemeColour], amount: float) -> Color:
        first, last = self.colour(start), self.colour(end)
        # Terminal colours cannot be blended; they step.
        if first.ansi is not None or last.ansi is not None:
            return first if amount < 0.5 else last
        return first.blend(last, amount)

    def resolved(self, colour: RichColor, *, foreground: bool) -> Color:
        """Resolve palette ink or background against the active terminal theme."""
        return self.schemes[self.app.theme].palette.resolved(colour, foreground=foreground)

    def paint_gradient(self, frame: Gradient, target: Strip,
                       *, edge: type[BlockInk] = BottomInk) -> Strip:
        """Sample shared colour/shape into truecolour cells; never change row geometry."""
        width = target.cell_length
        if width == 0:
            return target
        first = next(iter(target))
        style = first.style or RichStyle()
        colours = {
            role: self.resolved(self.colour(role).rich_color, foreground=not role.background)
            for role in dict.fromkeys(frame.stops)
        }
        background = self.resolved(
            style.bgcolor or self.colour(BackgroundColour).rich_color, foreground=False)
        segments = []
        for cell in range(width):
            start, end, amount, height = frame.sample((cell + 0.5) / width)
            if height <= 0:
                segments.append(Segment(" ", style))
                continue
            level = max(1, min(edge.LEVELS, round(height * edge.LEVELS)))
            ink = colours[start].blend(colours[end], amount)
            # Fade tails smaller than the first native level. Keep the body
            # at full colour when its glyph reaches that level.
            ink = background.blend(ink, min(1.0, height * edge.LEVELS))
            segments.append(edge.paint(level, ink, background, style))
        return Strip(Segment.simplify(segments), cell_length=width)

    def paint_mix(self, frame: Mix, target: Strip) -> Strip:
        return Strip(Segment.apply_style(target, post_style=RichStyle(
            color=self.mixed(frame.start, frame.end, frame.amount).rich_color)), target.cell_length)

    def paint_band(self, frame: Band, target: Strip) -> Strip:
        width = target.cell_length
        start, end = (max(0, min(width, round(edge * width))) for edge in (frame.start, frame.end))
        if start >= end:
            return target
        before, band, after = target.divide((start, end, width))
        band = Strip(Segment.apply_style(band, post_style=RichStyle(
            color=self.colour(frame.colour).rich_color)), band.cell_length)
        return Strip.join((before, band, after))

    def paint_rising(self, frame: Mix, target: Strip) -> Strip:
        """The palette state owns RGB blending or the native dim-to-normal step."""
        return self.schemes[self.app.theme].palette.paint_rising(self, frame, target)

    def paint_text(self, frame: TextFrame, target: Strip | None) -> Content:
        """Text in Textual's own styled text; each frame is built once."""
        return _text(frame)

    # The animation clock's one timer.

    def _schedule(self, interval: float | None) -> None:
        """Run `tick` every `interval` seconds, or never when interval is None.

        Each tick is a Textual callback message posted after the interval, so it
        always returns to the event loop, and Textual handles what it raises. A
        Textual interval timer started from inside `tick` (its `refresh` asks for
        a new interval) ran its first tick inline under Textual's eager task
        factory, and Textual's sleep does not yield below half a millisecond, so
        a short interval never returned and froze the app.
        """
        self._cadence.cancel()
        self._cadence = self._arm(interval) if interval is not None else ClockCadence()

    def _arm(self, interval: float) -> ClockRunning:
        return ClockRunning(interval, partial(self.app.call_later, self._tick))

    def _tick(self, cadence: ClockRunning) -> None:
        if self._cadence is not cadence:
            return
        self.clock.tick()
        # `tick` replaces the cadence through `_schedule` when its interval
        # changed; otherwise the same cadence continues.
        if self._cadence is cadence:
            self._cadence = self._arm(cadence.interval)


class _ThemedAppMeta(_MessagePumpMeta, ABCMeta):
    """Compose Textual message dispatch with the result display capability."""


class ThemedApp(App[None], ResultShower, metaclass=_ThemedAppMeta):
    """A Textual app drawn through ui_theme: mix in before `App`.

    Holds the colours owner and answers Textual's three questions from it: the
    console's colour system, the terminal palette ANSI colours map to, and the
    CSS variables (from which the line styles are resolved). Widgets that use
    effects or line styles need their app to be one.
    """

    colours: TextualColours
    saved_settings: SavedSettings

    def __init__(self) -> None:
        # Line styles read the diff settings, so a themed app holds settings before its colours.
        self.saved_settings = self.open_settings()
        # Textual asks for the colour system and the palette while it builds the app.
        self.colours = TextualColours(self)  # type: ignore[arg-type]
        super().__init__()
        self.colours.register_catalog()

    def open_settings(self) -> SavedSettings:
        """Settings held by this app alone; an app with a settings file opens it instead."""
        return SavedSettings()

    @property
    def settings(self) -> ToadSettings:
        """The settings in use, to read from; `saved_settings` changes and saves them."""
        return self.saved_settings.current

    def _display(self, screen: Screen, renderable: RenderableType | None) -> None:
        super()._display(screen, renderable)
        self.colours.clock.refresh()

    def watch_app_focus(self, focused: bool) -> None:
        self.colours.clock.refresh()

    def show_done(self, text: str, title: str) -> None:
        self.notify(text, title=title)

    def show_failure(self, text: str, title: str) -> None:
        self.show_error(text, title)

    def show_error(self, error: Exception | str, title: str, severity: SeverityLevel = "error") -> None:
        """Every error Toad shows: its text verbatim, never parsed as markup."""
        text = str(error)
        self.notify(text, title=title, severity=severity, markup=False)

    def get_color_system(self) -> str:
        return self.colours.depth.name

    def get_css_variables(self) -> dict[str, str]:
        variables = super().get_css_variables()  # type: ignore[misc]
        self.colours.variables_changed(variables, self.color_system)
        return self.colours.variables

    @property
    def ansi_theme(self) -> PaletteState:
        return self.colours.terminal_theme(self.theme)  # type: ignore[attr-defined]


@lru_cache(maxsize=128)
def _text(frame: TextFrame) -> Content:
    return Content("\n").join(
        Content.assemble(*((character, VisualStyle(foreground=Color(*colour.triple)))
                           if colour is not None else character for character, colour in line))
        for line in frame.lines)
