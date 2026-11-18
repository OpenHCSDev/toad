"""A message's files are read in the conversation its reader sees it in: a channel message in
its channel, a direct message in the DM with the participant that is not the reader."""

import pytest
from agent_comms.messaging.messages import InfoKind, Message

from toad.client.message_file_links import FileReader, file_size
from toad.message_rows import MessageRow


@pytest.mark.parametrize(("sender", "target", "reader", "read"), (
    ("peer", "owner", "owner", FileReader("peer", "owner")),
    ("owner", "peer", "owner", FileReader("peer", "owner")),
    ("peer", "#team", "owner", FileReader("#team", "owner")),
), ids=("dm-incoming", "dm-outgoing", "channel"))
def test_a_row_names_the_read_its_files_are_listed_under(sender, target, reader, read):
    assert MessageRow(Message(sender, target, "body", InfoKind), reader).file_reader == read


def test_a_chip_names_its_size_as_a_reader_reads_it():
    assert [file_size(size) for size in (512, 1536, 2 * 1024 * 1024)] == ["512 B", "1.5 KB", "2.0 MB"]
