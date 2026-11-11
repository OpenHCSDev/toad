"""The saved hint preference is the native rendering choice, not a second mode flag."""
from toad.hint_labels import FullKeyHintLabels, HintLabels, NextLetterHintLabels
from toad.preferences import SETTINGS, SavedSettings
from toad.setting_declarations import FamilyChoices


def test_hint_labels_default_to_next_letter_and_save_the_full_key_choice():
    settings = SavedSettings({})
    assert settings.current.ui.hint_labels is NextLetterHintLabels
    assert settings.current.ui.hint_labels.caption("as", "a") == "s"
    settings.set(SETTINGS.ui.hint_labels, FullKeyHintLabels)
    reopened = SavedSettings(settings.document())
    assert reopened.current.ui.hint_labels is FullKeyHintLabels
    assert reopened.current.ui.hint_labels.caption("as", "a") == "as"
    assert {FamilyChoices(HintLabels).label(choice) for choice in FamilyChoices(HintLabels).choices()} == {"Next letter", "Full key"}
