"""A page's messages draw their files as chips, from one read beside the page, and a chip's
link fetches the very bytes that were sent."""

import base64
import os
from pathlib import Path

from agent_comms.comms import Comms
from agent_comms.execution.launch_root import LaunchRoot
from agent_comms.messaging.channel_targets import ChannelTarget
from agent_comms.messaging.historical_views import UnobservedConversation
from agent_comms.messaging.message_files import FileUpload
from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.threads import NativeThread
from agent_comms.transport.request import CoreAccess
from agent_comms.transport.tool_caller import HumanCaller
from agent_comms.transport.tool_request import ServedRequest
from agent_comms.transport.tools.served import ServedCommsUserSendTool
from support.agents import AppAgents
from support.roots import installed_wire

from toad.client.conversation import ChannelConversation
from toad.client.history import WireSource
from toad.client.history_preparation import OLDER_END, PageRequest
from toad.client.line_blocks import Spans
from toad.client.message_file_links import MessageFileLink
from toad.message_rows import IrcMessageStyle
from toad.widgets.wire_history import WireFragment


class ServedCore(CoreAccess):
    """This test's Core, every request served in process as the human caller, the caller the
    observation child serves a UI's reads as."""

    def __init__(self, comms: Comms) -> None:
        self.comms = comms
        self.called: list[str] = []

    def call(self, request):
        self.called.append(request.declared_name)
        return ServedRequest.serving(request).apply_without_thread(self.comms, HumanCaller())

    def serves(self, request_type) -> bool:
        return True


def test_a_page_draws_each_message_s_files_and_a_chip_fetches_the_sent_bytes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    comms = installed_wire(tmp_path / "wire")
    comms.registry.declare(NativeThread("peer", frozenset({"team"}), Checkout(tmp_path)))
    content = os.urandom(3000)
    HumanCaller().invoke(ServedCommsUserSendTool(target="#team", body="the trace", files=(
        FileUpload("trace.bin", "application/octet-stream", base64.b64encode(content).decode()),)), comms)
    HumanCaller().invoke(ServedCommsUserSendTool(target="#team", body="no file"), comms)
    project = Checkout(tmp_path)
    core = ServedCore(comms)
    source = WireSource(comms.root, ChannelConversation(ChannelTarget("#team")), project,
                        comms.messaging.user_identity(project).name, IrcMessageStyle(),
                        access=AppAgents.unrun(project.path, LaunchRoot.from_path(comms.root)).app.coordination_access,
                        core=core, fragments=WireFragment)
    through = source.observe(UnobservedConversation()).through
    prepared = source.read(PageRequest(OLDER_END, through), through)
    assert core.called.count("comms_message_files") == 1
    with_file, without = prepared.fragments
    chips = [span for block in with_file.blocks(with_file.shown) if isinstance(block, Spans)
             for span in block.spans if isinstance(span.link, MessageFileLink)]
    assert [span.text for span in chips] == ["[trace.bin · 2.9 KB]"]
    assert not [span for block in without.blocks(without.shown) if isinstance(block, Spans)
                for span in block.spans if isinstance(span.link, MessageFileLink)]
    (link,) = (span.link for span in chips)
    assert (link.conversation, link.root) == ("#team", str(comms.root))
    kept = link.fetched(core)
    assert kept.read_bytes() == content
    assert kept.is_relative_to(tmp_path / "data") and kept.name == "trace.bin"
