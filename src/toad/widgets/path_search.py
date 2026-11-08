from __future__ import annotations


import asyncio
from abc import abstractmethod
from dataclasses import replace
from functools import cached_property

import os
from pathlib import Path

from typing import TYPE_CHECKING, Self, Sequence


from textual import on
from textual.app import ComposeResult
from textual.document._editing import EditingMode
from textual.navigation import MovesCursor
from toad.widget_actions import ForwardsCursor, WidgetAction, PriorityActions, HiddenActions, Submits, DismissAction, SubmitAction, VisibleActions
from textual import work
from textual import getters
from textual import containers
from textual import events
from textual.actions import SkipAction

from textual.reactive import var
from textual.widget import Widget
from textual.content import Content, Span
from textual.css.native import NativeDeclaration, Percent, Variable
from textual.css.styles import Styles
from textual._paint_state import PaintState
from textual.strip import Strip
from textual.style import Style
from textual import widgets
from textual.text_format import TextFormat, TextFormatSnapshot
from textual.visual import RenderOptions
from textual.widgets import OptionList, Input, DirectoryTree
from textual.widgets.option_list import Option
from textual.widgets.input import InputComponent
from textual.widgets.directory_tree import DirEntry
from textual.widgets.tree import TreeNode

from metaclass_registry.mro_dispatch import handles

from toad import directory
from toad.core.events import LinkContextChanged
from toad.core_event_carrier import CoreEventReceiver
from toad.project_path_owner import ProjectPathOwner
from toad.path_search_ranking import PathSearchRanking
from toad.messages import Dismiss, InsertPath, PromptSuggestion
from toad.path_filter import PathFilter
from ui_theme.scheme import ForegroundColour

from toad.native_style import MutedText, SideMargin, SidePadding
from toad.widgets.project_directory_tree import ProjectDirectoryTree
from toad.widgets.prompt_popup import CompletionInput, CompletionOptionList, CompletionPopup


if TYPE_CHECKING:
    from toad.widgets.prompt import Prompt


class PathContent(Content):
    _line_format = TextFormatSnapshot("left", "nowrap", "clip", 0)

    def get_text_format(self, supplied: TextFormat) -> TextFormat:
        return self._line_format

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
                text_format=self.get_text_format(options.text_format),
            ),
        )


class FuzzyPathOptionList(CompletionOptionList):
    """The fuzzy matches; a small list loads with the app's plain indicator, not the screen's."""

    def get_loading_widget(self) -> Widget:
        return self.app.get_loading_widget()


class FuzzyInput(CompletionInput):
    """Adds a Content placeholder to fuzzy input.

    TODO: Add this ability to Textual.
    """

    HELP = """\
## Fuzzy search

Type a few characters from the file you are searching for.

The search is *fuzzy*, and will match characters that aren't neccesarily next to each other—only the order matters.
"""

    def render_line(self, y: int, paint: PaintState) -> Strip:
        if y == 0 and not self.value:
            placeholder = Content.from_markup(self.placeholder).expand_tabs()
            placeholder = placeholder.stylize(paint.visual_style)
            placeholder = placeholder.stylize(
                paint.component_style(self, InputComponent.PLACEHOLDER)
            )
            if self.has_focus:
                cursor_style = paint.component_style(self, InputComponent.CURSOR)
                if self.cursor_shape.draws_cell(self._cursor_visible):
                    # If the placeholder is empty, there's no characters to stylise
                    # to make the cursor flash, so use a single space character
                    if len(placeholder) == 0:
                        placeholder = Content(" ")
                    placeholder = placeholder.stylize(cursor_style, 0, 1)

            strip = Strip(placeholder.render_segments())
            return strip

        return super().render_line(y, paint)


class PickerPane(containers.VerticalGroup):
    """One way of picking a path. The popup shows only the picked pane, and every key,
    submit and suggestion goes to it."""

    @property
    def search(self) -> PathSearch:
        return self.query_ancestor(PathSearch)

    @property
    @abstractmethod
    def toggled(self) -> PickerPane:
        """The pane Tab switches to."""

    @property
    @abstractmethod
    def cursor_owner(self) -> MovesCursor: ...

    @property
    @abstractmethod
    def focus_target(self) -> Widget: ...

    async def prepare(self) -> None:
        """Make this pane ready to be picked."""

    @abstractmethod
    def submit(self) -> None: ...

    def suggest_option(self, option: Option) -> None:
        """A list highlight suggests nothing unless this pane picks from the list."""

    async def suggest_node(self, node: TreeNode[DirEntry]) -> None:
        """A tree highlight suggests nothing unless this pane picks from the tree."""


class FuzzyPane(PickerPane):
    """Fuzzy search over the project's paths."""

    @property
    def toggled(self) -> PickerPane:
        return self.search.query_one(TreePane)

    @property
    def cursor_owner(self) -> FuzzyPathOptionList:
        return self.query_one(FuzzyPathOptionList)

    @property
    def focus_target(self) -> FuzzyInput:
        return self.query_one(FuzzyInput)

    def submit(self) -> None:
        option_list = self.cursor_owner
        if (highlighted := option_list.highlighted) is not None:
            option = option_list.options[highlighted]
            if option.id:
                self.post_message(InsertPath(option.id))
                self.post_message(Dismiss(self.search))

    def suggest_option(self, option: Option) -> None:
        self.post_message(PromptSuggestion(option.id))


