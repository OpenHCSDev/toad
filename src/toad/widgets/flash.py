from typing import Literal

from textual.content import Content
from textual.reactive import var
from textual.widgets import Static
from textual.timer import Timer
from textual import getters


from toad.app import ToadApp


class Flash(Static):
    DEFAULT_CSS = """
    Flash {
        height: 1;
        width: 1fr;
        background: $success 10%;
        color: $text-success;
        text-align: center;
        text-wrap: nowrap;
        text-overflow: ellipsis;     
        &.-default {
            background: $primary 10%;
            color: $text-primary;
        }
        
        &.-success {
            background: $success 10%;
            color: $text-success;
        }
        
        
        &.-warning {
            background: $warning 10%;
            color: $text-warning;
        }

        &.-error {
            background: $error 10%;
            color: $text-error;
        }
        &:ansi {
            background: ansi_bright_white;
            color: ansi_black;
            text-style: bold;
        }
    }
    """
    app = getters.app(ToadApp)
    flash_timer: var[Timer | None] = var(None)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.display = False

    def flash(
        self,
        content: str | Content,
        *,
        duration: float | None = None,
        style: Literal["default", "success", "warning", "error"] = "default",
    ) -> None:
        """Flash the content for a brief period.

        Args:
            content: Content to show.
            duration: Duration in seconds to show content.
            style: A semantic style.
        """
        if self.flash_timer is not None:
            self.flash_timer.stop()
        self.display = False

        def hide() -> None:
            """Hide the content without reserving a transcript row."""
            self.display = False

        self.update(content)
        self.remove_class("-default", "-success", "-warning", "-error", update=False)
        self.add_class(f"-{style}")
        self.display = True

        if duration is None:
            duration = self.app.settings.ui.flash_duration

        self.flash_timer = self.set_timer(duration or 3, hide)
