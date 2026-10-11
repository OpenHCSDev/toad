"""A lookahead request never cancels the running pass; the worker takes the latest request after it."""

import asyncio
from types import SimpleNamespace
import unittest

from textual.app import App, ComposeResult
from textual.widget import Widget

from toad.transcript_source_preparation import TranscriptSourcePreparation


class Source:
    """The source state's retirement, all this test's history uses of it."""

    def retire_preparation(self, buffer) -> None:
        pass

    def retirement_source(self):
        return None


class History(TranscriptSourcePreparation, Widget):
    """A source whose passes record their request and wait to be released."""

    def __init__(self) -> None:
        super().__init__(source_state=Source())
        self.passes: list[int] = []
        self.cancelled = 0
        self.release = asyncio.Event()
        # Retirement removes the history from its window's set.
        self.window = SimpleNamespace(histories=set())

    async def prepare_lookahead(self, intent) -> None:
        self.passes.append(intent)
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        self.release.clear()

    # The state a request was made for; a width change or a new admission
    # makes every earlier request stale before the next one arrives.
    latest = None

    def lookahead_current(self, intent) -> bool:
        return intent == self.latest


class Host(App):
    def compose(self) -> ComposeResult:
        yield History()


class LookaheadRequests(unittest.IsolatedAsyncioTestCase):
    async def test_requests_during_a_pass_wait_for_it_and_the_latest_runs_next(self):
        async with Host().run_test() as pilot:
            history = pilot.app.query_one(History)
            history.latest = 1
            history.request_lookahead(1)
            await pilot.pause()
            for intent in (2, 3, 4):
                history.latest = intent
                history.request_lookahead(intent)
                await pilot.pause()
            self.assertEqual(history.passes, [1], "the running pass continues")
            history.release.set()
            await pilot.pause()
            self.assertEqual(history.passes, [1, 4], "then the latest request, once")
            history.release.set()
            await pilot.pause()
            self.assertEqual(history.cancelled, 0)
            self.assertFalse(any(history.lookahead_workers()))
            history.request_lookahead(4)
            await pilot.pause()
            self.assertEqual(history.passes, [1, 4], "a request already prepared is not repeated")


if __name__ == "__main__":
    unittest.main()
