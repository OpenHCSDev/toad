"""Original filesystem context shared by live and archived rich history."""

from abc import abstractmethod
from pathlib import Path
from textual.widget import Widget


class ProjectPathOwner:
    @classmethod
    def containing(cls, widget: Widget) -> "ProjectPathOwner":
        return next(owner for owner in widget.ancestors if isinstance(owner, cls))

    @property
    @abstractmethod
    def project_root(self) -> Path: ...
