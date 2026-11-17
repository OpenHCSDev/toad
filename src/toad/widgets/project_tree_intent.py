"""Back-compat re-export: `ProjectTreeIntent`, `TreeIntent`, `NO_TREE_INTENT` and
`ProjectTreeOwner` live in `toad.client.project_tree_intent` so Qt can read and apply
intents without pulling the Textual geometry types. The Textual tree
(`ProjectDirectoryTree`) implements `ProjectTreeOwner`; the Qt tree
(`QtProjectPanel`) does the same. The capture/restore algorithm is the single owner
of what makes an intent and how it is applied.
"""
from __future__ import annotations

from toad.client.project_tree_intent import (
    NO_TREE_INTENT,
    ProjectTreeIntent,
    ProjectTreeOwner,
    TreeIntent,
)

__all__ = ["NO_TREE_INTENT", "ProjectTreeIntent", "ProjectTreeOwner", "TreeIntent"]
