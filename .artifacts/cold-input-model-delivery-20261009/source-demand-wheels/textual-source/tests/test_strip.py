import gc
import weakref
from unittest.mock import patch

import pytest
from rich.console import Console
from rich.segment import Segment
from rich.style import Style

from textual._segment_tools import NoCellPositionForIndex
from textual.cache import FIFOCache
from textual.color import Color
from textual.filter import Monochrome
from textual.strip import Strip


@pytest.mark.parametrize("operation", ["divide", "crop_extend"])
def test_identity_transform_does_not_require_cyclic_gc(operation):
    """Discarded compositor lines should die immediately, not in a GC pause."""

    class WeakStrip(Strip):
        __slots__ = ("__weakref__",)

    enabled = gc.isenabled()
    gc.disable()
    try:
        strip = WeakStrip([Segment("text")])
        reference = weakref.ref(strip)
        if operation == "divide":
            assert strip.divide([4]) == [strip]
        else:
            assert strip.crop_extend(0, 4, None) is strip
        del strip
        assert reference() is None
    finally:
        if enabled:
            gc.enable()


def test_transient_strips_only_allocate_caches_they_use():
    """Rendering one-use lines must not allocate seven unused caches apiece."""
    with patch("textual.strip.FIFOCache", wraps=FIFOCache) as cache:
        strips = [Strip([Segment("line")]) for _ in range(1000)]
        assert cache.call_count == 0
        cropped = strips[0].crop(1, 3)
        assert cropped.text == "in"
        assert strips[0].crop(1, 3) is cropped
        assert cache.call_count == 1


def test_cell_length() -> None:
    strip = Strip([Segment("foo"), Segment("💩"), Segment("bar")])
    assert strip._cell_length is None
    assert strip.cell_length == 8
    assert strip._cell_length == 8


def test_repr() -> None:
    strip = Strip([Segment("foo")])
    assert repr(strip) == "Strip([Segment('foo')], 3)"


def test_join() -> None:
    strip1 = Strip([Segment("foo")])
    strip2 = Strip([Segment("bar")])
    strip = Strip.join([strip1, strip2])
    assert len(strip) == 2
    assert strip.cell_length == 6
    assert list(strip) == [Segment("foo"), Segment("bar")]


def test_join_preserves_original_wide_row_metadata_and_render_resources():
    style = Style(color="red", link="https://example.com/row", meta={"@click": "open_row"})
    original = Strip([Segment("界", style), Segment("x", style)], 3)
    console = Console(force_terminal=True)
    rendered = original.render(console)
    cropped = original.crop(0, 2)
    original.divide([2, 3])

    joined = Strip.join(iter((None, Strip([], 0), original, None)))
    assert joined is original
    assert joined.text == "界x" and joined.cell_length == 3
    assert joined.render(console) == rendered
    assert joined.crop(0, 2) is cropped
    assert all(segment.style.meta["@click"] == "open_row" for segment in joined)
    assert all(segment.style.link == "https://example.com/row" for segment in joined)

    appended = Strip.join((joined, Strip([Segment("z", style)], 1)))
    assert appended.text == "界xz" and appended.cell_length == 4
    assert original.text == "界x" and original.cell_length == 3


def test_join_retains_requested_factory_and_empty_value_contract():
    class RowStrip(Strip):
        pass

    plain = Strip([Segment("value")], 5)
    specialized = RowStrip.join((plain,))
    assert type(specialized) is RowStrip and specialized is not plain
    assert RowStrip.join((None, specialized)) is specialized
    normalized = Strip.join((specialized,))
    assert type(normalized) is Strip and normalized is not specialized
    assert list(normalized) == list(plain)
    empty = RowStrip.join(iter((None, Strip([], 0), None)))
    assert type(empty) is RowStrip and empty.cell_length == 0
    assert list(empty) == []


def test_bool() -> None:
    assert not Strip([])
    assert Strip([Segment("foo")])


def test_iter() -> None:
    assert list(Strip([])) == []
    assert list(Strip([Segment("foo")])) == [Segment("foo")]
    assert list(Strip([Segment("foo"), Segment("bar")])) == [
        Segment("foo"),
        Segment("bar"),
    ]


def test_len():
    assert len(Strip([])) == 0
    assert len(Strip([Segment("foo")])) == 1
    assert len(Strip([Segment("foo"), Segment("bar")])) == 2


def test_reversed():
    assert list(reversed(Strip([]))) == []
    assert list(reversed(Strip([Segment("foo")]))) == [Segment("foo")]
    assert list(reversed(Strip([Segment("foo"), Segment("bar")]))) == [
        Segment("bar"),
        Segment("foo"),
    ]


def test_eq():
    assert Strip([]) == Strip([])
    assert Strip([Segment("foo")]) == Strip([Segment("foo")])
    assert Strip([Segment("foo")]) != Strip([Segment("bar")])


