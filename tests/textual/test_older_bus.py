"""A newer Toad on a bus older than message files: its pages draw every message with no file
chips and ask that bus for no files, compose offers no Attach, and a draft carrying files is
refused with its reason before it is sent. The phone's APK on the laptop's older bus failed
every page read on the files read that bus did not have (2026-11-18)."""

import base64
from pathlib import Path

from agent_comms.comms import Comms
from agent_comms.errors import RelationViolationError
from agent_comms.execution.launch_root import LaunchRoot
from agent_comms.messaging.channel_targets import ChannelTarget
from agent_comms.messaging.historical_views import UnobservedConversation
from agent_comms.messaging.message_files import FileUpload
from agent_comms.nominal.field_codec import FieldCodec
from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.threads import NativeThread
from agent_comms.transport.request import CoreAccess, RequestPoster
from agent_comms.transport.tool_caller import HumanCaller
from agent_comms.transport.tool_request import ServedRequest
from agent_comms.transport.tools.served import ServedCommsUserSendTool
from agent_comms.transport.tools.sidebar import CommsMessageFilesTool, CommsMessageFileTool
from support.agents import AppAgents
from support.roots import installed_wire

from toad.client.bus_submission import TypedText
from toad.client.conversation import ChannelConversation
from toad.client.history import WireSource
from toad.client.history_preparation import OLDER_END, PageRequest
from toad.client.line_blocks import Spans
from toad.client.message_file_links import MessageFileLink
from toad.client.message_files import MessagePromptComposer
from toad.client.submission import ComposeAccess
from toad.message_rows import IrcMessageStyle
from toad.widgets.wire_history import WireFragment

UNEXPOSED = frozenset({CommsMessageFilesTool.declared_name, CommsMessageFileTool.declared_name})


class OlderBusCore(CoreAccess, RequestPoster):
    """A remote Core on a bus older than message files: each request is posted, as across the
    connector, and that connector serves every tool but the two file reads, refusing one it
    lacks as it did then, with an undifferentiated refusal."""

    def __init__(self, comms: Comms) -> None:
        self.comms = comms
        self.posted: list[str] = []

    def call(self, request):
        return FieldCodec.decode(request.result_type(), request.posted(self))

    def serves(self, request_type) -> bool:
        return request_type.declared_name not in UNEXPOSED

    def forget_served(self) -> None:
        """This connector's tools never change."""

    def post(self, request):
        self.posted.append(request.declared_name)
        if request.declared_name in UNEXPOSED:
            raise RelationViolationError(f"The connector exposes no tool {request.declared_name!r}.")
        return FieldCodec.encode(ServedRequest.serving(request).apply_without_thread(self.comms, HumanCaller()))

    def exchange(self, request):
        return self.post(request)

    def post_observed(self, request):
        return self.post(request)


def older_bus(tmp_path: Path) -> tuple[Comms, OlderBusCore, Checkout]:
    comms = installed_wire(tmp_path / "wire")
    comms.registry.declare(NativeThread("peer", frozenset({"team"}), Checkout(tmp_path)))
    for body in ("first", "second"):
        HumanCaller().invoke(ServedCommsUserSendTool(target="#team", body=body), comms)
    return comms, OlderBusCore(comms), Checkout(tmp_path)


def test_a_page_from_an_older_bus_draws_its_messages_and_asks_it_for_no_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    comms, core, project = older_bus(tmp_path)
    source = WireSource(comms.root, ChannelConversation(ChannelTarget("#team")), project,
                        comms.messaging.user_identity(project).name, IrcMessageStyle(),
                        access=AppAgents.unrun(project.path, LaunchRoot.from_path(comms.root)).app.coordination_access,
                        core=core, fragments=WireFragment)
    through = source.observe(UnobservedConversation()).through
    prepared = source.read(PageRequest(OLDER_END, through), through)
    assert len(prepared.fragments) == 2
    assert not [span for fragment in prepared.fragments for block in fragment.blocks(fragment.shown)
                if isinstance(block, Spans) for span in block.spans if isinstance(span.link, MessageFileLink)]
    assert CommsMessageFilesTool.declared_name not in core.posted


def test_compose_on_an_older_bus_takes_no_files(tmp_path: Path) -> None:
    _, core, _ = older_bus(tmp_path)
    access = ChannelConversation(ChannelTarget("#team")).compose_access(core)
    assert access == ComposeAccess(read_only=False, takes_files=False)
    upload = FileUpload("a.txt", "text/plain", base64.b64encode(b"a").decode())
    assert access.refuses(TypedText("with a file", (upload,)))
    assert not access.refuses(TypedText("plain", ()))
    assert not ComposeAccess(read_only=False, takes_files=True).refuses(TypedText("with a file", (upload,)))


class Composer(MessagePromptComposer):
    """The shared message composer with only its drawing recorded."""

    settings = None

    def __init__(self) -> None:
        self.offered: list[bool] = []
        self.failures: list[str] = []
        self.opened = 0

    def show_files_offered(self) -> None:
        self.offered.append(self.takes_files)

    def pick_in_window(self) -> None:
        self.opened += 1

    def pick_by_path_search(self) -> None:
        self.opened += 1

    def show_attached(self) -> None: ...

    def sync_queue(self) -> None: ...

    def show_failure(self, text: str) -> None:
        self.failures.append(text)

    def append_to_draft(self, suffix: str) -> None: ...


def test_a_composer_on_an_older_bus_offers_no_attach_and_says_why() -> None:
    composer = Composer()
    composer.offer_files(True)
    assert composer.offered == []  # open until the bus answers: no change, nothing redrawn
    composer.offer_files(False)
    assert composer.offered == [False]
    composer.attach_file()
    assert composer.opened == 0 and composer.failures == [ComposeAccess.files_refused_reason]
