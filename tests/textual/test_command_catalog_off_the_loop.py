"""A command's applicability is read on the preparation worker, never on the event loop. Over
the connector it is a Core round trip (DirectMessagesCommand.available asks for the peer's
registry slice); read from CommandCatalog.commands on the loop, every catalog refresh froze a
remote Toad's UI for that round trip."""

import asyncio
import threading
from dataclasses import dataclass

from agent_comms.errors import UnregisteredThreadError

from toad.command_catalog import CommandCatalog


@dataclass(frozen=True)
class AskingCommand:
    """An advertised command whose applicability, like a remote one, is a read."""

    command: str
    asked_on: list

    def completion(self, context):
        self.asked_on.append(threading.current_thread())
        return [self.command]

    def target_choices(self, context):
        self.asked_on.append(threading.current_thread())
        return ()


class Preparation:
    async def run_thread(self, function, *args):
        return await asyncio.to_thread(function, *args)


class App:
    preparation = Preparation()


async def unbound_context():
    raise UnregisteredThreadError("a view with no backend thread")


async def test_a_catalog_is_projected_off_the_event_loop():
    asked_on = []
    catalog = await CommandCatalog.read(App(), [AskingCommand("/asks", asked_on)], unbound_context())
    assert "/asks" in catalog.commands
    assert asked_on and threading.main_thread() not in asked_on
