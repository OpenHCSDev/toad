"""Keyboard preferences retain declaration identity and independent modes."""
import pytest

from toad.application_actions import CommanderAction, KeymapAction
from toad.key_modes import KeyMode, Standard, VimNormal
from toad.keymap import Keymap, KeymapRow
from toad.preferences import SETTINGS, SavedSettings


def test_saved_remaps_keep_modes_independent_and_reset_to_the_declaration():
    ordinary = KeymapRow(KeymapAction, Standard)
    normal = KeymapRow(KeymapAction, VimNormal)
    keymap = Keymap().changed(normal, ("f7",))
    applied = []
    settings = SavedSettings(applied=applied.append)
    settings.set(SETTINGS.ui.keymap.bindings, keymap.bindings)
    loaded = SavedSettings(settings.document()).current.ui.keymap
    assert [setting.path for setting in applied] == [SETTINGS.ui.keymap.bindings.bind(settings.state).path]
    assert normal.effective(loaded) == ("f7",)
    assert ordinary.effective(loaded) == ordinary.defaults
    assert normal.effective(loaded.reset(normal)) == normal.defaults
    with pytest.raises(ValueError, match="Commander.*Keymap|Keymap.*Commander"):
        loaded.changed(KeymapRow(CommanderAction, VimNormal), ("f7",))


def test_defaults_allow_the_declared_alternatives_in_every_mode():
    for mode in KeyMode.members_with(KeyMode):
        assert not Keymap().conflicts(mode)


def test_reset_cannot_reintroduce_a_collision_and_duplicate_rows_are_refused():
    menu = KeymapRow(KeymapAction, Standard)
    keymap = Keymap().changed(menu, ("f7",))
    keymap = keymap.changed(KeymapRow(CommanderAction, Standard), menu.defaults)
    with pytest.raises(ValueError, match="Key conflict"):
        keymap.reset(menu)
    with pytest.raises(ValueError, match="only one override"):
        Keymap(bindings=(keymap.bindings[0], keymap.bindings[0]))
