"""Textual-facing: a SessionObservation reads for a mounted view, and Textual's mount and removal bound its lifetime."""

import asyncio

import pytest
from textual.app import App
from textual.widget import Widget

from toad.session_observation import InputDeliveryObservation, SessionObservation


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


async def next_read(observation):
    async with asyncio.timeout(10):
        return await observation.entered.get()


async def test_invalidation_during_a_read_supersedes_its_result():
    view, app = ProbeView(), App()
    observation = ProbeObservation(view)
    async with app.run_test():
        await app.screen.mount(view)
        observation.invalidate()
        assert await next_read(observation) is view.agent
        observation.invalidate()
        observation.responses.put_nowait("superseded")
        assert await next_read(observation) is view.agent
        assert view.result is None
        observation.responses.put_nowait("current")
        await observation.task
        assert view.result == "current"
        assert app._exception is None


async def test_a_read_for_a_previous_agent_is_not_published():
    view, app = ProbeView(), App()
    observation = ProbeObservation(view)
    async with app.run_test():
        await app.screen.mount(view)
        observation.invalidate()
        assert await next_read(observation) is view.agent
        observation.responses.put_nowait("current")
        await observation.task
        observation.invalidate()
        previous = await next_read(observation)
        view.agent = object()
        observation.responses.put_nowait("previous owner")
        assert await next_read(observation) is view.agent and view.agent is not previous
        assert view.result == "current"
        assert app._exception is None


async def test_a_closed_observation_starts_no_read_and_delivery_actions_refuse():
    view, app = ProbeView(), App()
    observation = ProbeObservation(view)
    async with app.run_test() as pilot:
        await app.screen.mount(view)
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
