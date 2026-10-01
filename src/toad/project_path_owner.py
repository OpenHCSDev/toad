"""Original filesystem context shared by live and archived rich history."""

from abc import abstractmethod
from pathlib import Path
from textual.widget import Widget


class ProjectPathOwner:
    @classmethod
    def containing(cls, widget: Widget) -> "ProjectPathOwner":
        return next(owner for owner in widget.ancestors_with_self if isinstance(owner, cls))

    @classmethod
    def link_from(cls, widget: Widget, href: str):
        from toad.project_link import ProjectLink
        return ProjectLink.from_href(lambda: cls.containing(widget).project_root.resolve(), href)

    def admits_link(self, widget: Widget, root: Path) -> bool:
        return (widget.is_on_screen and widget.screen.is_current
                and self.project_root.resolve() == root)

    @property
    @abstractmethod
    def project_root(self) -> Path: ...
