"""A long ANSI stream with screen switches keeps only the screen's lines and the text it drew."""

from toad.ansi import TerminalState


async def test_streamed_ansi_stays_within_the_screen_and_keeps_its_text():
    async def stdin(value):
        raise AssertionError(f"Unexpected terminal input request: {value!r}")

    chunk = "\x1b[?1049h\x1b[2J\x1b[H" + "hello \x1b[31mworld\x1b[0m\r\n" * 20
    state = TerminalState(stdin, width=100, height=30)
    for _ in range(3000):
        await state.write(chunk)
    assert len(state.buffer.lines) <= 30
    assert state.buffer.lines[0].content.plain == "hello world"
