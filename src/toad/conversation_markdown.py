import asyncio
import re
import os
from collections import OrderedDict
from pathlib import Path
from threading import local
from typing import Iterable
from urllib.parse import quote, unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.rules_core import StateCore
from markdown_it.token import Token
from textual.widgets import Markdown
from textual.widgets._markdown import MarkdownBlock


from toad.menus import MenuItem
from toad.layout import trim_trailing_margin
from textual.layout import WidgetPlacement


class ConversationCodeFence(Markdown.BLOCKS["fence"]):

    def get_block_menu(self) -> Iterable[MenuItem]:
        yield from ()

    def get_block_content(self, destination: str) -> str | None:
        if destination == "clipboard":
            return self._content.plain
        return self.source


CUSTOM_BLOCKS = {"fence": ConversationCodeFence}

_PATH_PATTERN = re.compile(
    r"(?<![\w:/])"
    r"(?P<path>(?:(?:~|\.{1,2})?/)?(?:[\w.@+-]+/)+[\w.@+-]+|[\w.@+-]+\.[A-Za-z0-9][\w+-]*)"
    r"(?P<location>:\d+(?::\d+)?)?"
    r"(?![\w/])"
)


def _resolve_path(root: Path, value: str) -> Path | None:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        candidate = candidate.resolve()
        return candidate if candidate.is_file() else None
    except (OSError, RuntimeError):
        return None


def _linked_file(root: Path, href: str) -> Path | None:
    """Resolve an explicit Markdown file link without treating web URLs as files."""
    parsed = urlsplit(href)
    if parsed.scheme == "file":
        if parsed.netloc not in {"", "localhost"}:
            return None
        return _resolve_path(root, unquote(parsed.path))
    if parsed.scheme or parsed.netloc:
        return None
    return _resolve_path(root, unquote(parsed.path)) if parsed.path else None


def _searchable_basename(href: str) -> str | None:
    """Only simple filenames qualify for a deferred, ambiguity-checked lookup."""
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc or parsed.fragment or parsed.query:
        return None
    name = unquote(parsed.path)
    return (name if name and Path(name).name == name and Path(name).suffix
            and not name.startswith(".") else None)


def _unique_project_file(root: Path, name: str) -> tuple[Path | None, str]:
    """Find one project file only when the user actually opens its link.

    Never select the first of several same-named files. The bounded walk skips
    generated/hidden trees and cannot block streaming Markdown parsing.
    """
    if _searchable_basename(name) != name:
        return None, "invalid"
    ignored = {"node_modules", "__pycache__", "dist", "build", "coverage"}
    found: Path | None = None
    directories = files_seen = 0
    try:
        for current, directories_here, files in os.walk(root, followlinks=False):
            directories += 1
            files_seen += len(files)
            if directories > 800 or files_seen > 8000:
                return None, "limit"
            directories_here[:] = [directory for directory in directories_here
                                   if not directory.startswith(".") and directory not in ignored]
            if name not in files:
                continue
            path = _resolve_path(root, str(Path(current) / name))
            if path is None:
                continue
            if found is not None and path != found:
                return None, "ambiguous"
            found = path
    except OSError:
        return None, "unavailable"
    return (found, "found") if found else (None, "missing")


def _file_lookup_notice(name: str, root: Path, reason: str) -> str:
    if reason == "ambiguous":
        return f"Several files named {name} exist under {root}; use a full path."
    if reason == "limit":
        return f"Project file search is too large for {name}; use a full path."
    return f"No project file named {name} found under {root}."


