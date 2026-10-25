"""Tab order keeps one opening order and a branching visit history."""

from toad.tab_order import TabOrder
from toad.db import DB
from toad.tab_identity.kinds import PreviewTab


async def test_history_branches_closing_prunes_it_and_a_new_kind_of_tab_needs_no_new_code(tmp_path):
    first, second, third, new_kind, closed = (
        PreviewTab(tmp_path / name) for name in ("first", "second", "third", "new-kind", "closed")
    )
    focused = []
    database = DB(tmp_path / "toad.db")
    await database.create()
    order = TabOrder(
        lambda mode, index: focused.append((mode, index)),
        home="home", db=database,
    )
    await order.load()
    for mode in (first, second, third):
        await order.open(mode)
        order.record_visit(mode)
    order.navigate(-1)
    mode, index = focused[-1]
    order.record_visit(mode, index)
    await order.open(new_kind, after=mode)
    order.record_visit(new_kind)
    assert order.names == (first, second, new_kind, third)
    assert order.history_target(+1) is None
    assert order.previous(new_kind) == second
    await order.close({second, third})
    order.navigate(-1)
    assert focused[-1][0] == first
    assert order.previous(new_kind) == first
    assert order.project({first: 1, new_kind: 2, closed: 3}) == (1, 2)


async def test_home_is_shown_only_while_no_tab_is_open(tmp_path):
    only, closed = PreviewTab(tmp_path / "only"), PreviewTab(tmp_path / "closed")
    database = DB(tmp_path / "toad.db")
    await database.create()
    order = TabOrder(lambda mode, index: None, home="home", db=database)
    await order.load()
    assert order.previous(closed) is None
    await order.open(only)
    # Leaving the only tab for "the previous one" stays on it: home is not a tab to go back to.
    assert order.previous(only) == only
    assert order.previous(closed) == only
    await order.close({only})
    assert order.previous(only) is None
