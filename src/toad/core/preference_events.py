"""A setting changed: which one, named through its declaration."""

from dataclasses import dataclass

from toad.forms.field_path import FieldPath
from .events import CoreEvent


@dataclass(frozen=True)
class PreferenceChanged(CoreEvent):
    """Read this setting again; what the app does on the change has been done."""

    path: FieldPath
