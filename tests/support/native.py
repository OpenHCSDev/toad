"""The real native agent (the Pi package Core starts) behind Toad, with a provider the test controls.

Nothing here reaches a real model: the native agent is configured with one
provider, a loopback HTTP endpoint in this process that answers what the test
tells it to. The wire, the Pi settings and the project are the test's private roots.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shlex
import sys
import threading

PROVIDER = "selected-offline"
MODEL = f"{PROVIDER}/fixture"
KEY = "offline-only-fixture"


def selected_triage_reply(request: dict, decision=None) -> dict | None:
    """The answer to Core's "should this thread respond" question, when `request` is one."""
    from agent_comms.field_codec import FieldCodec
    from agent_comms.selected_triage import IgnoreSelectedTriage, SelectedTriage
    from agent_comms.turn_context import InstructionFile

    message = request["messages"][-1]
    if message["role"] != "user":
        return None
    content = message["content"]
    texts = (content,) if isinstance(content, str) else tuple(
        block["text"] for block in content if block["type"] == "text")
    output = InstructionFile.read("selected-triage-output.md").render(SelectedTriage.output_values()).strip()
    if not any(text.rstrip().endswith(output) for text in texts):
        return None
    return {"role": "assistant", "content": json.dumps(FieldCodec.encode(
        IgnoreSelectedTriage() if decision is None else decision))}


def numbered_reply(request: dict, number: int) -> tuple[dict, str]:
    """Declines triage questions and answers anything else ``NATIVE_RESPONSE_<n>``."""
    return (selected_triage_reply(request)
            or {"role": "assistant", "content": f"NATIVE_RESPONSE_{number}"}), "stop"


def small_usage(request: dict, number: int) -> dict:
    return {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}


@dataclass
class ControlledProvider:
    """A loopback chat-completions endpoint: records each request and streams the chosen reply."""

    reply: Callable[[dict, int], tuple[dict, str]] = numbered_reply
    usage: Callable[[dict, int], dict] = small_usage
    request_budget: int = 12
    chunk_characters: int | None = None
    after_chunk: Callable[[int, int], None] | None = None
    expected_disconnects: frozenset[int] = frozenset()
    requests: list[dict] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    entered: threading.Event = field(default_factory=threading.Event)
    released: threading.Event = field(default_factory=threading.Event)
    holding: threading.Event = field(default_factory=threading.Event)

    def hold_next_request(self) -> None:
        """The next request waits, after setting `entered`, until `release()`."""
        self.entered.clear()
        self.released.clear()
        self.holding.set()

    def release(self) -> None:
        self.released.set()

    def answer(self, handler: BaseHTTPRequestHandler) -> None:
        number = None
        try:
            request = json.loads(handler.rfile.read(int(handler.headers["Content-Length"])))
            self.requests.append(request)
            number = len(self.requests)
            assert request["model"] == "fixture"
            assert handler.headers["Authorization"] == f"Bearer {KEY}"
            assert number <= self.request_budget, "The native agent keeps asking the model"
            if self.holding.is_set():
                self.holding.clear()
                self.entered.set()
                assert self.released.wait(20), "The test never released the held model reply"
            reply, finish_reason = self.reply(request, number)
            chunk = {"id": "offline", "object": "chat.completion.chunk", "created": 1, "model": "fixture",
                     "choices": [{"index": 0, "delta": reply, "finish_reason": None}]}
            final = {**chunk, "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
                     "usage": self.usage(request, number)}
            chunks = [chunk]
            if self.chunk_characters is not None:
                text = reply.get("content", "")
                chunks = [{**chunk, "choices": [{"index": 0, "delta": {
                    **({"role": "assistant"} if offset == 0 else {}),
                    "content": text[offset:offset + self.chunk_characters],
                }, "finish_reason": None}]} for offset in range(0, len(text), self.chunk_characters)]
            rows = [("data: " + json.dumps(row) + "\n\n").encode() for row in (*chunks, final)]
            handler.send_response(200)
            handler.send_header("Content-Type", "text/event-stream")
            if self.after_chunk is None:
                body = b"".join(rows) + b"data: [DONE]\n\n"
                handler.send_header("Content-Length", str(len(body)))
                handler.end_headers()
                handler.wfile.write(body)
                return
            handler.end_headers()
            for index, row in enumerate(rows):
                handler.wfile.write(row)
                handler.wfile.flush()
                self.after_chunk(number, index)
            handler.wfile.write(b"data: [DONE]\n\n")
        except BrokenPipeError:
            if number not in self.expected_disconnects:
                self.failures.append(f"request {number}: the native agent closed the reply early")
        except Exception as error:
            self.failures.append(repr(error))
            try:
                handler.send_error(400, "Controlled provider failed")
            except OSError:
                pass

    @contextmanager
    def serving(self):
        """Serve on a free loopback port; yields the base URL."""
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                provider.answer(self)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/v1"
        finally:
            self.release()
            server.shutdown()
            server.server_close()


