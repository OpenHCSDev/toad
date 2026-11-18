"""The app's name, drawn large: the welcome draws it, and so does Qt's first frame.

It has a module of its own, importing nothing, because Qt paints it before the client loads
(`toad.qt.splash`): the welcome's module reads Core's sidebar model, which is part of what
loading the client costs."""

from __future__ import annotations


class WelcomeBanner:
    """The app's name, drawn large on the welcome."""

    TEXT = "\n".join(
        (
            " ██████╗ ██████╗ ███╗   ███╗███╗   ███╗███████╗",
            "██╔════╝██╔═══██╗████╗ ████║████╗ ████║██╔════╝",
            "██║     ██║   ██║██╔████╔██║██╔████╔██║███████╗",
            "██║     ██║   ██║██║╚██╔╝██║██║╚██╔╝██║╚════██║",
            "╚██████╗╚██████╔╝██║ ╚═╝ ██║██║ ╚═╝ ██║███████║",
            " ╚═════╝ ╚═════╝ ╚═╝     ╚═╝╚═╝     ╚═╝╚══════╝",
        )
    )
