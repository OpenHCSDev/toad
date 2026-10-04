import re
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from threading import local

from agent_comms.declared_family import DeclaredFamily
from agent_comms.field_codec import FieldCodec
from markdown_it import MarkdownIt
from markdown_it.rules_core import StateCore, inline as inline_rule
from markdown_it.token import Token
from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from textual.layout import WidgetPlacement
from textual.widgets import Markdown

from toad.layout import trim_trailing_margin
from toad.block_content import MarkdownBlockContent
from toad.project_link import ProjectLink


class ConversationCodeFence(MarkdownBlockContent, Markdown.BLOCKS["fence"]):
    def get_clipboard_text(self) -> str:
        return self._content.plain

    def get_prompt_text(self) -> str:
        return self.source


_PATH_PATTERN = re.compile(
    r"(?<![\w:/])"
    r"(?P<path>(?:(?:~|\.{1,2})?/)?(?:[\w.@+-]+/)+[\w.@+-]+|[\w.@+-]+\.[A-Za-z0-9][\w+-]*)"
    r"(?P<location>:\d+(?::\d+)?)?"
    r"(?![\w/])"
)


@dataclass(slots=True)
class _ProjectTokens:
    root: Path
    linked: int = 0


class ProjectTokenRule(DeclaredFamily, affix="TokenRule"):
    """Declare a markdown-it token rule with Token output for Textual."""

    @classmethod
    def register(cls, parser: MarkdownIt) -> None:
        def native_rule(renderer, tokens, index, options, env):
            return cls.resolve(renderer, tokens[index], env["project_tokens"])

        parser.add_render_rule(FieldCodec.encode(cls), native_rule, fmt=ProjectTokenRenderer.__output__)

    @classmethod
    @abstractmethod
    def resolve(cls, renderer, token: Token, context: _ProjectTokens) -> list[Token]: ...


class InlineTokenRule(ProjectTokenRule):
    @classmethod
    def resolve(cls, renderer, token, context):
        if token.children is not None:
            token.children = renderer.resolve(token.children, _ProjectTokens(context.root))
        return [token]


class LinkOpenTokenRule(ProjectTokenRule):
    @classmethod
    def resolve(cls, renderer, token, context):
        href = str(token.attrGet("href") or "")
        token.attrSet("href", ProjectLink.from_href(lambda: context.root, href).href)
        context.linked += 1
        return [token]


class LinkCloseTokenRule(ProjectTokenRule):
    @classmethod
    def resolve(cls, renderer, token, context):
        context.linked -= 1
        return [token]


class PathTokenRule(ProjectTokenRule):
    @staticmethod
    @abstractmethod
    def matches(token: Token): ...

    @staticmethod
    @abstractmethod
    def content(token: Token, match) -> Token: ...

    @classmethod
    def resolve(cls, renderer, token, context):
        if context.linked:
            return [token]
        children: list[Token] = []
        position = 0
        for match in cls.matches(token):
            link = ProjectLink.from_path(context.root, match.group("path"))
            linked = link.inline_tokens(cls.content(token, match))
            if not linked:
                continue
            if match.start() > position:
                children.append(Token("text", "", 0, content=token.content[position:match.start()]))
            children.extend(linked)
            position = match.end()
        if not position:
            return [token]
        if position < len(token.content):
            children.append(Token("text", "", 0, content=token.content[position:]))
        return children


class TextTokenRule(PathTokenRule):
    @staticmethod
    def matches(token):
        return _PATH_PATTERN.finditer(token.content)

    @staticmethod
    def content(token, match):
        return Token("text", "", 0, content=match.group(0))


class CodeInlineTokenRule(PathTokenRule):
    @staticmethod
    def matches(token):
        return (
            match for match in _PATH_PATTERN.finditer(token.content)
            if match.start() == 0 and match.end() == len(token.content)
        )

    @staticmethod
    def content(token, match):
        return token


class ProjectTokenRenderer:
    """Native RendererProtocol output is Any; this renderer preserves Tokens.

    rules is the registry populated by MarkdownIt.add_render_rule. HTML
    renderer methods are not used: Textual consumes Tokens, not HTML strings.
    """

    __output__ = "textual-tokens"

    def __init__(self, parser) -> None:
        self.rules = {}

    def render(self, tokens, options, env) -> list[Token]:
        result: list[Token] = []
        for index, token in enumerate(tokens):
            rule = self.rules.get(token.type)
            result.extend(rule(tokens, index, options, env) if rule else (token,))
        return result

    def resolve(self, tokens, context: _ProjectTokens) -> list[Token]:
        return self.render(tokens, {}, {"project_tokens": context})


class _MarkdownParserState(local):
    def __init__(self) -> None:
        self.parser = MarkdownIt("gfm-like", renderer_cls=ProjectTokenRenderer)
        for rule in ProjectTokenRule.members_with(ProjectTokenRule):
            rule.register(self.parser)
        rules = tuple(self.parser.core.ruler.getRules(""))
        boundary = rules.index(inline_rule) + 1
        self.syntax_rules, self.presentation_rules = rules[:boundary], rules[boundary:]


_parser_state = _MarkdownParserState()


def parse_markdown_syntax(source: str, env: dict | None = None) -> list[Token]:
    """Pure syntax owns no project filesystem inputs and may be reused."""
    state = StateCore(source, _parser_state.parser, {} if env is None else env)
    for rule in _parser_state.syntax_rules:
        rule(state)
    return state.tokens


class _ThreadLocalPathParser:
    """Resolve project links against fresh filesystem state in prepared syntax."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def parse(self, source: str, env: dict | None = None) -> list[Token]:
        return self.resolve_tokens(parse_markdown_syntax(source, env))

    def resolve_tokens(self, tokens: list[Token]) -> list[Token]:
        tokens = _parser_state.parser.renderer.resolve(tokens, _ProjectTokens(self.root))

        # Preserve the native ordering: project links run directly after
        # inline parsing, before the parser's derived linkify/text-join suffix.
        state = StateCore("", _parser_state.parser, {}, tokens)
        for rule in _parser_state.presentation_rules:
            rule(state)
        return state.tokens


class ConversationMarkdown(Markdown):
    """Markdown widget with custom blocks."""

    BLOCKS = {
        **{name: MarkdownBlockContent.declare(block) for name, block in Markdown.BLOCKS.items()},
        "fence": ConversationCodeFence,
    }

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("parser_factory", self._make_parser)
        kwargs.setdefault("open_links", False)
        super().__init__(*args, **kwargs)

    def _make_parser(self) -> _ThreadLocalPathParser:
        from toad.project_path_owner import ProjectPathOwner
        return _ThreadLocalPathParser(ProjectPathOwner.containing(self).project_root.resolve())

    async def on_markdown_link_clicked(self, event: Markdown.LinkClicked) -> None:
        from toad.project_path_owner import ProjectPathOwner
        link = ProjectPathOwner.link_from(self, event.href)
        await link.preview(self, event)

    @height_dependency(INDEPENDENT_HEIGHT)
    def process_layout(self, placements: list[WidgetPlacement]) -> list[WidgetPlacement]:
        return trim_trailing_margin(placements)
