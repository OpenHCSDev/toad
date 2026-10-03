"""External terminal bytes, incremental consumption, and extension contracts."""

import ast
import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

from toad.ansi._ansi import ANSICommand, TerminalMode, TerminalState
from toad.ansi._stream_parser import (
    Pattern,
    Read,
    ReadPattern,
    ReadPatterns,
    ReadRegex,
    ReadUntil,
)


# These are terminal escape contracts, not saved internal snapshots.
@pytest.mark.parametrize(
    ("sequence", "expected"),
    [
        ("hello", {"text": "hello", "cursor": (0, 5)}),
        ("hi\rX", {"text": "Xi", "cursor": (0, 1)}),
        ("hi\nX", {"text": "hi\nX", "cursor": (1, 1)}),
        ("abc\x08X", {"text": "abX"}),
        ("\x1b[3;5H", {"cursor": (2, 4)}),
        ("\x1b[3;5H\x1b[2A\x1b[2D", {"cursor": (0, 2)}),
        ("\x1b[31mX", {"foreground": 1}),
        ("\x1b[31m\x1b[0mX", {"foreground": None}),
        ("abc\r\x1b[K", {"text": ""}),
        ("abc\x1b[2J", {"text": ""}),
        ("\x1b[2;5r", {"margins": (1, 4), "cursor": (0, 0)}),
        ("\x1b[?1049hA\nB", {"text": "A\n B", "alternate": True}),
        ("\x1b[?1049h\x1b[1S", {"alternate": True}),
        ("\x1b[?1049h\x1b[1T", {"alternate": True}),
        ("\x1b[?25l", {"show_cursor": False}),
        ("\x1b[?25l\x1b[?25h", {"show_cursor": True}),
        ("\x1b[?1049h\x1b[?1049l", {"alternate": False}),
        ("\x1b[?2004h", {"bracketed_paste": True}),
        ("\x1b[?12h", {"cursor_blink": True}),
        ("\x1b[?1h", {"cursor_keys": True}),
        ("\x1b[?7l", {"auto_wrap": False}),
        ("abc\r\x1b[4hX", {"text": "Xabc", "replace_mode": False}),
        ("\x1b[4h\x1b[4l", {"replace_mode": True}),
        ("\x1b[?1000h", {"tracking": "button"}),
        ("\x1b[?1002h", {"tracking": "drag"}),
        ("\x1b[?1003h", {"tracking": "all"}),
        ("\x1b[?1000h\x1b[?1000l", {"tracking": None}),
        ("\x1b[?1006h", {"format": "sgr"}),
        ("\x1b[?1006h\x1b[?1006l", {"format": "normal"}),
        ("\x1b[?1015h", {"format": "urxvt"}),
        ("\x1b[?1004h", {"focus_events": True}),
        ("\x1b[?1007h", {"alternate_scroll": True}),
        ("\x1b[?25;2004h", {"show_cursor": True, "bracketed_paste": True}),
        ("\x1b[?987654h", {"tracking": None}),
        ("\x1b]2025;/project\x07", {"directory": "/project"}),
        ("\x1b]2025;/project\x1b\\", {"directory": "/project"}),
        ("\x1b(0q\x1b(Bx", {"text": "─x"}),
        ("\x1bPignored\x1b\\X", {"text": "X"}),
        ("\x1b#8X", {"text": "X"}),
        ("\x1b F" + "X", {"text": "X"}),
        ("\x1b[3;5H\x1b[6n", {"stdin": "\x1b[3;5R"}),
    ],
)
def test_terminal_escape_contract(sequence, expected):
    async def run():
        for fragments in ([sequence], list(sequence)):
            replies = []

            async def stdin(value):
                replies.append(value)

            state = TerminalState(stdin, width=20, height=8)
            for fragment in fragments:
                await state.write(fragment)
            mouse = state.mouse_tracking
            actual = {
                "text": "\n".join(line.content.plain for line in state.buffer.lines),
                "cursor": (state.buffer.cursor_line, state.buffer.cursor_offset),
                "foreground": state.style.color.number
                if state.style.color
                else None,
                "margins": tuple(state.buffer.scroll_margin),
                "alternate": state.alternate_screen,
                "show_cursor": state.show_cursor,
                "bracketed_paste": state.bracketed_paste,
                "cursor_blink": state.cursor_blink,
                "cursor_keys": state.cursor_keys,
                "auto_wrap": state.auto_wrap,
                "replace_mode": state.replace_mode,
                "tracking": mouse.tracking if mouse else None,
                "format": mouse.format if mouse else None,
                "focus_events": mouse.focus_events if mouse else False,
                "alternate_scroll": mouse.alternate_scroll if mouse else False,
                "directory": state.current_directory,
                "stdin": "".join(replies),
            }
            assert {key: actual[key] for key in expected} == expected

    asyncio.run(run())