class TreePane(PickerPane):
    """The project's directory tree, mounted the first time it is picked."""

    @cached_property
    def mount_lock(self) -> asyncio.Lock:
        return asyncio.Lock()

    @property
    def toggled(self) -> PickerPane:
        return self.search.query_one(FuzzyPane)

    @property
    def cursor_owner(self) -> ProjectDirectoryTree:
        return self.query_one(ProjectDirectoryTree)

    @property
    def focus_target(self) -> ProjectDirectoryTree:
        return self.cursor_owner

    async def prepare(self) -> None:
        async with self.mount_lock:
            if self.query_one_optional(ProjectDirectoryTree) is None:
                tree = PathSearchTree(self.search.root)
                tree.guide_depth = 2
                tree.center_scroll = True
                await self.mount(tree)

    def submit(self) -> None:
        """Enter belongs to the tree, which opens directories and selects files."""
        raise SkipAction()

    async def suggest_node(self, node: TreeNode[DirEntry]) -> None:
        if (dir_entry := node.data) is not None:
            search = self.search
            path = await asyncio.to_thread(search.make_relative, dir_entry.path, search.root)
            self.post_message(PromptSuggestion(str(path)))


class PathSearchTree(SideMargin, ProjectDirectoryTree):
    """The project tree as a path picker, inset under the popup's edge."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.padding = (0, 0, 0, 1)


class PathSearchMessage(MutedText, SideMargin, SidePadding, widgets.Static):
    """The popup's one-line instruction band."""

    native_theme = (NativeDeclaration.of(Styles.background, Variable(ForegroundColour.name), Percent(8)),)



class SwitchPathPickerAction(WidgetAction):
    """Switch between path search and the project tree."""
    keys = {EditingMode: ("tab",)}
    priority = True

    async def apply(self, context: PathSearch) -> None:
        await context.pick(context.picked.toggled)


class PathSearch(
    CoreEventReceiver, PriorityActions, HiddenActions, VisibleActions, ForwardsCursor, Submits, CompletionPopup,
    scopes={HiddenActions: (DismissAction, SubmitAction)},
    actions=(SwitchPathPickerAction,),
):
    requires_completion = True

    BINDING_GROUP_TITLE = "Path search"

    paths: var[list[Path]] = var(list, init=False)
    display_paths: var[list[str]] = var(list)
    picked: PickerPane

    option_list = getters.query_one(FuzzyPathOptionList)
    tree_view = getters.query_one(ProjectDirectoryTree)
    input = getters.query_one(Input)

    def __init__(self) -> None:
        super().__init__()
        self.ranking = PathSearchRanking()
        self._paths_dirty = True

    @classmethod
    def for_prompt(cls, prompt: Prompt) -> Self | None:
        return cls()

    @property
    def root(self) -> Path:
        return ProjectPathOwner.containing(self).project_root

    @on(events.Mount)
    def on_mount(self) -> None:
        self.observe_core(ProjectPathOwner.containing(self).link_context_events)

    @handles(LinkContextChanged)
    def project_changed(self, event: LinkContextChanged) -> None:
        for tree in self.query(ProjectDirectoryTree):
            tree.path = self.root
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

    def compose_content(self) -> ComposeResult:
        with containers.VerticalGroup():
            with FuzzyPane() as self.picked:
                yield FuzzyInput(
                    compact=True, placeholder="fuzzy search \t[r]▌tab▐[/r] tree view"
                )
                yield FuzzyPathOptionList()
            with TreePane() as tree_pane:
                tree_pane.display = False
                yield PathSearchMessage(
                    Content.from_markup(
                        "tree view \t[r]▌tab▐[/] fuzzy search"
                    ).expand_tabs(),
                )

    async def pick(self, pane: PickerPane) -> None:
        """Show and focus one pane; it is picked only once it is ready, so a picked tree is mounted."""
        await pane.prepare()
        self.picked.display = False
        pane.display = True
        self.picked = pane
        pane.focus_target.focus()

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

    @property
    def cursor_owner(self) -> MovesCursor:
        return self.picked.cursor_owner

    def invalidate_paths(self) -> None:
        self._paths_dirty = True
        if self.is_on_screen and self.screen.is_current:
            self.refresh_paths()

    def focus_content(self, scroll_visible: bool) -> None:
        self.input.clear()
        if self._paths_dirty:
            self.refresh_paths()
        self.picked.focus_target.focus(scroll_visible=scroll_visible)

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
        await self.picked.suggest_node(event.node)

    @on(DirectoryTree.FileSelected)
    async def on_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        event.stop()

        dir_entry = event.node.data
        if dir_entry is not None:
            path = await asyncio.to_thread(
                self.make_relative, dir_entry.path, self.root
            )
            tree_path = str(path)
            self.post_message(InsertPath(tree_path))
            self.post_message(Dismiss(self))

    @on(Input.Changed)
    async def on_input_changed(self, event: Input.Changed):
        await self.search(event.value)

    @on(OptionList.OptionHighlighted)
    async def on_option_list_changed(self, event: OptionList.OptionHighlighted):
        event.stop()
        if event.option:
            self.picked.suggest_option(event.option)

    @on(OptionList.OptionSelected)
    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.submit()

    def submit(self) -> None:
        self.picked.submit()

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
            is_directory = path.is_dir()
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
