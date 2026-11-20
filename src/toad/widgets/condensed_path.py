import os.path

from textual.geometry import Size
from textual.reactive import reactive
from textual.content import Content

from toad.client.condensed_path import condense_path, home_relative
from toad.native_style import OneRow
from textual.events import Resize
from textual import on


class CondensedPath(OneRow):
    path = reactive("")
    display_path = reactive("")


    def __init__(
        self,
        path: str = "",
        *,
        directory: bool = False,
    ) -> None:
        super().__init__()
        self.set_reactive(CondensedPath.path, path)
        self._directory = directory

    @on(Resize)
    def on_resize(self) -> None:
        self.watch_path(self.path)

    def watch_path(self, path: str) -> None:
        if not path or not self.size.width:
            return
        if not self.tooltip:
            self.tooltip = os.path.abspath(os.path.expanduser(path))
        self.display_path = home_relative(path, directory=self._directory)

    def render(self) -> Content:
        self.watch_path(self.path)
        return Content(condense_path(self.display_path, self.size.width))

    def get_content_width(self, container: Size, viewport: Size) -> int:
        if self.display_path:
            return Content(self.display_path).cell_length
        else:
            return container.width
