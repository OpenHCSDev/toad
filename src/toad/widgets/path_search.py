from __future__ import annotations


import asyncio
from dataclasses import replace

import os
from pathlib import Path

from typing import TYPE_CHECKING, Self, Sequence


from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual import work
from textual import getters
from textual import containers
from textual import events
from textual.actions import SkipAction

from textual.reactive import var
from textual.content import Content, Span
from textual.strip import Strip
from textual.style import Style
from textual.widget import Widget
from textual import widgets
from textual.visual import RenderOptions
from textual.widgets import OptionList, Input, DirectoryTree
from textual.widgets.option_list import Option

from toad import directory
from toad.path_search_ranking import PathSearchRanking
from toad.messages import Dismiss, InsertPath, PromptSuggestion
from toad.path_filter import PathFilter
from toad.widgets.project_directory_tree import ProjectDirectoryTree
from toad.widgets.selection import SelectionOptionList
from toad.widgets.prompt_popup import CompletionPopup


if TYPE_CHECKING:
    from toad.widgets.prompt import Prompt


class PathContent(Content):

    def render_strips(
        self, width: int, height: int | None, style: Style, options: RenderOptions
    ) -> list[Strip]:
        """Render the Visual into an iterable of strips. Part of the Visual protocol.

        Args:
            width: Width of desired render.
            height: Height of desired render or `None` for any height.
            style: The base style to render on top of.
            options: Additional render options.

        Returns:
            An list of Strips.
        """
        if not width:
            return []

        line = self
        if line.cell_length > width:
            while line.cell_length >= width - 3 and "/" in line.plain:
                line = line[line.plain.find("/") + 1 :]
            line = Content.assemble(("⋯ ", "$text-error"), line)

        return Content.render_strips(
            line,
            width,
            height,
            style,
            replace(
                options,
                rules={
                    "text_wrap": "nowrap",
                    "text_overflow": "clip",
                    "text_align": "left",
                    "line_pad": 0,
                },
            ),
        )


class FuzzyPathOptionList(SelectionOptionList):
    """Option list with loading indicator override."""

    def get_loading_widget(self) -> Widget:
        from textual.widgets import LoadingIndicator

        return LoadingIndicator()


class FuzzyInput(Input):
    """Adds a Content placeholder to fuzzy input.

    TODO: Add this ability to Textual.
    """

    HELP = """\
## Fuzzy search

Type a few characters from the file you are searching for.

The search is *fuzzy*, and will match characters that aren't neccesarily next to each other—only the order matters.
"""

    def render_line(self, y: int) -> Strip:
        if y == 0 and not self.value:
            placeholder = Content.from_markup(self.placeholder).expand_tabs()
            placeholder = placeholder.stylize(self.visual_style)
            placeholder = placeholder.stylize(
                self.get_visual_style("input--placeholder")
            )
            if self.has_focus:
                cursor_style = self.get_visual_style("input--cursor")
                if self._cursor_visible:
                    # If the placeholder is empty, there's no characters to stylise
                    # to make the cursor flash, so use a single space character
                    if len(placeholder) == 0:
                        placeholder = Content(" ")
                    placeholder = placeholder.stylize(cursor_style, 0, 1)

            strip = Strip(placeholder.render_segments())
            return strip

        return super().render_line(y)