def _path_parser(root: Path) -> MarkdownIt:
    parser = MarkdownIt("gfm-like")

    def link_paths(state: StateCore) -> None:
        for block in state.tokens:
            if block.type != "inline" or block.children is None:
                continue
            linked = 0
            children: list[Token] = []
            for child in block.children:
                if child.type == "link_open":
                    href = str(child.attrs.get("href", ""))
                    if path := _linked_file(root, href):
                        child.attrs["href"] = f"toad-file:{quote(str(path))}"
                    elif name := _searchable_basename(href):
                        child.attrs["href"] = f"toad-file-search:{quote(name)}"
                    linked += 1
                    children.append(child)
                    continue
                if child.type == "link_close":
                    linked -= 1
                    children.append(child)
                    continue
                if linked or child.type not in {"text", "code_inline"}:
                    children.append(child)
                    continue
                matches = list(_PATH_PATTERN.finditer(child.content))
                if child.type == "code_inline":
                    matches = [
                        match
                        for match in matches
                        if match.start() == 0 and match.end() == len(child.content)
                    ]
                position = 0
                for match in matches:
                    path = _resolve_path(root, match.group("path"))
                    if path is None:
                        name = _searchable_basename(match.group("path"))
                        if name is None:
                            continue
                        href = f"toad-file-search:{quote(name)}"
                    else:
                        href = f"toad-file:{quote(str(path))}"
                    if match.start() > position:
                        children.append(Token("text", "", 0, content=child.content[position:match.start()]))
                    children.append(
                        Token(
                            "link_open",
                            "a",
                            1,
                            attrs={"href": href},
                        )
                    )
                    if child.type == "code_inline":
                        children.append(child)
                    else:
                        children.append(Token("text", "", 0, content=match.group(0)))
                    children.append(Token("link_close", "a", -1))
                    position = match.end()
                if position:
                    if position < len(child.content):
                        children.append(Token("text", "", 0, content=child.content[position:]))
                else:
                    children.append(child)
            block.children = children

    parser.core.ruler.after("inline", "toad_file_paths", link_paths)
    return parser


class _PathParserState(local):
    def __init__(self) -> None:
        self.parsers: OrderedDict[Path, MarkdownIt] = OrderedDict()


_parser_state = _PathParserState()


class _ThreadLocalPathParser:
    """Resolve reusable parser machinery on the thread doing the actual parse.

    Markdown creates its parser on the UI thread but can execute parse() in an
    executor. Sharing the parser returned by a UI-thread cache would therefore
    race linkifier state. This facade holds only an immutable project path;
    actual parsers are thread-local and bounded across project changes.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def parse(self, source: str, env: dict | None = None) -> list[Token]:
        parsers = _parser_state.parsers
        parser = parsers.get(self.root)
        if parser is None:
            parser = parsers[self.root] = _path_parser(self.root)
            if len(parsers) > 8:
                parsers.popitem(last=False)
        parsers.move_to_end(self.root)
        return parser.parse(source, env)


class ConversationMarkdown(Markdown):
    """Markdown widget with custom blocks."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("parser_factory", self._make_parser)
        kwargs.setdefault("open_links", False)
        super().__init__(*args, **kwargs)

    def _make_parser(self) -> _ThreadLocalPathParser:
        project = Path(getattr(self.screen, "project_path", Path.cwd()))
        return _ThreadLocalPathParser(project.resolve())

    async def on_markdown_link_clicked(self, event: Markdown.LinkClicked) -> None:
        screen = self.screen
        root = Path(getattr(screen, "project_path", Path.cwd())).resolve()
        if event.href.startswith("toad-file:"):
            path = Path(unquote(event.href.removeprefix("toad-file:")))
        elif event.href.startswith("toad-file-search:"):
            name = unquote(event.href.removeprefix("toad-file-search:"))
            path, status = await asyncio.to_thread(_unique_project_file, root, name)
            if path is None:
                self.notify(_file_lookup_notice(name, root, status),
                            title="File preview", severity="warning")
                return
        elif path := _linked_file(root, event.href):
            pass
        elif (urlsplit(event.href).scheme in {"", "file"}
              and Path(urlsplit(event.href).path).suffix):
            self.notify(f"File not found: {event.href} (project: {root})",
                        title="File preview", severity="warning")
            return
        else:
            self.app.open_url(event.href)
            return
        event.stop()
        open_preview = getattr(screen, "open_file_preview", None)
        if open_preview is None:
            open_preview = self.app.open_file_preview
        await open_preview(path)

    def process_layout(self, placements: list[WidgetPlacement]) -> list[WidgetPlacement]:
        return trim_trailing_margin(placements)

    def get_block_class(self, block_name: str) -> type[MarkdownBlock]:
        if (custom_block := CUSTOM_BLOCKS.get(block_name)) is not None:
            return custom_block
        return super().get_block_class(block_name)
