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

from agent_comms.pi_vocabulary import OffThinkingLevel
from agent_comms.thread_model import DeclaredModel

from support.roots import installed_wire

PROVIDER = "selected-offline"
MODEL = DeclaredModel(f"{PROVIDER}/fixture")
KEY = "offline-only-fixture"


def last_user_texts(request: dict) -> tuple[str, ...]:
    message = request["messages"][-1]
    if message["role"] != "user":
        return ()
    content = message["content"]
    return (content,) if isinstance(content, str) else tuple(
        block["text"] for block in content if block["type"] == "text")


def selected_triage_reply(request: dict, decision=None) -> dict | None:
    """The answer to Core's "should this thread respond" question, when `request` is one."""
    from agent_comms.field_codec import FieldCodec
    from agent_comms.selected_triage import IgnoreSelectedTriage, SelectedTriage
    from agent_comms.turn_context import InstructionFile

    texts = last_user_texts(request)
    output = InstructionFile.read("selected-triage-output.md").render(SelectedTriage.output_values()).strip()
    if not any(text.rstrip().endswith(output) for text in texts):
        return None
    return {"role": "assistant", "content": json.dumps(FieldCodec.encode(
        IgnoreSelectedTriage() if decision is None else decision))}


def numbered_reply(request: dict, number: int) -> tuple[dict, str]:
    """Declines triage questions and answers anything else ``NATIVE_RESPONSE_<n>``."""
    answer = f"NATIVE_RESPONSE_{number}"
    return (selected_triage_reply(request)
            or {"role": "assistant", "content": answer}), "stop"


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


def start_private_native_wire(root: Path):
    """Create a private root; Core derives its root identity and reviewed package."""
    comms = installed_wire(root)
    for key in ("PI_PROMPT", "PI_PARENT_ID", "PI_AGENT_ID"):
        os.environ.pop(key, None)
    return comms


def configure_provider(base_url: str, *, settings: dict | None = None) -> None:
    """Point the native agent at the controlled provider, in this test's Pi settings directory."""
    config = Path(os.environ["PI_CODING_AGENT_DIR"])
    config.mkdir(mode=0o700, parents=True, exist_ok=True)
    (config / "models.json").write_text(json.dumps({"providers": {PROVIDER: {
        "baseUrl": base_url, "api": "openai-completions",
        "models": [{"id": "fixture", "name": "Offline fixture", "reasoning": True,
                    "contextWindow": 32768, "maxTokens": 2048}],
    }}}))
    (config / "auth.json").write_text(json.dumps({PROVIDER: {"type": "api_key", "key": KEY}}))
    if settings is not None:
        (config / "settings.json").write_text(json.dumps(settings))
    os.environ.update(
        AGENT_COMMS_AGENT_BIN="pi",
        AGENT_COMMS_AGENT_ARGS=f"--provider {PROVIDER} --model fixture --no-extensions --no-skills --no-context-files",
        AGENT_COMMS_AGENT_MODELS=MODEL.text,
    )


def comms_agent():
    """The agent definition for Core's own ACP server (``python -m agent_comms.acp``)."""
    from toad.agent_schema import AgentDefinition

    return AgentDefinition.decode({
        "name": "Native fixture", "identity": "native-fixture", "short_name": "native", "protocol": "acp",
        "accepts_comms_root": True,
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
async def attached_app(workspace, comms, thread: str, *, size: tuple[int, int] = (160, 44),
                       application: type | None = None, attached: bool = True, project: Path | None = None):
    """Start Toad on declared thread `thread` through Core's ACP server; yields (ui, agent) once
    the session has settled. Stops the agent and every owner on the wire afterwards."""
    from toad.app import ToadApp
    from toad.agent import AgentBase

    agent = None
    started = partial(application or ToadApp, agent_session_id=thread)
    if project is not None:
        started = partial(started, project_dir=str(project))
    try:
        async with workspace.app(size=size, agent=comms_agent(), application=_first_wins(started)) as ui:
            await ui.until(lambda: isinstance(ui.conversation.agent_binding, AgentBase), seconds=20,
                           why="the bound agent")
            agent = ui.conversation.agent_binding
            await ui.until(agent.session.settled.is_set, seconds=30, why="the ACP session to settle")
            assert agent.session.connected is attached, "Unexpected ACP attachment outcome"
            yield ui, agent
    finally:
        if agent is not None:
            await agent.stop()
        names = tuple(name for thread in comms.registry.all_threads().values()
                      for name in thread.role.executor(thread.name))
        await asyncio.to_thread(comms.owners.stop, *names)


def _first_wins(started):
    """Construct with the arguments bound here taking precedence over the caller's."""
    def construct(**given):
        return started.func(**{**given, **started.keywords})
    return construct


@asynccontextmanager
async def native_session(workspace, *, provider: ControlledProvider | None = None,
                         settings: dict | None = None, prepare=None, size: tuple[int, int] = (160, 44),
                         application: type | None = None, attached: bool = True):
    """Start Toad on a declared native thread ``beta`` whose model is the controlled provider.

    `prepare(comms, project, provider)` may arrange wire state before the app starts.
    `attached=False` expects the session to settle without a connection.
    """

    provider = provider or ControlledProvider()
    with provider.serving() as base_url:
        comms = start_private_native_wire(workspace.roots.wire)
        configure_provider(base_url, settings=settings)
        comms.registry.declare(comms.registry.new_thread(NativeSession.thread, frozenset({"team"}), str(workspace.project),
                                      model=MODEL, thinking_level=OffThinkingLevel))
        try:
            if prepare is not None:
                await prepare(comms, workspace.project, provider)
            async with attached_app(workspace, comms, NativeSession.thread, size=size, application=application,
                                    attached=attached) as (ui, agent):
                yield NativeSession(ui, agent, comms, provider, workspace.project)
                assert not provider.failures, provider.failures
        except BaseException as error:
            if provider.failures:
                error.add_note(f"Controlled provider failures: {provider.failures}")
            raise
        finally:
            provider.release()


def without_provider(models: str = "test/model") -> None:
    """Configure native owners with a model nothing serves, for tests that must never ask one."""
    os.environ.update(AGENT_COMMS_AGENT_BIN="pi", AGENT_COMMS_AGENT_ARGS="", AGENT_COMMS_AGENT_MODELS=models)
