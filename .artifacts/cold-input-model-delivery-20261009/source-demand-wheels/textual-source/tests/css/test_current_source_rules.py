"""Adding widget CSS must not reparse every source after the LRU fills up."""

from unittest.mock import patch

import pytest

from textual.color import Color
from textual.css.stylesheet import Stylesheet, StylesheetParseError
from textual.dom import DOMNode
import textual.css.stylesheet as stylesheet_module


def make_sheet():
    sheet = Stylesheet(variables={"shade": "red"})
    for index in range(100):
        sheet.add_source(f".row-{index} {{ color: $shade; }}", read_from=(f"source-{index}", ""))
    sheet.parse()
    return sheet


def test_new_source_only_parses_new_declaration_beyond_historical_lru_capacity():
    sheet = make_sheet()
    with patch.object(stylesheet_module, "parse", wraps=stylesheet_module.parse) as parser:
        sheet.add_source(".new { color: blue; }", read_from=("new-source", ""))
        sheet.parse()
        assert parser.call_count == 1
        sheet.parse()
        assert parser.call_count == 1
    assert len(sheet.rules) == len(sheet._source_rules) == 101


def test_source_edits_removal_variables_and_reparse_keep_current_semantics():
    sheet = make_sheet()
    node = DOMNode(classes="row-0")
    sheet.apply(node)
    assert node.styles.color == Color.parse("red")
    for color in ("blue", "green", "yellow"):
        sheet.add_source(f".row-0 {{ color: {color}; }}", read_from=("source-0", ""))
        sheet.parse()
        sheet.apply(node)
        assert node.styles.color == Color.parse(color)
        assert len(sheet._source_rules) == 100
    sheet.source.pop(("source-99", ""))
    sheet.parse()
    assert ("source-99", "") not in sheet._source_rules
    assert len(sheet._source_rules) == 99

    sheet.set_variables({"shade": "blue"})
    sheet.parse()
    other = DOMNode(classes="row-1")
    sheet.apply(other)
    assert other.styles.color == Color.parse("blue")
    sheet.reparse()
    with patch.object(stylesheet_module, "parse", wraps=stylesheet_module.parse) as parser:
        sheet.add_source(".last { color: red; }", read_from=("last", ""))
        sheet.parse()
        assert parser.call_count == 1


def test_scope_and_priority_changes_invalidate_the_source_result():
    sheet = Stylesheet()
    location = ("scoped", "")
    for scope, priority in (("One", 0), ("Two", 0), ("Two", 1)):
        sheet.add_source(".child { color: red; }", read_from=location,
                         is_default_css=True, scope=scope, tie_breaker=priority)
        # add_source's duplicate-content policy intentionally keeps the first
        # registration in some cases; the authoritative source tuple determines
        # what parse must use, including direct source replacement on reload.
        source_type = type(sheet.source[location])
        sheet.source[location] = source_type(".child { color: red; }", True, priority, scope)
        with patch.object(stylesheet_module, "parse", wraps=stylesheet_module.parse) as parser:
            sheet.parse()
            assert parser.call_count == 1
        assert sheet.rules[0].selector_set[0].selectors[0].name == scope
        assert sheet.rules[0].tie_breaker == priority


def test_failed_parse_does_not_publish_partial_current_source_cache():
    sheet = make_sheet()
    old_rules = sheet.rules
    old_cache = sheet._source_rules
    sheet.add_source(".broken { not-a-property: invalid; }", read_from=("broken", ""))
    with pytest.raises(StylesheetParseError):
        sheet.parse()
    assert sheet._rules is old_rules
    assert sheet._source_rules is old_cache
