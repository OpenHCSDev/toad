"""Tab order keeps one opening order and a branching visit history."""

from toad.tab_order import TabOrder


def test_history_branches_closing_prunes_it_and_a_new_kind_of_tab_needs_no_new_code():
    focused = []
    order = TabOrder(lambda mode, index: focused.append((mode, index)))
    for mode in ("first", "second", "third"):
        order.open(mode)
        order.record_visit(mode)
    order.navigate(-1)
    mode, index = focused[-1]
    order.record_visit(mode, index)
    order.open("new-kind", after=mode)
    order.record_visit("new-kind")
    assert order.names == ("first", "second", "new-kind", "third")
    assert order.history_target(+1) is None
    assert order.previous("new-kind") == "second"
    order.close({"second", "third"})
    order.navigate(-1)
    assert focused[-1][0] == "first"
    assert order.previous("new-kind") == "first"
    assert order.project({"first": 1, "new-kind": 2, "closed": 3}) == (1, 2)
