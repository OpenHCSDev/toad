"""Keyboard preferences retain declaration identity and independent modes."""
import pytest

from toad.application_actions import CommanderAction, HelpQuitAction, KeymapAction
from toad.key_modes import KeyMode, Standard, VimNormal
from toad.keymap import Keymap, KeymapCatalog, KeymapRow
from toad.preferences import SETTINGS, SavedSettings
from toad.screens.store import LaunchSlotAction


def test_saved_remaps_keep_modes_independent_and_reset_to_the_declaration():
    catalog = KeymapCatalog.capture(KeyMode.members_with(KeyMode))
    ordinary = KeymapRow.of(KeymapAction(), Standard)
    normal = KeymapRow.of(KeymapAction(), VimNormal)
    keymap = Keymap().changed(normal, ("f7",))
    applied = []
    settings = SavedSettings(applied=applied.append)
    settings.set(SETTINGS.ui.keymap.bindings, keymap.bindings)
    loaded = SavedSettings(settings.document()).current.ui.keymap
    assert [setting.path for setting in applied] == [SETTINGS.ui.keymap.bindings.bind(settings.state).path]
    assert catalog.effective(normal, loaded) == ("f7",)
    assert catalog.effective(ordinary, loaded) == catalog.defaults(ordinary)
    assert catalog.effective(normal, loaded.reset(normal)) == catalog.defaults(normal)
    with pytest.raises(ValueError, match="Commander.*Keymap|Keymap.*Commander"):
        loaded.changed(KeymapRow.of(CommanderAction(), VimNormal), ("f7",))


def test_an_empty_override_unbinds_and_survives_saving_until_reset():
    catalog = KeymapCatalog.capture(KeyMode.members_with(KeyMode))
    menu = KeymapRow.of(KeymapAction(), Standard)
    settings = SavedSettings()
    settings.set(SETTINGS.ui.keymap.bindings, Keymap().changed(menu, ()).bindings)
    loaded = SavedSettings(settings.document()).current.ui.keymap
    assert catalog.effective(menu, loaded) == ()
    assert loaded.native() == {menu.binding_id: ""}
    assert catalog.effective(menu, loaded.reset(menu)) == catalog.defaults(menu)


def test_defaults_allow_the_declared_alternatives_in_every_mode():
    for mode in KeyMode.members_with(KeyMode):
        assert not Keymap().conflicts(mode)


def test_reset_cannot_reintroduce_a_collision_and_duplicate_rows_are_refused():
    catalog = KeymapCatalog.capture(KeyMode.members_with(KeyMode))
    menu = KeymapRow.of(KeymapAction(), Standard)
    keymap = Keymap().changed(menu, ("f7",))
    keymap = keymap.changed(KeymapRow.of(CommanderAction(), Standard), catalog.defaults(menu))
    with pytest.raises(ValueError, match="Key conflict"):
        keymap.reset(menu)
    with pytest.raises(ValueError, match="only one override"):
        Keymap(bindings=(keymap.bindings[0], keymap.bindings[0]))


def test_launch_slots_have_distinct_saved_invocations_and_mode_defaults():
    catalog = KeymapCatalog.capture(KeyMode.members_with(KeyMode))
    rows = tuple(KeymapRow.of(LaunchSlotAction(slot), Standard) for slot in range(15))
    assert len({row.declaration for row in rows}) == len(rows)
    assert tuple(catalog.defaults(row) for row in rows) == tuple((key,) for key in LaunchSlotAction.keys[Standard().binding_mode])
    keymap = Keymap().changed(rows[0], ("f6",))
    settings = SavedSettings()
    settings.set(SETTINGS.ui.keymap.bindings, keymap.bindings)
    loaded = SavedSettings(settings.document()).current.ui.keymap
    assert loaded == keymap
    assert catalog.effective(rows[0], loaded) == ("f6",)
    assert catalog.effective(rows[1], loaded) == catalog.defaults(rows[1])
    assert catalog.effective(KeymapRow.of(LaunchSlotAction(0), VimNormal), loaded) == ("1",)


def test_hidden_system_bindings_keep_their_valid_saved_references():
    row = KeymapRow.of(HelpQuitAction(), Standard)
    keymap = Keymap().changed(row, ("f10",))
    settings = SavedSettings()
    settings.set(SETTINGS.ui.keymap.bindings, keymap.bindings)
    assert SavedSettings(settings.document()).current.ui.keymap == keymap