def test_adjust_cell_length():
    assert Strip([]).adjust_cell_length(3) == Strip([Segment("   ")])
    assert Strip([Segment("f")]).adjust_cell_length(3) == Strip(
        [Segment("f"), Segment("  ")]
    )
    assert Strip([Segment("💩")]).adjust_cell_length(3) == Strip(
        [Segment("💩"), Segment(" ")]
    )

    assert Strip([Segment("💩💩")]).adjust_cell_length(3) == Strip([Segment("💩 ")])
    assert Strip([Segment("💩💩")]).adjust_cell_length(4) == Strip([Segment("💩💩")])
    assert Strip([Segment("💩"), Segment("💩💩")]).adjust_cell_length(2) == Strip(
        [Segment("💩")]
    )
    assert Strip([Segment("💩"), Segment("💩💩")]).adjust_cell_length(4) == Strip(
        [Segment("💩"), Segment("💩")]
    )


def test_extend_cell_length():
    strip = Strip([Segment("foo"), Segment("bar")])
    assert strip.extend_cell_length(3).text == "foobar"
    assert strip.extend_cell_length(6).text == "foobar"
    assert strip.extend_cell_length(7).text == "foobar "
    assert strip.extend_cell_length(9).text == "foobar   "


def test_simplify():
    assert Strip([Segment("foo"), Segment("bar")]).simplify() == Strip(
        [Segment("foobar")]
    )


def test_apply_filter():
    strip = Strip([Segment("foo", Style.parse("#990000"))])
    expected = Strip([Segment("foo", Style.parse("#212121"))])
    result = strip.apply_filter(Monochrome(), Color(0, 0, 0))
    print(repr(result))
    assert result == expected


def test_style_links():
    link_style = Style.on(click="clicked")
    strip = Strip(
        [
            Segment("foo"),
            Segment("bar", link_style),
            Segment("baz"),
        ]
    )
    hover_style = Style(underline=True)
    new_strip = strip.style_links(link_style._link_id, hover_style)
    expected = Strip(
        [
            Segment("foo"),
            Segment("bar", link_style + hover_style),
            Segment("baz"),
        ]
    )
    assert new_strip == expected


def test_crop():
    assert Strip([Segment("foo")]).crop(0, 3) == Strip([Segment("foo")])
    assert Strip([Segment("foo")]).crop(0, 2) == Strip([Segment("fo")])
    assert Strip([Segment("foo")]).crop(0, 1) == Strip([Segment("f")])

    assert Strip([Segment("foo")]).crop(1, 3) == Strip([Segment("oo")])
    assert Strip([Segment("foo")]).crop(1, 2) == Strip([Segment("o")])
    assert Strip([Segment("foo")]).crop(1, 1) == Strip([])

    assert Strip([Segment("foo💩"), Segment("b💩ar"), Segment("ba💩z")]).crop(
        1, 6
    ) == Strip([Segment("oo💩"), Segment("b")])


@pytest.mark.parametrize(
    "text,crop,output",
    [
        ["foo", (0, 5), [Segment("foo")]],
        ["foo", (2, 5), [Segment("o")]],
        ["foo", (3, 5), []],
        ["foo", (4, 6), []],
    ],
)
def test_crop_out_of_bounds(text, crop, output):
    assert Strip([Segment(text)]).crop(*crop) == Strip(output)


def test_divide():
    assert Strip([Segment("foo")]).divide([1, 2]) == [
        Strip([Segment("f")]),
        Strip([Segment("o")]),
    ]


@pytest.mark.parametrize(
    "index,cell_position",
    [
        (0, 0),
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
        (5, 6),
        (6, 8),
        (7, 10),
        (8, 11),
        (9, 12),
        (10, 13),
        (11, 14),
    ],
)
def test_index_to_cell_position(index, cell_position):
    strip = Strip([Segment("ab"), Segment("cd日本語ef"), Segment("gh")])
    assert cell_position == strip.index_to_cell_position(index)


def test_index_cell_position_no_segments():
    strip = Strip([])
    with pytest.raises(NoCellPositionForIndex):
        strip.index_to_cell_position(2)


def test_index_cell_position_index_too_large():
    strip = Strip([Segment("abcdef"), Segment("ghi")])
    with pytest.raises(NoCellPositionForIndex):
        strip.index_to_cell_position(100)


def test_text():
    assert Strip([]).text == ""
    assert Strip([Segment("foo")]).text == "foo"
    assert Strip([Segment("foo"), Segment("bar")]).text == "foobar"


def test_render_with_missing_style() -> None:
    """Test that render with segments that omit a style still work."""
    strip = Strip([Segment("Hello")])
    assert strip.render(Console()) == "Hello"
