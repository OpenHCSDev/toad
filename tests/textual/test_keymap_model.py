"""Keyboard preferences retain declaration identity and independent modes."""
import pytest
from textual.widget import Widget

from toad.application_actions import HelpQuitAction
from toad.client.application_actions import (
    DeclaredAction,
    DuplicateSavedKey,
    KeymapAction,
    TeamAction,
)
from toad.prompt_actions import SubmitAction as PromptSubmit
from toad.widget_actions import SubmitAction as WidgetSubmit
from toad.key_modes import KeyMode, Standard, VimNormal
from toad.keymap import Keymap, KeymapCatalog, KeymapRow
from toad.preferences import SETTINGS, SavedSettings


def test_saved_remaps_keep_modes_independent_and_reset_to_the_declaration():
    catalog = KeymapCatalog.capture(KeyMode.members_with(KeyMode))
    ordinary = KeymapRow.of(KeymapAction(), Standard)
    normal = KeymapRow.of(KeymapAction(), VimNormal)
    keymap = Keymap().changed(normal, ("f18",))
    applied = []
    settings = SavedSettings(applied=applied.append)
    settings.set(SETTINGS.ui.keymap.bindings, keymap.bindings)
    loaded = SavedSettings(settings.document()).current.ui.keymap
    assert [setting.path for setting in applied] == [SETTINGS.ui.keymap.bindings.bind(settings.state).path]
    assert catalog.effective(normal, loaded) == ("f18",)
    assert catalog.effective(ordinary, loaded) == catalog.defaults(ordinary)
    assert catalog.effective(normal, loaded.reset(normal)) == catalog.defaults(normal)
    with pytest.raises(ValueError, match="Team.*Keymap|Keymap.*Team"):
        loaded.changed(KeymapRow.of(TeamAction(), VimNormal), ("f18",))


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
    keymap = Keymap().changed(menu, ("f18",))
    keymap = keymap.changed(KeymapRow.of(TeamAction(), Standard), catalog.defaults(menu))
    with pytest.raises(ValueError, match="Key conflict"):
        keymap.reset(menu)
    with pytest.raises(ValueError, match="only one override"):
        Keymap(bindings=(keymap.bindings[0], keymap.bindings[0]))


def test_the_catalog_is_built_once_per_declarations_and_sees_a_class_declared_later():
    modes = tuple(KeyMode.members_with(KeyMode))
    first = KeymapCatalog.capture(modes)
    # Every saved keymap row validates against the catalog; twelve rows build it once.
    assert all(KeymapCatalog.capture(modes) is first for _ in range(12))

    class DeclaredAfterTheFirstCapture(Widget):
        """A context the first catalog could not have seen."""

    later = KeymapCatalog.capture(modes)
    assert later is not first
    assert all(len(later.scopes[mode]) == len(first.scopes[mode]) + 1 for mode in modes)


def test_hidden_system_bindings_keep_their_valid_saved_references():
    row = KeymapRow.of(HelpQuitAction(), Standard)
    keymap = Keymap().changed(row, ("f10",))
    settings = SavedSettings()
    settings.set(SETTINGS.ui.keymap.bindings, keymap.bindings)
    assert SavedSettings(settings.document()).current.ui.keymap == keymap


def test_a_saved_keymap_follows_its_declaration_when_the_class_moves_module():
    # KeymapAction lived in toad.application_actions until #2001 hoisted it to toad.client;
    # a toad.json written before that names the old module and must keep its keys.
    moved = {"ui": {"keymap": {"bindings": [
        {"declaration": "toad.application_actions.KeymapAction", "mode": "standard", "keys": ["f1"]},
    ]}}}
    settings = SavedSettings(moved)
    (remap,) = settings.current.ui.keymap.bindings
    assert remap.declaration == KeymapAction.identity() and remap.keys == ("f1",)
    # What is written back names the declaration, not its module, so the next move is harmless.
    assert settings.document()["ui"]["keymap"]["bindings"][0]["declaration"] == "KeymapAction"
    assert SavedSettings(settings.document()).current.ui.keymap == settings.current.ui.keymap


def test_every_command_has_its_own_saved_name_and_old_paths_are_never_guessed():
    catalog = KeymapCatalog.capture(tuple(KeyMode.members_with(KeyMode)))
    assert len(catalog.saved_names) == len(catalog.invocations)
    for reference in catalog.invocations:
        assert catalog.resolve(catalog.spelling(reference)) == reference
    # Two declarations are classes named SubmitAction; each saves under its own name, and an
    # old file's exact module path still finds its own class.
    assert catalog.spelling(WidgetSubmit.identity()) == "SubmitAction"
    assert catalog.spelling(PromptSubmit.identity()) == "PromptSubmitAction"
    assert catalog.resolve("toad.prompt_actions.SubmitAction") == PromptSubmit.identity()
    # A moved path that matches both by class name alone names neither, and is refused by name.
    with pytest.raises(ValueError, match="could name any of"):
        catalog.resolve("toad.somewhere_else.SubmitAction")
    with pytest.raises(ValueError, match="Unknown keyboard invocation 'toad.nowhere.Nonexistent'"):
        catalog.resolve("toad.nowhere.Nonexistent")


def test_a_second_declaration_saved_under_a_taken_name_fails_as_its_class_is_created():
    class ProbeAction(DeclaredAction[object], affix="Probe"):
        """A family of its own, so the refused member below joins no real registry."""

    with pytest.raises(DuplicateSavedKey, match="'KeymapAction'.*already names"):
        class KeymapClashProbe(ProbeAction):
            saved_key = "KeymapAction"

            def apply(self, context: object) -> None: ...


def test_one_broken_saved_entry_is_kept_and_reported_while_the_rest_apply():
    saved = {"ui": {"keymap": {"bindings": [
        {"declaration": "KeymapAction", "mode": "standard", "keys": ["f1"]},
        {"declaration": "toad.nowhere.Gone", "mode": "standard", "keys": ["f9"]},
    ]}}}
    settings = SavedSettings(saved)
    keymap = settings.current.ui.keymap
    (broken,) = keymap.broken
    assert broken.remap.declaration == "toad.nowhere.Gone" and "Unknown keyboard invocation" in broken.reason
    assert keymap.native() == {KeymapRow.of(KeymapAction(), Standard).binding_id: "f1"}
    # Never silently dropped: the entry is written back as it was saved.
    written = [entry["declaration"] for entry in settings.document()["ui"]["keymap"]["bindings"]]
    assert written == ["KeymapAction", "toad.nowhere.Gone"]
