"""A throbber sync asks its activity owner again; it does not ring the doorbell twice.

`busy` is a computed reactive, so reading it recomputes and invokes its own watcher when
the answer changed (textual `reactive.py:170`). `sync` used to read it *and* call
`watch_busy` by hand, so every source round notified twice. On a phone capture of the
landing page with no input that was 238 `watch_busy` invocations for about 60 hidden
source rounds: 119 from the reactive and 119 from the hand call, each ending in a
`refresh()` of a throbber that renders nothing when it is not busy, on a view nobody was
looking at.

This counts invocations and does not let them through, because the count is the claim.
"""

from toad.widgets.throbber import AboveThrobber


def test_a_sync_notifies_once_for_a_change_and_not_at_all_without_one():
    working = False
    throbber = AboveThrobber(lambda: working)
    notified: list[bool] = []

    original = type(throbber).watch_busy
    type(throbber).watch_busy = lambda self, busy: notified.append(busy)
    try:
        throbber.sync()
        notified.clear()

        throbber.sync()
        assert notified == [], "an unchanged answer has nothing to say"

        working = True
        throbber.sync()
        assert notified == [True], "a changed answer notifies exactly once"

        notified.clear()
        for _ in range(5):
            throbber.sync()
        assert notified == [], "repeating the question does not repeat the answer"

        working = False
        throbber.sync()
        assert notified == [False], "going quiet notifies exactly once"
    finally:
        type(throbber).watch_busy = original
