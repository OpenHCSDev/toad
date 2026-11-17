"""The Qt conversation history inherits the toolkit-neutral parents of Textual's LineHistory.

Every behaviour the two draw differently is a neutral parent one of them skipped (paper1
Corollary 4.10). The parents Qt still lacks are listed here, and the list may only shrink:
adding a neutral parent to LineHistory without giving it to Qt, or giving Qt one without
striking it here, fails.
"""

from toad.qt.history import QtConversationHistory
from toad.widgets.transcript_history import LineHistory

FRONTEND = ("textual", "PySide6", "shiboken6", "toad.widgets", "toad.qt", "toad.core_event_carrier",
            "toad.transcript_source_preparation", "builtins", "abc", "typing")

STILL_MISSING = frozenset({
    "toad.block_navigation.ConversationEntry",
    "toad.frame_presentation.CascadingRows",
    "toad.frame_presentation.UnrisenRows",
    "toad.frame_presentation.AnimationEffects",
    "toad.tone_paint.TonePaint",
    "toad.entry_placement.PostedEntry",
    "toad.block_content.BlockContent",
    "formbridge.navigation_commands.NavigationTarget",
    "metaclass_registry.own_declarations.OwnDeclarations",
    "metaclass_registry.descendants.Descendants",
})


def missing_neutral_parents() -> frozenset[str]:
    qt = set(QtConversationHistory.__mro__)
    return frozenset(f"{parent.__module__}.{parent.__qualname__}" for parent in LineHistory.__mro__
                     if not parent.__module__.startswith(FRONTEND) and parent not in qt)


def test_qt_history_lacks_only_the_listed_neutral_parents():
    assert missing_neutral_parents() == STILL_MISSING
