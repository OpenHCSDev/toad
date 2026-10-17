from textual_diff_view import DiffView as NativeDiffView
from toad.block_navigation import ConversationBlock


class DiffView(ConversationBlock, NativeDiffView):
    """A native diff admitted as one atomic conversation block."""


from toad.app import ToadApp


def make_diff(
    path_original: str,
    path_modified: str,
    code_before: str | None,
    code_after: str | None,
    id: str | None = None,
    classes: str | None = None,
) -> DiffView:
    """Make a diff view widget, configured with app settings.

    Args:
        app: Instance of the app.
        path_original: Path to the original file.
        path_modified: Path to the modified file.,
        code_before: Original code.
        code_after: Modified code.
        id: Textual CSS ID.
        classes: Textual CSS classses.

    Returns:
        A diff view widget.
    """
    split = False
    annotations = False
    auto_split = False
    wrap = False
    from textual._context import active_app

    try:
        app = active_app.get()
    except LookupError:
        pass
    else:
        if isinstance(app, ToadApp):
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
