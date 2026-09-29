"""One coalesced read lifetime; each projection owns its source and reaction."""
from abc import ABC, abstractmethod
import asyncio
from weakref import ref

from toad.goal_display import GoalDisplay, GoalUnavailable


class SessionObservation(ABC):
    errors = (OSError, ValueError)

    def __init__(self, view):
        self._view = ref(view)
        self.revision = 0
        self.task = None

    @property
    def view(self):
        return self._view() if self._view is not None else None

    @property
    def active(self):
        return self.task is not None and not self.task.done()

    def invalidate(self):
        view = self.view
        if view is None or not view.is_attached or view.agent is None:
            return
        self.revision += 1
        if not self.active:
            self.task = asyncio.create_task(self._run())

    async def refresh(self):
        self.invalidate()
        task = self.task
        if task is not None:
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                # Source retirement owns cancellation of its read. A callback
                # awaiting that read must not cancel the retained UI pump.
                if self.view is None and task.cancelled() and not asyncio.current_task().cancelling():
                    return
                raise

    async def close(self):
        self._view = None
        self.revision += 1
        if self.active:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.task = None

    async def _run(self):
        while (view := self.view) is not None and view.is_attached:
            revision, agent = self.revision, view.agent
            if agent is None:
                return
            try:
                result = await self.read(agent)
            except self.errors as error:
                if self.view is not view or not view.is_attached:
                    return
                if revision != self.revision or agent is not view.agent:
                    continue
                self.failed(view, error)
                return
            if self.view is not view or not view.is_attached:
                return
            if revision != self.revision or agent is not view.agent:
                continue
            self.publish(view, result)
            return

    @abstractmethod
    async def read(self, agent): ...

    @abstractmethod
    def publish(self, view, result): ...

    @abstractmethod
    def failed(self, view, error): ...


class GoalObservation(SessionObservation):
    async def read(self, agent):
        return await agent.get_goal_snapshot()

    def publish(self, view, result):
        goal, execution = result
        view.goal_display = GoalDisplay.current(goal)
        view.goal_execution = execution

    def failed(self, view, error):
        view.goal_display = GoalUnavailable(view.goal_display.snapshot)


class InputDeliveryObservation(SessionObservation):
    errors = (OSError, ValueError, RuntimeError, TimeoutError, KeyError)

    async def read(self, agent):
        return await agent.get_input_delivery()

    def publish(self, view, result):
        view.input_delivery = result
        view.input_delivery_error = ""

    def failed(self, view, error):
        view.input_delivery_error = f"Delivery unavailable: {error}"

    def require_owner(self, agent):
        if self.view is None or not self.view.is_attached or agent is not self.view.agent:
            raise ValueError("The connected owner changed; inspect delivery again.")

    def current_owner(self):
        view = self.view
        if view is None or not view.is_attached:
            raise ValueError("The connected owner changed; inspect delivery again.")
        if view.agent is None:
            raise ValueError("No connected owner.")
        return view.agent

    async def history(self):
        agent = self.current_owner()
        while True:
            revision = self.revision
            result = await agent.get_input_delivery(include_history=True)
            self.require_owner(agent)
            if revision != self.revision:
                continue
            await self.refresh()
            self.require_owner(agent)
            if self.view.input_delivery_error:
                raise ValueError(self.view.input_delivery_error)
            if revision + 1 != self.revision or any(
                result[key] != self.view.input_delivery[key]
                for key in ("historicalCount", "dismissedHistoricalCount")
            ):
                continue
            return result["historicalInputs"]

    async def dismiss_history(self):
        agent = self.current_owner()
        await agent.dismiss_historical_inputs()
        self.require_owner(agent)
        await self.refresh()
        self.require_owner(agent)
        if self.view.input_delivery_error:
            raise ValueError(self.view.input_delivery_error)
