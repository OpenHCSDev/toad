from unittest.mock import patch

import pytest

from textual.content import Content


@pytest.mark.parametrize("text", ["", "\n", "a\n\n", "  padded words  ", "a " * 40,
                                  "abcdefghijklmnop", "界 café 界 👍🏽 é", "a\tb\n界\tend"])
@pytest.mark.parametrize("width", [1, 2, 5, 12, 40])
@pytest.mark.parametrize("wrap", ["wrap", "nowrap"])
@pytest.mark.parametrize("overflow", ["fold", "ellipsis", "clip"])
def test_height_projection_matches_native_formatter(text, width, wrap, overflow):
    content = Content(text)
    rules = {"text_wrap": wrap, "text_overflow": overflow}
    expected = sum(1 for _ in content.without_spans._wrap_and_format(width, overflow=overflow, no_wrap=wrap == "nowrap"))
    with patch.object(Content, "_wrap_and_format", side_effect=AssertionError("Measurement constructed paint objects")):
        assert content.get_height(rules, width) == expected


def test_line_padding_does_not_alias_another_widths_measurement():
    content = Content("one two three four five six")
    for width, padding in [(10, 1), (12, 0), (8, 2), (12, 0)]:
        rules = {"line_pad": padding}
        expected = sum(1 for _ in content.without_spans._wrap_and_format(width - padding * 2))
        assert content.get_height(rules, width) == expected


@pytest.mark.parametrize("width", [0, 2])
def test_no_available_width_measurement_consumes_all_source_lines(width):
    content = Content("first\n\nlast")
    rules = {"text_wrap": "nowrap", "text_overflow": "clip", "line_pad": 1}
    assert content.get_height(rules, width) == 3
