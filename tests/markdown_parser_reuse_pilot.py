"""Parser reuse preserves token/link semantics and isolates concurrent threads."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
from threading import Barrier

from markdown_it import MarkdownIt
from toad.conversation_markdown import _ThreadLocalPathParser, _path_parser, _parser_state
from toad.widgets.transcript_fragments import _fragment_parser


def tokens(parser, text):
    return [token.as_dict() for token in parser.parse(text)]


def main():
    with tempfile.TemporaryDirectory(prefix="toad-parser-reuse-") as directory:
        root = Path(directory)
        (root / "local.py").write_text("pass\n")
        texts = [
            "[reference][x]\n\n[x]: https://example.com\n",
            "[reference][x]\n",  # No reference definitions may leak from a prior parse.
            "Visit https://example.com and local.py:12\n",
            "| a | b |\n|---|---|\n|界|é|\n",
            "```python\nprint('local.py')\n```\n",
            "1. **one**\n2. `two`\n\n> quote\n",
        ]
        facade = _ThreadLocalPathParser(root)
        for _ in range(3):
            for text in texts:
                assert tokens(facade, text) == tokens(_path_parser(root), text)
                assert tokens(_fragment_parser(), text) == tokens(MarkdownIt("gfm-like"), text)
        same = _parser_state.parsers[root]
        facade.parse("another input")
        assert _parser_state.parsers[root] is same

        barrier = Barrier(2)

        def concurrent_parse():
            local_facade = _ThreadLocalPathParser(root)
            local_facade.parse("warm")
            parser = _parser_state.parsers[root]
            barrier.wait(timeout=5)
            for text in texts:
                assert tokens(local_facade, text) == tokens(_path_parser(root), text)
            return parser

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(concurrent_parse)
            second = executor.submit(concurrent_parse)
            assert first.result() is not second.result()
        for index in range(20):
            _ThreadLocalPathParser(root / str(index)).parse("plain text")
        assert len(_parser_state.parsers) == 8
    print("parser reuse: token parity, isolated document references and threads, bounded project cache passed")


if __name__ == "__main__":
    main()
