"""Preference observations identify the original declaration, not another value."""

from dataclasses import dataclass

from toad.settings import SettingKind
from .events import CoreEvent


@dataclass(frozen=True)
class PreferenceChanged(CoreEvent):
    """Read this original setting again after its owned effect was applied."""

    field: SettingKind
