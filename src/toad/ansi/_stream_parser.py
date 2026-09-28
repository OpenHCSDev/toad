import io
import re
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable, Generator, Iterable
from functools import lru_cache

import rich.repr

type TokenMatch = tuple[str, str]

type ParseResult = Generator[StreamRead, Token]
type PatternCheck = Generator[None, str, TokenMatch | bool | None]


@rich.repr.auto
class Pattern[ValueType]:
    __slots__ = ["_send", "value"]

    def __init__(self) -> None:
        self._send: Callable[[str], None] | None = None
        self.value: ValueType | None = None

    def feed(self, character: str) -> bool | TokenMatch | None:
        if self._send is None:
            generator = self.check()
            self._send = generator.send
            next(generator)
        try:
            self._send(character)
        except StopIteration as stop_iteration:
            return stop_iteration.value
        else:
            return None

    def check(self) -> PatternCheck:
        return False
        yield


class StreamRead[ResultType](ABC):
    """A read owns how input is consumed and what reaches the parser."""

    @property
    def is_exhausted(self) -> bool:
        return True

    @property
    def unconsumed_text(self) -> str:
        return ""

    @abstractmethod
    def feed(self, text: str) -> tuple[int, tuple[Token, ...]]:
        """Return consumed characters and completed tokens."""


@rich.repr.auto
class Read[ResultType](StreamRead[ResultType]):
    def __init__(self, count: int) -> None:
        self.remaining = count

    def feed(self, text: str) -> tuple[int, tuple[Token, ...]]:
        value = text[: self.remaining]
        self.remaining -= len(value)
        return len(value), (Token(value),)


@rich.repr.auto
class ReadUntil[ResultType](StreamRead[ResultType]):
    def __init__(self, *characters: str) -> None:
        self.characters = characters
        self._regex = re.compile(
            "|".join(re.escape(character) for character in characters)
        )

    def __rich_repr__(self) -> rich.repr.Result:
        yield from self.characters

    def feed(self, text: str) -> tuple[int, tuple[Token, ...]]:
        match = self._regex.search(text)
        if match is None:
            return len(text), (Token(text),)
        start, end = match.span(0)
        if start:
            return start, (Token(text[:start]),)
        return end, (SeparatorToken(text[:end]),)


@rich.repr.auto
class ReadRegex[ResultType](StreamRead[ResultType]):
    def __init__(self, regex: str) -> None:
        self.regex = re.compile(regex, re.VERBOSE)

    def feed(self, text: str) -> tuple[int, tuple[Token, ...]]:
        match = self.regex.search(text)
        if match is None:
            return len(text), (Token(text),)
        tokens = (MatchToken(match.group(0), match),)
        if match.start():
            tokens = (Token(text[: match.start()]), *tokens)
        return match.end(), tokens


class PatternRead[ResultType](StreamRead[ResultType]):
    """Shared incremental consumption for one or several pattern declarations."""

    def __init__(self, start: str) -> None:
        self._text = io.StringIO()
        self._text.write(start)
        self._exhausted = False

    @property
    def is_exhausted(self) -> bool:
        return self._exhausted

    @property
    def unconsumed_text(self) -> str:
        return self._text.getvalue()

    @abstractmethod
    def match(self, character: str) -> tuple[str, TokenMatch] | bool | None:
        """Advance the owned pattern candidates."""

    def feed(self, text: str) -> tuple[int, tuple[Token, ...]]:
        consumed = 0
        for character in text:
            consumed += 1
            result = self.match(character)
            if result is False:
                self._exhausted = True
                self._text.write(text[:consumed])
                return consumed, (Token(self.unconsumed_text),)
            if result:
                self._exhausted = True
                return consumed, (PatternToken(*result),)
        self._text.write(text)
        return consumed, ()


@rich.repr.auto
class ReadPatterns[ResultType](PatternRead[ResultType]):
    def __init__(self, start: str = "", **patterns: Pattern) -> None:
        super().__init__(start)
        self.patterns = patterns

    def match(self, character: str) -> tuple[str, TokenMatch] | bool | None:
        rejected = []
        for name, pattern in self.patterns.items():
            result = pattern.feed(character)
            if result is False:
                rejected.append(name)
            elif result:
                return name, result
        for name in rejected:
            del self.patterns[name]
        return None if self.patterns else False


@rich.repr.auto
class ReadPattern[ResultType](PatternRead[ResultType]):
    def __init__(self, start: str, name: str, pattern: Pattern) -> None:
        super().__init__(start)
        self.name = name
        self.pattern = pattern

    def match(self, character: str) -> tuple[str, TokenMatch] | bool | None:
        result = self.pattern.feed(character)
        return (self.name, result) if result else result


@rich.repr.auto
class Token:
    """A token containing text."""

    __slots__ = "text"

    def __init__(self, text: str = "") -> None:
        self.text = text

    def __rich_repr__(self) -> rich.repr.Result:
        yield self.text

    def __str__(self) -> str:
        return self.text


class SeparatorToken(Token):
    pass


class MatchToken(Token):
    __slots__ = ["match"]

    def __init__(self, text: str, match: re.Match) -> None:
        self.match = match
        super().__init__(text)

    def __rich_repr__(self) -> rich.repr.Result:
        yield self.match


class PatternToken(Token):
    __slots__ = ["name", "value"]

    def __init__(self, name: str, value: TokenMatch) -> None:
        self.name = name
        self.value = value
        super().__init__("")

    def __rich_repr__(self) -> rich.repr.Result:
        yield self.name
        yield None, self.value


class StreamParser[ParseType]:
    """Parses a stream of text into tokens."""

    def __init__(self):
        self._tokens: deque[ParseType] = deque()
        self._gen = self.parse()
        self._reading: StreamRead | None = next(self._gen)

    def emit(self, token: ParseType) -> None:
        self._tokens.append(token)

    def read(self, count: int) -> Read:
        """Read a specific number of bytes.

        Args:
            count: Number of bytes to read.
        """
        return Read(count)

    @lru_cache(1024)
    def read_until(self, *characters: str) -> ReadUntil:
        """Read until the given characters.

        Args:
            characters: Set of characters to stop read.

        """
        return ReadUntil(*characters)

    def read_regex(self, regex: str) -> ReadRegex:
        """Search for the matching regex.

        Args:
            regex: Regular expression.
        """
        return ReadRegex(regex)

    def read_patterns(self, start: str = "", **patterns) -> ReadPattern | ReadPatterns:
        """Read until a pattern matches, or the patterns have been exhausted.

        Args:
            start: Initial part of the string.
            **patterns: One or more patterns.
        """
        if len(patterns) == 1:
            name, pattern = patterns.popitem()
            return ReadPattern(start, name, pattern)
        return ReadPatterns(start, **patterns)

    def feed(self, text: str) -> Iterable[ParseType]:
        sequences = text.splitlines(keepends=True)
        for sequence in sequences:
            yield from self._feed(sequence)

    def _feed(self, text: str) -> Iterable[ParseType]:
        """Feed text in to parser.

        Args:
            text: Text from stream.

        Returns:
            A generator of tokens or the parse type.

        """
        if not text or self._gen is None:
            return

        while text and self._reading is not None:
            consumed, tokens = self._reading.feed(text)
            text = text[consumed:]
            for token in tokens:
                try:
                    self._reading = self._gen.send(token)
                except StopIteration:
                    self._gen.close()
                    self._gen = None
                    self._reading = None
                while self._tokens:
                    yield self._tokens.popleft()
                if self._reading is None:
                    return

    def parse(self) -> ParseResult:
        yield from ()
