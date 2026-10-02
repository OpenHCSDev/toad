"""Project links own their encoding, resolution and native user effects."""

from __future__ import annotations

import asyncio
import os
from abc import abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import ClassVar
from urllib.parse import SplitResult, quote, unquote, urlsplit

from agent_comms.declared_family import DeclaredFamily
from markdown_it.token import Token


class ProjectLinkProblem(Exception):
    def __init__(self, name: str, root: Path) -> None:
        self.name = name
        self.root = root
        super().__init__(self.notice)

    @property
    def notice(self) -> str:
        return f"No project file named {self.name} found under {self.root}."

    def notify(self, widget) -> None:
        widget.notify(self.notice, title="File preview", severity="warning")


class AmbiguousProjectFile(ProjectLinkProblem):
    @property
    def notice(self) -> str:
        return f"Several files named {self.name} exist under {self.root}; use a full path."


class ProjectSearchLimit(ProjectLinkProblem):
    @property
    def notice(self) -> str:
        return f"Project file search is too large for {self.name}; use a full path."


class EncodedProjectLink:
    """Membership in the internal URI protocol derives from declarations."""

    @classmethod
    @abstractmethod
    def from_uri(cls, uri: SplitResult) -> ProjectLink: ...


class ProjectLink(DeclaredFamily, affix="Link"):
    @classmethod
    def from_href(cls, project_root: Callable[[], Path], href: str) -> ProjectLink:
        """Decode URI syntax once, including the external file/relative grammar."""
        uri = urlsplit(href)
        for declaration in cls.members_with(EncodedProjectLink):
            if uri.scheme == declaration.declared_name:
                return declaration.from_uri(uri)
        if uri.scheme == "file":
            if uri.netloc not in {"", "localhost"}:
                return ExternalProjectLink(href)
        elif uri.scheme or uri.netloc:
            return ExternalProjectLink(href)
        root = project_root()
        value = unquote(uri.path)
        try:
            return DirectProjectFileLink(cls.existing_file(root, value))
        except ProjectLinkProblem:
            pass
        if not (uri.scheme or uri.fragment or uri.query) and SearchProjectFileLink.accepts(value):
            return SearchProjectFileLink(value)
        if Path(uri.path).suffix:
            return MissingProjectFileLink(href)
        return ExternalProjectLink(href)

    @classmethod
    def from_path(cls, root: Path, value: str) -> ProjectLink:
        """Plain token paths are filesystem spellings, never URI-decoded twice."""
        try:
            return DirectProjectFileLink(cls.existing_file(root, value))
        except ProjectLinkProblem:
            pass
        if SearchProjectFileLink.accepts(value):
            return SearchProjectFileLink(value)
        return ExternalProjectLink(value)

    @staticmethod
    def existing_file(root: Path, value: str) -> Path:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            candidate = candidate.resolve()
            if candidate.is_file():
                return candidate
        except (OSError, RuntimeError) as error:
            raise ProjectLinkProblem(value, root) from error
        raise ProjectLinkProblem(value, root)

    @property
    @abstractmethod
    def href(self) -> str: ...

    def inline_tokens(self, content: Token) -> tuple[Token, ...]:
        return ()

    @abstractmethod
    async def preview(self, widget, event) -> None: ...

    async def copy_menu(self, widget, event) -> bool:
        return False


