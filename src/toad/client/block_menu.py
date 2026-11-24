"""A block's menu in either frontend: which commands it lists in what order, and the
keys each row shows from the user's keymap.

Textual's `widgets.menu.Menu` and Qt's `QtMenu` inherit this. Each keeps its native rows
and its own choose order: Textual posts the choice before the menu leaves; Qt hides its
one shared panel before running, since a run may refill that panel.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from functools import partial
from typing import ClassVar

from toad.client.input_modality import InputModality, KeyboardInput
from toad.client.menu_entry import MenuEntry, strip_menu_markup
from toad.keymap import KeymapCatalog
from toad.menus import MenuCommand, standard_commands
from toad.preferences import ToadSettings

class BlockMenu:
    """The block-menu decisions both frontends share. What a row shows of a command's keys
    and description follows the frontend's declared `input_modality`: a terminal is driven
    by keys; a phone by touch, where a key column is noise and a row must be tappable."""

    input_modality: ClassVar[type[InputModality]] = KeyboardInput

    @staticmethod
    def block_commands(target: object, offered: Iterable[MenuCommand]) -> tuple[MenuCommand, ...]:
        """A block's menu, declared once for both frontends: the family's commands that
        apply to ``target`` (a Textual block cursor, a Qt history fragment; each answers
        `allow_maximize`), then the block's own (``offered``: its `block_menu`). Textual's
        `Menu` and Qt's `QtMenu` only draw it; a frontend that assembled its own list fails
        `tests/model/test_menu_owners.py`."""
        return (*standard_commands(target), *offered)

    @staticmethod
    def ordered(commands: Iterable[MenuCommand]) -> tuple[MenuCommand, ...]:
        """Commands with default keys first, each group in the order given."""
        return tuple(sorted(commands, key=lambda command: not type(command).default_keys()))

    @staticmethod
    def command_keys(command: MenuCommand, settings: ToadSettings) -> str:
        """The keys the user's keymap gives `command` in the current key mode."""
        return ", ".join(KeymapCatalog.menu_keys(command, settings.ui.key_mode, settings.ui.keymap))

    @classmethod
    def command_entries(cls, commands: Iterable[MenuCommand], settings: ToadSettings,
                        run: Callable[[MenuCommand], object]) -> tuple[MenuEntry, ...]:
        """The block menu as plain rows, for a frontend whose menu draws `MenuEntry`s."""
        return tuple(
            MenuEntry(label=strip_menu_markup(command.description), run=partial(run, command),
                      key_display=cls.command_keys(command, settings))
            for command in cls.ordered(commands))

    def row_keys(self, entry: MenuEntry) -> str:
        """The key column this menu's rows show for `entry`."""
        return self.input_modality.menu_keys(entry.key_display)

    def row_text(self, entry: MenuEntry) -> str:
        """A row's text column: the label, then its description on the same line when the
        modality keeps it inline; otherwise the description goes under the label."""
        return self.input_modality.row_text(entry.label, entry.description)

    def row_subtext(self, entry: MenuEntry) -> str:
        """The description line shown beneath a row's label when the modality stacks it."""
        return self.input_modality.row_subtext(entry.description)