class PathSearch(CompletionPopup):

    BINDING_GROUP_TITLE = "Path search"

    CURSOR_BINDING_GROUP = Binding.Group(description="Move selection")
    BINDINGS = [
        Binding(
            "up", "cursor_up", "Cursor up", group=CURSOR_BINDING_GROUP, priority=True
        ),
        Binding(
            "down",
            "cursor_down",
            "Cursor down",
            group=CURSOR_BINDING_GROUP,
            priority=True,
        ),
        Binding("enter", "submit", "Insert path", priority=True, show=False),
        Binding("escape", "dismiss", "Dismiss", priority=True, show=False),
        Binding("tab", "switch_picker", "Switch picker", priority=True, show=False),
    ]

    root: var[Path] = var(Path("./"))
    paths: var[list[Path]] = var(list)
    display_paths: var[list[str]] = var(list)
    show_tree_picker: var[bool] = var(False)

    option_list = getters.query_one(FuzzyPathOptionList)
    tree_view = getters.query_one(ProjectDirectoryTree)
    input = getters.query_one(Input)

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.set_reactive(PathSearch.root, root)
        self.root = root
        self.ranking = PathSearchRanking()
        self._paths_dirty = True
        self._tree_mount_lock = asyncio.Lock()

    @classmethod
    def for_prompt(cls, prompt: Prompt) -> Self | None:
        from toad.widgets.prompt import Prompt
        return None if prompt.simple_input else cls(prompt.project_path).data_bind(root=Prompt.project_path)

    def admitted(self) -> bool:
        return self.prompt.supports_completion

    def watch_root(self) -> None:
        self.invalidate_paths()

    @on(PromptSuggestion)
    def suggest_path(self, event: PromptSuggestion) -> None:
        event.stop()
        if self.is_open:
            self.prompt.prompt_text_area.suggestion = event.suggestion

    @on(InsertPath)
    def insert_path(self, event: InsertPath) -> None:
        event.stop()
        area = self.prompt.prompt_text_area
        if " " in event.path:
            path = f'"{event.path}"'
        else:
            path = event.path
            if area.get_text_range(*area.selection) != " ":
                path += " "
        area.insert(path)

    def compose(self) -> ComposeResult:
        with widgets.ContentSwitcher(initial="path-search-fuzzy"):
            with containers.VerticalGroup(id="path-search-fuzzy"):
                yield FuzzyInput(
                    compact=True, placeholder="fuzzy search \t[r]▌tab▐[/r] tree view"
                )
                yield FuzzyPathOptionList()
            with containers.VerticalGroup(id="path-search-tree"):
                yield widgets.Static(
                    Content.from_markup(
                        "tree view \t[r]▌tab▐[/] fuzzy search"
                    ).expand_tabs(),
                    classes="message",
                )

    async def watch_show_tree_picker(self, show_tree_picker: bool) -> None:
        content_switcher = self.query_one(widgets.ContentSwitcher)
        content_switcher.current = (
            "path-search-tree" if show_tree_picker else "path-search-fuzzy"
        )
        if show_tree_picker:
            async with self._tree_mount_lock:
                if self.query_one_optional(ProjectDirectoryTree) is None:
                    tree = ProjectDirectoryTree(self.root).data_bind(path=PathSearch.root)
                    tree.guide_depth = 2
                    tree.center_scroll = True
                    await self.query_one("#path-search-tree").mount(tree)
            if self.show_tree_picker:
                self.tree_view.focus()

        else:
            self.input.focus()

    def action_switch_picker(self) -> None:
        self.show_tree_picker = not self.show_tree_picker

    async def search(self, search: str) -> None:
        if not search:
            self.option_list.set_options(
                [
                    Option(self.highlight_path(path), path)
                    for path in self.display_paths[:100]
                ],
            )
            return

        scored_paths = await self.ranking.search(search)

        scores = [
            (match.score, match.offsets, self.highlight_path(match.path))
            for match in scored_paths[:30]
        ]

        def highlight_offsets(path: Content, offsets: Sequence[int]) -> Content:
            highlighted_path = path.add_spans(
                [Span(offset, offset + 1, "underline") for offset in offsets]
            )
            return PathContent(
                highlighted_path.plain,
                list(highlighted_path.spans),
                highlighted_path.cell_length,
            )

        self.option_list.set_options(
            [
                Option(highlight_offsets(path, offsets), id=path.plain)
                for index, (score, offsets, path) in enumerate(scores)
            ]
        )
        with self.option_list.prevent(OptionList.OptionHighlighted):
            self.option_list.highlighted = 0
        self.post_message(PromptSuggestion(""))

    def action_cursor_down(self) -> None:
        if self.show_tree_picker:
            if tree := self.query_one_optional(ProjectDirectoryTree):
                tree.action_cursor_down()
        else:
            self.option_list.action_cursor_down()

    def action_cursor_up(self) -> None:
        if self.show_tree_picker:
            if tree := self.query_one_optional(ProjectDirectoryTree):
                tree.action_cursor_up()
        else:
            self.option_list.action_cursor_up()

    def invalidate_paths(self) -> None:
        self._paths_dirty = True
        if self.is_on_screen and self.screen is self.app.screen:
            self.refresh_paths()

    def focus_content(self, scroll_visible: bool) -> None:
        self.input.clear()
        if self._paths_dirty:
            self.refresh_paths()
        if self.show_tree_picker and (tree := self.query_one_optional(ProjectDirectoryTree)):
            tree.focus(scroll_visible=scroll_visible)
        else:
            self.input.focus(scroll_visible=scroll_visible)

    @classmethod
    def make_relative(cls, path: Path, root: Path) -> Path:
        """Make a path relative from the root.

        Args:
            path: Path to consider.
            root: Root path.

        Returns:
            A relative path.
        """
        return path.resolve().relative_to(root.resolve())

    @on(DirectoryTree.NodeHighlighted)
    async def on_node_highlighted(self, event: DirectoryTree.NodeHighlighted) -> None:
        event.stop()
        if not self.show_tree_picker:
            return

        dir_entry = event.node.data
        if dir_entry is not None:
            try:
                path = await asyncio.to_thread(
                    self.make_relative, dir_entry.path, self.root
                )
            except ValueError:
                # Being defensive here, shouldn't occur
                return
            tree_path = str(path)
            self.post_message(PromptSuggestion(tree_path))

    @on(DirectoryTree.FileSelected)
    async def on_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        event.stop()

        dir_entry = event.node.data
        if dir_entry is not None:
            try:
                path = await asyncio.to_thread(
                    self.make_relative, dir_entry.path, self.root
                )
            except ValueError:
                return
            tree_path = str(path)
            self.post_message(InsertPath(tree_path))
            self.post_message(Dismiss(self))

    @on(Input.Changed)
    async def on_input_changed(self, event: Input.Changed):
        await self.search(event.value)

    @on(OptionList.OptionHighlighted)
    async def on_option_list_changed(self, event: OptionList.OptionHighlighted):
        event.stop()
        if event.option and not self.show_tree_picker:
            self.post_message(PromptSuggestion(event.option.id))

    @on(OptionList.OptionSelected)
    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.action_submit()

    def action_submit(self):
        if self.show_tree_picker:
            raise SkipAction()

        elif (highlighted := self.option_list.highlighted) is not None:
            option = self.option_list.options[highlighted]
            if option.id:
                self.post_message(InsertPath(option.id))
                self.post_message(Dismiss(self))

    @work(exclusive=True)
    async def refresh_paths(self):
        self._paths_dirty = False
        self.option_list.set_loading(True)
        root = self.root
        try:
            path_filter = await asyncio.to_thread(PathFilter.from_git_root, root)
            if tree := self.query_one_optional(ProjectDirectoryTree):
                tree.path_filter = path_filter
                tree.invalidate()
            paths = await directory.scan(
                root, path_filter=path_filter, add_directories=True
            )

            def make_absolute(paths: list[Path]) -> list[Path]:
                """Make all paths absolute.

                Args:
                    paths: A list of paths.

                Returns:
                    List of absolute paths,

                """
                return [path.absolute() for path in paths]

            paths = await asyncio.to_thread(make_absolute, paths)
            if self.root != root:
                return
            self.paths = paths
        except Exception:
            self.option_list.set_loading(False)
            raise

    def highlight_path(self, path: str) -> PathContent:
        content = Content.styled(path, "$text 50%")
        if os.path.split(path)[-1].startswith("."):
            return PathContent(
                content.plain, list(content.spans), cell_length=content.cell_length
            )
        content = content.highlight_regex("[^/]*?$", style="$text-primary")
        content = content.highlight_regex(r"\.[^/]*$", style="italic")
        return PathContent(
            content.plain, list(content.spans), cell_length=content.cell_length
        )

    @work(description="watch_paths")
    async def watch_paths(self, paths: list[Path]) -> None:

        def path_display(path: Path) -> str:
            try:
                is_directory = path.is_dir()
            except OSError:
                is_directory = False
            if is_directory:
                return str(path.relative_to(self.root)) + "/"
            else:
                return str(path.relative_to(self.root))

        def make_display_paths() -> list[str]:
            display_paths = sorted(map(path_display, paths), key=str.lower)
            display_paths.sort(key=lambda path: path.count("/"))
            return display_paths

        self.display_paths = await asyncio.to_thread(make_display_paths)

        self.option_list.highlighted = None
        self._update_paths(self.display_paths)

        self.option_list.set_options(
            [
                Option(self.highlight_path(path), id=path)
                for path in self.display_paths[:100]
            ]
        )
        with self.option_list.prevent(OptionList.OptionHighlighted):
            self.option_list.highlighted = 0

        self.post_message(PromptSuggestion(""))

    @work(description="update_paths")
    async def _update_paths(self, paths: list[str]) -> None:
        """Update the paths index.

        Args:
            paths: A list of paths.
        """
        await self.ranking.update_paths(paths)
        self.call_after_refresh(self.option_list.set_loading, False)