def start_private_native_wire(root: Path, package: Path):
    """Create the test's wire and make it the route native owners launch on, with `package`."""
    from agent_comms.comms import Comms

    comms = Comms(root)
    root_id = comms.messaging.initialize_private_initial_protocol()
    comms.owners.pin_private_nk_launch(comms.root, root_id, package)
    os.environ.update(
        AGENT_COMMS_ROOT=str(comms.root),
        AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=root_id,
        AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=str(package),
    )
    for key in ("PI_PROMPT", "PI_PARENT_ID", "PI_AGENT_ID"):
        os.environ.pop(key, None)
    return comms


def configure_provider(base_url: str, *, settings: dict | None = None) -> None:
    """Point the native agent at the controlled provider, in this test's Pi settings directory."""
    config = Path(os.environ["PI_CODING_AGENT_DIR"])
    config.mkdir(mode=0o700, parents=True, exist_ok=True)
    (config / "models.json").write_text(json.dumps({"providers": {PROVIDER: {
        "baseUrl": base_url, "api": "openai-completions",
        "models": [{"id": "fixture", "name": "Offline fixture", "contextWindow": 32768, "maxTokens": 2048}],
    }}}))
    (config / "auth.json").write_text(json.dumps({PROVIDER: {"type": "api_key", "key": KEY}}))
    if settings is not None:
        (config / "settings.json").write_text(json.dumps(settings))
    os.environ.update(
        AGENT_COMMS_AGENT_BIN="pi",
        AGENT_COMMS_AGENT_ARGS=f"--provider {PROVIDER} --model fixture --no-extensions --no-skills --no-context-files",
        AGENT_COMMS_AGENT_MODELS=MODEL,
    )


def comms_agent():
    """The agent definition for Core's own ACP server (``python -m agent_comms.acp``)."""
    from toad.agent_schema import AgentDefinition

    return AgentDefinition.decode({
        "name": "Native fixture", "identity": "native-fixture", "short_name": "native", "protocol": "acp",
        "run_command": {"*": shlex.join([sys.executable, "-m", "agent_comms.acp"])},
    })


@dataclass
class NativeSession:
    """Toad attached to the native thread ``beta`` of a private wire."""

    ui: object
    agent: object
    comms: object
    provider: ControlledProvider
    project: Path
    thread: str = "beta"

    @property
    def executing(self) -> bool:
        return self.comms.registry.require(self.thread).executing


@asynccontextmanager
async def native_session(workspace, package: Path, *, provider: ControlledProvider | None = None,
                         settings: dict | None = None, prepare=None, size: tuple[int, int] = (160, 44),
                         application: type | None = None, attached: bool = True):
    """Start Toad on a declared native thread ``beta`` and wait for its ACP session to settle.

    `prepare(comms, project, provider)` may arrange wire state before the app starts.
    `attached=False` expects the session to settle without a connection.
    """
    from agent_comms.threads import Thread
    from toad.app import ToadApp

    provider = provider or ControlledProvider()
    agent = None
    with provider.serving() as base_url:
        comms = start_private_native_wire(workspace.roots.wire, package)
        configure_provider(base_url, settings=settings)
        comms.registry.declare(Thread("beta", frozenset({"team"}), str(workspace.project),
                                      model=MODEL, thinking_level="off"))
        try:
            if prepare is not None:
                await prepare(comms, workspace.project, provider)
            started = partial(application or ToadApp, agent_session_id="beta")
            async with workspace.app(size=size, agent=comms_agent(), application=started) as ui:
                await ui.until(lambda: ui.conversation.agent is not None, seconds=20, why="the agent object")
                agent = ui.conversation.agent
                await ui.until(agent.session.settled.is_set, seconds=30, why="the ACP session to settle")
                assert agent.session.connected is attached, "Unexpected ACP attachment outcome"
                yield NativeSession(ui, agent, comms, provider, workspace.project)
                assert not provider.failures, provider.failures
        finally:
            provider.release()
            if agent is not None:
                await agent.stop()
            for name in comms.registry.all_threads():
                await asyncio.to_thread(comms.owners.stop, name)
