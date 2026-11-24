from textual._context import active_app
from textual_diff_view import DiffView as NativeDiffView

from toad.block_navigation import ConversationBlock
from toad.client.view_settings import ApplicationSettings


class DiffView(ConversationBlock, NativeDiffView):
    """A native diff shown as one atomic conversation block."""


def make_diff(
    path_original: str,
    path_modified: str,
    code_before: str | None,
    code_after: str | None,
    id: str | None = None,
    classes: str | None = None,
) -> DiffView:
    """Make a diff view widget, configured with app settings."""
    split = False
    annotations = False
    auto_split = False
    wrap = False

    try:
        app = active_app.get()
    except LookupError:
        pass
    else:
        if isinstance(app, ApplicationSettings):
            diff_view_setting = app.settings.diff.view
            split = diff_view_setting.split
            auto_split = diff_view_setting.auto_split
            wrap = app.settings.diff.wrap.enabled
            annotations = app.settings.diff.annotations

    diff_view = DiffView(
        path_original,
        path_modified,
        code_before or "",
        code_after or "",
        classes=classes,
        id=id,
        split=split,
        annotations=annotations,
        auto_split=auto_split,
        wrap=wrap,
    )

    return diff_view
