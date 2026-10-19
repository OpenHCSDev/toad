"""Shell commands are analysed into spans the prompt marks as dangerous or destructive."""

import pytest

from toad.danger import analyze, DangerStyles

SPANS = (
    ("rm -rf ../x", ((0, 11, "destructive"),)),
    ("rm tmp/x", ((0, 8, "danger"),)),
    ("ls", ()),
    ("cd ..; rm x", ((7, 11, "destructive"),)),
    ("echo hi > ../x", ((8, 14, "destructive"),)),
    ("cat < ../x", ()),
    ("rm -rf", ((0, 6, "danger"),)),
    ("ls | rm ../x", ((5, 12, "destructive"),)),
    ('echo "unterminated', ((0, 18, "danger"),)),
    ('echo $((', ((0, 8, "danger"),)),
    ('echo $((1 + 2))', ((0, 15, "danger"),)),
)


@pytest.mark.parametrize("command, expected", SPANS)
def test_real_shell_syntax_is_marked(command, expected):
    atoms = analyze("/project", "/project", command)
    styles = DangerStyles("danger", "destructive")
    assert tuple((*atom.span, style) for atom in atoms if (style := atom.level.highlight(styles))) == expected


def test_a_substitution_changes_directory_only_inside_itself():
    atoms = analyze("/project", "/project", "echo $(cd ..; rm x); rm x")
    styles = DangerStyles("danger", "destructive")
    assert [style for atom in atoms if (style := atom.level.highlight(styles))] == ["destructive", "danger"]