class ProjectFileLink(ProjectLink):
    @abstractmethod
    async def resolve(self, root: Path) -> Path: ...

    def inline_tokens(self, content: Token) -> tuple[Token, ...]:
        return (Token("link_open", "a", 1, attrs={"href": self.href}),
                content, Token("link_close", "a", -1))

    async def preview(self, widget, event) -> None:
        await self.apply_file(widget, event, partial(self.preview_file, widget))

    async def copy_menu(self, widget, event) -> bool:
        await self.apply_file(widget, event, partial(self.copy_file, widget, event))
        return True

    async def apply_file(self, widget, event, effect: Callable[[Path], None]) -> None:
        from toad.project_path_owner import ProjectPathOwner

        owner = ProjectPathOwner.containing(widget)
        root = owner.project_root.resolve()
        event.stop()
        try:
            path = await self.resolve(root)
        except ProjectLinkProblem as problem:
            if owner.admits_link(widget, root):
                problem.notify(widget)
            return
        if owner.admits_link(widget, root):
            effect(path)

    def preview_file(self, widget, path: Path) -> None:
        # Navigation may retire this pump; finish it before changing the view.
        widget.app.run_worker(partial(widget.app.session_navigation.preview, path))

    def copy_file(self, widget, event, path: Path) -> None:
        from toad.widgets.comms_menu import show_target_menu

        full_path = str(path)
        event.prevent_default()
        show_target_menu(widget.screen, event.screen_offset, full_path,
                         [("copy_path", "Copy full path")],
                         {"copy_path": partial(widget.app.copy_to_clipboard, full_path)})


@dataclass(frozen=True)
class DirectProjectFileLink(EncodedProjectLink, ProjectFileLink, declared_name="toad-file"):
    path: Path

    @classmethod
    def from_uri(cls, uri: SplitResult) -> DirectProjectFileLink:
        return cls(Path(unquote(uri.path)))

    @property
    def href(self) -> str:
        return f"{self.declared_name}:{quote(str(self.path))}"

    async def resolve(self, root: Path) -> Path:
        return self.existing_file(root, str(self.path))


@dataclass(frozen=True)
class SearchProjectFileLink(EncodedProjectLink, ProjectFileLink, declared_name="toad-file-search"):
    name: str

    directory_limit: ClassVar[int] = 800
    file_limit: ClassVar[int] = 8000
    excluded_directories: ClassVar[frozenset[str]] = frozenset(
        {"node_modules", "__pycache__", "dist", "build", "coverage"}
    )

    @staticmethod
    def accepts(name: str) -> bool:
        return bool(name and Path(name).name == name and Path(name).suffix
                    and not name.startswith("."))

    @classmethod
    def from_uri(cls, uri: SplitResult) -> SearchProjectFileLink:
        return cls(unquote(uri.path))

    @property
    def href(self) -> str:
        return f"{self.declared_name}:{quote(self.name)}"

    async def resolve(self, root: Path) -> Path:
        return await asyncio.to_thread(self.search, root)

    def search(self, root: Path) -> Path:
        if not self.accepts(self.name):
            raise ProjectLinkProblem(self.name, root)
        found: set[Path] = set()
        directories = files_seen = 0
        try:
            for current, children, files in os.walk(root, followlinks=False):
                directories += 1
                files_seen += len(files)
                if directories > self.directory_limit or files_seen > self.file_limit:
                    raise ProjectSearchLimit(self.name, root)
                children[:] = [name for name in children
                               if not name.startswith(".") and name not in self.excluded_directories]
                if self.name in files:
                    try:
                        path = self.existing_file(root, str(Path(current) / self.name))
                    except ProjectLinkProblem:
                        continue
                    found.add(path)
                    if len(found) > 1:
                        raise AmbiguousProjectFile(self.name, root)
        except OSError as error:
            raise ProjectLinkProblem(self.name, root) from error
        if not found:
            raise ProjectLinkProblem(self.name, root)
        return next(iter(found))


@dataclass(frozen=True)
class MissingProjectFileLink(ProjectFileLink):
    value: str

    @property
    def href(self) -> str:
        return self.value

    async def resolve(self, root: Path) -> Path:
        raise ProjectLinkProblem(self.href, root)


@dataclass(frozen=True)
class ExternalProjectLink(ProjectLink):
    value: str

    @property
    def href(self) -> str:
        return self.value

    async def preview(self, widget, event) -> None:
        widget.app.open_url(self.href)
