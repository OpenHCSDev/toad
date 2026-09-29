import asyncio
from pathlib import Path
from toad.input_history import InputHistories, InputHistory


def test_real_files_mode_navigation_binding_and_new_case(tmp_path: Path):
    class ReviewInputHistory(InputHistory):
        @classmethod
        def history_path(cls, directory, scope):
            return directory / f"review-{scope}.jsonl"

        def skips(self, entry, reference):
            return False

    async def acceptance():
        histories = InputHistories(tmp_path, "thread-a")
        for text in ("first", "second", "second"):
            await histories.shell.record(text)
        assert (await histories.shell.navigate(-1, "shell draft")).input == "second"
        assert (await histories.shell.navigate(-1, "second")).input == "first"
        assert (await histories.shell.navigate(1, "first")).input == "second"
        assert (await histories.shell.navigate(1, "second")).input == "shell draft"
        await histories.prompt.record("prompt only")
        assert (await histories.prompt.navigate(-1, "prompt draft")).input == "prompt only"
        assert (await histories.prompt.navigate(1, "prompt only")).input == "prompt draft"
        await histories.history(ReviewInputHistory).record("review only")
        prompt, shell, review = histories.prompt, histories.shell, histories.history(ReviewInputHistory)
        histories.bind_scope("thread-a")
        assert histories.prompt is prompt
        histories.bind_scope("thread-b")
        assert histories.shell is shell and histories.prompt is not prompt
        assert histories.history(ReviewInputHistory) is not review
        assert histories.prompt.size == 0
        histories.bind_scope("thread-a")
        assert (await histories.prompt.navigate(-1, "")).input == "prompt only"
        assert histories.shell.index == 0

    try:
        asyncio.run(acceptance())
    finally:
        InputHistory.__registry__.pop(ReviewInputHistory.declared_name)
