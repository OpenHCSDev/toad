"""Saved hint-label choices compose Textual's native presentation."""
from agent_comms.nominal.declared_choice import DeclaredChoice, TitledChoice
from textual.hint_labels import FullKeyHints, HintLabelStyle, NextLetterHints


class HintLabels(DeclaredChoice, HintLabelStyle, affix="HintLabels"):
    """The native caption behavior is also the saved settings choice."""


class NextLetterHintLabels(TitledChoice, NextLetterHints, HintLabels):
    title = "Next letter"


class FullKeyHintLabels(TitledChoice, FullKeyHints, HintLabels):
    title = "Full key"
