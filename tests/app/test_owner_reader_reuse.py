"""Owner requests share one registry reader, built off the UI thread, and never send for a replaced owner."""

import asyncio
import threading
from unittest.mock import patch

import pytest
from agent_comms.comms import wire
from agent_comms.runtime import RuntimeProxy
from agent_comms.threads import Thread

from support.coordination import registered_coordination_fact


def two_wires_with_an_owner(workspace):
    roots = [workspace.roots.wire, workspace.roots.wire.parent / "second"]
    owners = [wire(root) for root in roots]
    for comms in owners:
        comms.registry.declare(Thread("owner", frozenset(), str(workspace.project)))
    return owners


def bind(agent, comms, workspace):
    agent.coordination = registered_coordination_fact(comms, "owner", worktree=str(workspace.project))


async def test_concurrent_owner_requests_share_one_reader_and_a_changed_root_builds_another(workspace):
    first, second = two_wires_with_an_owner(workspace)
    agent = workspace.agents.detached_agent()
    bind(agent, first, workspace)
    ui_thread = threading.get_ident()
    constructors, requests = [], []

    def construct(source):
        constructors.append((str(source), threading.get_ident()))
        assert threading.get_ident() != ui_thread, "Registry reconstruction blocked the UI thread"
        return wire(source)

    async def request(proxy, method, **params):
        requests.append((proxy._comms, proxy.session_id, method, params))
        return {"ok": True}

    with (patch("toad.acp.transcript_reader.wire", construct), patch.object(RuntimeProxy, "request", request)):
        await asyncio.gather(*(agent.controller.request_owner("probe") for _ in range(6)))
        assert len(constructors) == 1 and len(requests) == 6
        assert all(row[0] is requests[0][0] for row in requests)
        bind(agent, second, workspace)
        await agent.controller.request_owner("probe", revision=2)
        assert len(constructors) == 2
        assert requests[-1][0].root == second.root and requests[-1][3] == {"revision": 2}


async def test_an_owner_replaced_while_the_reader_initializes_receives_no_request(workspace):
    first, second = two_wires_with_an_owner(workspace)
    agent = workspace.agents.detached_agent()
    bind(agent, first, workspace)
    requests = []

    async def request(proxy, method, **params):
        requests.append(method)
        return {"ok": True}

    entered, release = threading.Event(), threading.Event()

    def blocked(source):
        entered.set()
        if not release.wait(5):
            raise TimeoutError("Fixture did not release owner initialization")
        return wire(source)

    try:
        with (patch("toad.acp.transcript_reader.wire", blocked), patch.object(RuntimeProxy, "request", request)):
            pending = asyncio.create_task(agent.controller.request_owner("must-not-send"))
            assert await asyncio.to_thread(entered.wait, 2)
            bind(agent, second, workspace)
            release.set()
            with pytest.raises(ValueError, match="identity changed"):
                await pending
    finally:
        release.set()
    assert "must-not-send" not in requests


async def test_a_bound_reader_is_the_running_interfaces_own_service(workspace):
    first, _ = two_wires_with_an_owner(workspace)
    agent = workspace.agents.detached_agent()
    bind(agent, first, workspace)
    async with workspace.app() as ui:
        ui.attach_agent(agent)
        shared = ui.core_service
        with patch("toad.acp.transcript_reader.wire", side_effect=AssertionError("Shared reader reconstructed")):
            async with agent.controller.transcripts.bind(str(shared.root)) as reader:
                assert reader is shared
        assert reader is shared
