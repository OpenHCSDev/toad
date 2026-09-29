"""Parser reuse preserves token/link semantics and isolates concurrent threads."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
from threading import Barrier

from markdown_it import MarkdownIt
from toad.conversation_markdown import _ThreadLocalPathParser, _parser_state
from toad.widgets.transcript_fragments import _fragment_parser


def tokens(parser, text):
    return [token.as_dict() for token in parser.parse(text)]


def main():
    with tempfile.TemporaryDirectory(prefix="toad-parser-reuse-") as directory:
        root = Path(directory)
        (root / "local.py").write_text("pass\n")
        fixture = json.loads(Path(__file__).with_name("guards").joinpath(
            "markdown_parser_predecessor.json").read_text())
        texts = fixture["texts"]
        def expected(text):
            return fixture["tokens"][texts.index(text)]
        def observed(parser, text):
            return json.loads(json.dumps(tokens(parser, text)).replace(str(root), "<project>"))
        facade = _ThreadLocalPathParser(root)
        for _ in range(3):
            for text in texts:
                assert observed(facade, text) == expected(text)
                assert tokens(_fragment_parser(), text) == tokens(MarkdownIt("gfm-like"), text)
        same = _parser_state.parser
        facade.parse("another input")
        assert _parser_state.parser is same

        barrier = Barrier(2)

        def concurrent_parse():
            local_facade = _ThreadLocalPathParser(root)
            local_facade.parse("warm")
            parser = _parser_state.parser
            barrier.wait(timeout=5)
            for text in texts:
                assert observed(local_facade, text) == expected(text)
            return parser

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(concurrent_parse)
            second = executor.submit(concurrent_parse)
            assert first.result() is not second.result()
        for index in range(20):
            _ThreadLocalPathParser(root / str(index)).parse("plain text")
        assert _parser_state.parser is same
    print("parser reuse: token parity, isolated document references and threads, single bounded syntax parser passed")


if __name__ == "__main__":
    main()
