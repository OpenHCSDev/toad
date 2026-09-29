"""Nominal selection capabilities on the actual mounted block widgets."""
from collections.abc import Iterable

from toad.menus import MenuItem


class BlockContent:
    """Non-interactive blocks inherit empty content and expansion behavior."""

    def get_block_menu(self) -> Iterable[MenuItem]:
        return ()

    def get_clipboard_text(self) -> str | None:
        return None

    def get_prompt_text(self) -> str | None:
        return self.get_clipboard_text()

    def can_expand(self) -> bool | None:
        return None

    def is_block_expanded(self) -> bool:
        return False

    def expand_block(self) -> None:
        pass

    def collapse_block(self) -> None:
        pass


class MarkdownBlockContent(BlockContent):
    """Textual's Markdown block factory admits these capabilities once."""

    def get_clipboard_text(self) -> str:
        return self.source

    @classmethod
    def declare(cls, external: type) -> type:
        # Keep Textual's existing token catalog and concrete rendering classes.
        # The mounted class itself owns the capability, without a widget wrapper.
        return type(external.__name__, (cls, external), {"__module__": __name__})
