"""Original filesystem context shared by live and archived rich history."""

from abc import abstractmethod
from pathlib import Path
from textual.widget import Widget


class ProjectPathOwner:
    @classmethod
    def containing(cls, widget: Widget) -> "ProjectPathOwner":
        return next(owner for owner in widget.ancestors_with_self if isinstance(owner, cls))

    @property
    def link_context_events(self):
        return self.core_publications

    def link_context_changed(self):
        from toad.core.events import LinkContextChanged
        self.publish_core(LinkContextChanged())

    def admits_link(self, widget: Widget, root: Path) -> bool:
        return (widget.is_on_screen and widget.screen.is_current
                and self.project_root.resolve() == root)

    @property
    @abstractmethod
    def coordination_root(self) -> str | None: ...

    @property
    @abstractmethod
    def project_root(self) -> Path: ...