def test_declared_command_and_mode_need_no_dispatch_edit():
    @dataclass(frozen=True, slots=True)
    class TestCommand(ANSICommand):
        async def apply(self, state):
            state.current_directory = "/command"

    class TestMode(TerminalMode, declared_name="987653"):
        @classmethod
        def change(cls, state, enabled):
            state.current_directory = "/enabled" if enabled else "/disabled"

    async def run():
        async def stdin(value):
            raise AssertionError(value)

        state = TerminalState(stdin)
        await TestCommand().apply(state)
        assert state.current_directory == "/command"
        await state.write("\x1b[?987653h")
        assert state.current_directory == "/enabled"
        await state.write("\x1b[?987653l")
        assert state.current_directory == "/disabled"
        with pytest.raises(TypeError, match="Duplicate family name"):

            class DuplicateMode(TerminalMode, declared_name="987653"):
                @classmethod
                def change(cls, state, enabled):
                    pass

    asyncio.run(run())


def test_reads_own_consumption_and_pattern_exhaustion():
    class Word(Pattern):
        def check(self):
            if (yield) != "a":
                return False
            if (yield) != "b":
                return False
            return ("word", "ab")

    cases = [
        (Read(2), "abc", 2, "ab"),
        (ReadUntil(":"), "ab:cd", 2, "ab"),
        (ReadRegex("[0-9]+"), "ab12cd", 4, "ab12"),
    ]
    for reader, source, consumed, value in cases:
        count, tokens = reader.feed(source)
        assert count == consumed
        assert "".join(token.text for token in tokens) == value
    for reader in (ReadPattern("", "word", Word()), ReadPatterns(word=Word())):
        assert reader.feed("a") == (1, ())
        consumed, tokens = reader.feed("b!")
        assert consumed == 1 and tokens[0].value == ("word", "ab")
        assert reader.is_exhausted
    for reader in (
        ReadPattern("ESC", "word", Word()),
        ReadPatterns("ESC", word=Word()),
    ):
        consumed, tokens = reader.feed("x!")
        assert consumed == 1 and tokens[0].text == "ESCx"
        assert reader.is_exhausted


def test_terminal_dispatch_deletion_guard():
    root = Path(__file__).resolve().parents[1] / "src/toad/ansi"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "_parse_csi":
                    assert not any(
                        isinstance(part, ast.Constant) and part.value in ("h", "l")
                        for part in ast.walk(node)
                    ), "Mode decoding belongs to TerminalMode"
                if node.name == "_handle_ansi_command":
                    pytest.fail(
                        "Commands apply directly; do not restore the dispatcher"
                    )
            if isinstance(node, ast.ClassDef) and node.name.startswith("ANSI"):
                assert all(
                    not isinstance(base, ast.Name) or base.id != "NamedTuple"
                    for base in node.bases
                )
            if isinstance(node, ast.MatchClass):
                assert not (
                    isinstance(node.cls, ast.Name) and node.cls.id.startswith("ANSI")
                )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "isinstance"
            ):
                names = {
                    part.id
                    for part in ast.walk(node.args[1])
                    if isinstance(part, ast.Name)
                }
                assert not any(
                    name.startswith("ANSI")
                    or name
                    in {
                        "StreamRead",
                        "Read",
                        "ReadUntil",
                        "ReadRegex",
                        "ReadPattern",
                        "ReadPatterns",
                    }
                    for name in names
                )
            if isinstance(node, ast.Compare):
                assert not any(
                    isinstance(part, ast.Constant)
                    and isinstance(part.value, str)
                    and part.value.lstrip("?").isdigit()
                    for part in (node.left, *node.comparators)
                )
        assert "ANSIFeatures" not in path.read_text()
        assert "ANSIMouseTracking" not in path.read_text()
