"""New native token rule and fresh filesystem resolution of reused pure syntax."""

from copy import deepcopy
from pathlib import Path
import os
import tempfile

from toad.conversation_markdown import (
    ProjectTokenRule, _ThreadLocalPathParser, _parser_state, parse_markdown_syntax,
)


def hrefs(tokens):
    return [child.attrGet('href') for block in tokens for child in block.children or ()
            if child.type == 'link_open']


def main():
    with tempfile.TemporaryDirectory(
        prefix='markdown-rules-', dir=os.environ['TMPDIR'],
    ) as directory:
        root = Path(directory)
        first, second = root / 'first', root / 'second'
        first.mkdir()
        second.mkdir()
        source = 'file.py `file.py` `run file.py` [file.py](https://example.com)\n'
        syntax = parse_markdown_syntax(source)
        original = deepcopy(syntax)
        parser = _ThreadLocalPathParser(first)
        assert hrefs(parser.resolve_tokens(deepcopy(syntax))) == [
            'toad-file-search:file.py', 'toad-file-search:file.py', 'https://example.com',
        ]
        target = first / 'file.py'
        target.write_text('first\n')
        assert hrefs(parser.resolve_tokens(deepcopy(syntax))) == [
            f'toad-file:{target}', f'toad-file:{target}', 'https://example.com',
        ]
        assert hrefs(_ThreadLocalPathParser(second).resolve_tokens(deepcopy(syntax))) == [
            'toad-file-search:file.py', 'toad-file-search:file.py', 'https://example.com',
        ]
        target.unlink()
        assert hrefs(parser.resolve_tokens(deepcopy(syntax)))[0] == 'toad-file-search:file.py'
        assert [token.as_dict() for token in syntax] == [token.as_dict() for token in original]

        class SoftbreakTokenRule(ProjectTokenRule):
            @classmethod
            def resolve(cls, renderer, token, context):
                token.meta['project-rule-new-case'] = True
                return [token]

        native = _parser_state.parser
        previous = tuple(native.renderer.rules)
        SoftbreakTokenRule.register(native)
        resolved = parser.parse('before\nafter')
        assert tuple(native.renderer.rules) == (*previous, SoftbreakTokenRule.declared_name)
        breaks = [child for block in resolved for child in block.children or ()
                  if child.type == SoftbreakTokenRule.declared_name]
        assert len(breaks) == 1 and breaks[0].meta['project-rule-new-case']
    print('native token registry: declaration-only new case, pure syntax, fresh root/create/delete links')


if __name__ == '__main__':
    main()
