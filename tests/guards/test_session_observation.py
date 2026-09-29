"""Retired root readers cannot return; one new case inherits source fencing."""
import ast
import asyncio
from pathlib import Path
import pytest
from textual.app import App
from textual.widget import Widget
from toad.session_observation import SessionObservation, InputDeliveryObservation


def test_retired_root_readers_deleted():
    source = Path(__file__).parents[2] / 'src/toad/widgets/conversation.py'
    retired = {'_goal_refresh_task', '_goal_refresh_revision', '_delivery_refresh_task',
               '_delivery_refresh_revision', '_read_goal_snapshot', '_read_input_dispositions',
               '_load_delivery_history', '_dismiss_delivery_history', 'refresh_goal',
               'refresh_input_dispositions', '_invalidate_goal_snapshot', '_invalidate_input_dispositions'}
    for node in ast.walk(ast.parse(source.read_text())):
        if isinstance(node, ast.Attribute):
            assert node.attr not in retired
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.name not in retired


@pytest.mark.asyncio
async def test_new_case_inherits_coalescing_owner_fence_and_retirement():
    class ProbeObservation(SessionObservation):
        def __init__(self, view):
            super().__init__(view)
            self.responses = asyncio.Queue()
            self.entered = asyncio.Queue()

        async def read(self, agent):
            self.entered.put_nowait(agent)
            return await self.responses.get()

        def publish(self, view, result):
            view.result = result

        def failed(self, view, error):
            view.error = error

    class ProbeView(Widget):
        result = None
        error = None
        agent = object()

    view = ProbeView()
    app = App()
    observation = ProbeObservation(view)
    async with app.run_test() as pilot:
        await app.screen.mount(view)
        observation.invalidate()
        assert await observation.entered.get() is view.agent
        observation.invalidate()
        observation.responses.put_nowait('superseded')
        assert await observation.entered.get() is view.agent
        assert view.result is None
        observation.responses.put_nowait('current')
        await observation.task
        assert view.result == 'current'
        observation.invalidate()
        previous = await observation.entered.get()
        view.agent = object()
        observation.responses.put_nowait('previous owner')
        assert await observation.entered.get() is view.agent and view.agent is not previous
        assert view.result == 'current'
        await observation.close()
        observation.invalidate()
        assert observation.task is None and observation.view is None
        delivery = InputDeliveryObservation(view)
        await delivery.close()
        for action in (delivery.history, delivery.dismiss_history):
            with pytest.raises(ValueError, match="connected owner changed"):
                await action()
        await view.remove()
        await pilot.pause()
        assert app._exception is None
