"""Declared block capabilities shared by scene and original source consumers."""
from collections.abc import Iterable
from functools import cached_property

from textual.widgets import _markdown as native_markdown

from toad.menus import MenuItem


class BlockContent:
    """Non-interactive blocks inherit empty content and expansion behavior."""

    def retain_transcript_source(self, fragment):
        """Native content without acquired Markdown has no source to transfer."""

    @cached_property
    def block_cursor(self):
        from toad.block_navigation import AtomicBlockCursor

        return AtomicBlockCursor(self)

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
    """Declared native blocks share source-copy and menu capabilities."""

    code: str | None = None

    @classmethod
    def clipboard_source(cls, markdown: str | None, code: str | None) -> str | None:
        return markdown

    @classmethod
    def prompt_source(cls, markdown: str | None, code: str | None) -> str | None:
        return cls.clipboard_source(markdown, code)

    @classmethod
    def source_block_menu(cls, source) -> Iterable[MenuItem]:
        # A scene menu may depend on actual controls. It must explicitly
        # declare source behavior before detached consumers can supply it.
        cls._require_document_methods({"get_block_menu": BlockContent.get_block_menu})
        return ()

    @classmethod
    def source_copy(cls, source, *, prompt: bool = False) -> str | None:
        cls._require_document_methods({
            "get_clipboard_text": MarkdownBlockContent.get_clipboard_text,
            "get_prompt_text": MarkdownBlockContent.get_prompt_text,
        })
        supply = cls.prompt_source if prompt else cls.clipboard_source
        return supply(source.source_text(), source.code)

    def get_clipboard_text(self) -> str | None:
        return self.clipboard_source(self.source, self.code)

    def get_prompt_text(self) -> str | None:
        return self.prompt_source(self.source, self.code)

    @classmethod
    def blocks_for(cls, catalog: dict[str, type]) -> dict[str, type]:
        """Extend the original token catalog through declared inheritance.

        The native owner decides which token selects which block. These
        declarations add capabilities and stable Python identities; neither
        token names nor a transport codec select an implementation here.
        """
        native = set(catalog.values())
        implementations = {}
        for declaration in cls.__subclasses__():
            for base in declaration.__bases__:
                if base in native:
                    if base in implementations:
                        raise TypeError(f"Multiple declared block extensions for {base.__name__}")
                    implementations[base] = declaration
        return {token: implementations[block] for token, block in catalog.items()}


class MarkdownH1(MarkdownBlockContent, native_markdown.MarkdownH1):
    pass


class MarkdownH2(MarkdownBlockContent, native_markdown.MarkdownH2):
    pass


class MarkdownH3(MarkdownBlockContent, native_markdown.MarkdownH3):
    pass


class MarkdownH4(MarkdownBlockContent, native_markdown.MarkdownH4):
    pass


class MarkdownH5(MarkdownBlockContent, native_markdown.MarkdownH5):
    pass


class MarkdownH6(MarkdownBlockContent, native_markdown.MarkdownH6):
    pass


class MarkdownHorizontalRule(MarkdownBlockContent, native_markdown.MarkdownHorizontalRule):
    pass


class MarkdownParagraph(MarkdownBlockContent, native_markdown.MarkdownParagraph):
    pass


class MarkdownBlockQuote(MarkdownBlockContent, native_markdown.MarkdownBlockQuote):
    pass


class MarkdownBulletList(MarkdownBlockContent, native_markdown.MarkdownBulletList):
    pass


class MarkdownOrderedList(MarkdownBlockContent, native_markdown.MarkdownOrderedList):
    pass


class MarkdownOrderedListItem(MarkdownBlockContent, native_markdown.MarkdownOrderedListItem):
    pass


class MarkdownUnorderedListItem(MarkdownBlockContent, native_markdown.MarkdownUnorderedListItem):
    pass


class MarkdownTable(MarkdownBlockContent, native_markdown.MarkdownTable):
    pass


class MarkdownTBody(MarkdownBlockContent, native_markdown.MarkdownTBody):
    pass


class MarkdownTHead(MarkdownBlockContent, native_markdown.MarkdownTHead):
    pass


class MarkdownTR(MarkdownBlockContent, native_markdown.MarkdownTR):
    pass


class MarkdownTH(MarkdownBlockContent, native_markdown.MarkdownTH):
    pass


class MarkdownTD(MarkdownBlockContent, native_markdown.MarkdownTD):
    pass


class MarkdownFence(MarkdownBlockContent, native_markdown.MarkdownFence):
    pass
