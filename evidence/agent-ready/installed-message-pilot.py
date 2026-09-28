import asyncio
import toad.agent
from textual.app import App
from textual import on
from toad.agent import AgentReady

class MountedDelivery(App):
    def __init__(self):
        super().__init__()
        self.delivered = asyncio.Event()

    @on(AgentReady)
    def ready(self, message):
        assert not message.reconnected
        self.delivered.set()

async def main():
    app = MountedDelivery()
    async with app.run_test() as pilot:
        assert app.post_message(AgentReady())
        await asyncio.wait_for(app.delivered.wait(), 3)
        await pilot.pause()
        assert app._exception is None
    print('PASS: installed AgentReady through mounted Textual message dispatch')
    print(toad.agent.__file__)

if __name__ == '__main__':
    asyncio.run(main())
