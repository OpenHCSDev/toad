"""The message composer's files, through the shared owner both frontends inherit."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field

from agent_comms.messaging.message_files import MAX_MESSAGE_FILE_BYTES

from toad.client.bus_submission import TypedText
from toad.client.message_files import FilePicker, MessagePromptComposer, PathSearchFilePicker, WindowFilePicker
from toad.client.message_file_links import file_size


@dataclass
class Input:
    file_picker: type[FilePicker]
    agent_symbol: str = "❯"


@dataclass
class Ui:
    input: Input


@dataclass
class Settings:
    ui: Ui


@dataclass
class Composer(MessagePromptComposer):
    """A frontend that records what the shared owner asks of it."""

    picker: type[FilePicker] = WindowFilePicker
    asked: list[str] = field(default_factory=list)
    text: str = ""
    submissions = None

    @property
    def settings(self):
        return Settings(Ui(Input(self.picker)))

    def pick_in_window(self) -> None:
        self.asked.append("window")

    def pick_by_path_search(self) -> None:
        self.asked.append("path search")

    def show_attached(self) -> None:
        self.asked.append(f"chips {[self.chip_label(upload) for upload in self.attached_files]}")

    def show_failure(self, text: str) -> None:
        self.asked.append(f"failure {text}")

    def show_files_offered(self) -> None:
        pass

    def sync_queue(self) -> None:
        pass

    def append_to_draft(self, suffix: str) -> None:
        self.text += suffix

    def restore_draft(self, text: str) -> None:
        self.append_to_draft(self.restored_suffix(self.text, text))


def test_attach_opens_the_picker_the_setting_names() -> None:
    for picker, asked in ((WindowFilePicker, "window"), (PathSearchFilePicker, "path search")):
        composer = Composer(picker=picker)
        composer.attach_file()
        assert composer.asked == [asked]


def test_picked_files_ride_the_send_and_come_back_with_a_returned_draft() -> None:
    composer = Composer()
    composer.file_picked("/docs/me/notes.txt", b"notes")
    composer.file_picked("shot.png", b"\x89PNG")
    assert [(upload.name, upload.mime_type) for upload in composer.attached_files] == [
        ("notes.txt", "text/plain"), ("shot.png", "image/png")]
    assert composer.asked[-1] == "chips ['notes.txt · 5 B', 'shot.png · 4 B']"
    composer.detach_file(0)
    assert [upload.name for upload in composer.attached_files] == ["shot.png"]
    sent = TypedText("look at this", composer.take_files())
    assert composer.attached_files == () and composer.asked[-1] == "chips []"
    assert base64.b64decode(sent.files[0].data) == b"\x89PNG"
    composer.restore(sent)
    assert composer.text == "look at this"
    assert composer.attached_files == sent.files


def test_a_file_past_the_message_limit_is_refused_and_attaches_nothing() -> None:
    composer = Composer()
    composer.file_picked("half.bin", b"a" * (MAX_MESSAGE_FILE_BYTES // 2 + 1))
    assert composer.read_limit == MAX_MESSAGE_FILE_BYTES // 2
    composer.file_picked("other-half.bin", b"b" * composer.read_limit)
    assert [upload.name for upload in composer.attached_files] == ["half.bin"]
    assert composer.asked[-1].startswith("failure other-half.bin not attached: ")
    composer.file_picked("empty.txt", b"")
    assert composer.asked[-1].startswith("failure empty.txt not attached: ")


def test_sizes_read_at_a_glance() -> None:
    assert [file_size(size) for size in (0, 1023, 1536, 5 * 1024 * 1024)] == [
        "0 B", "1023 B", "1.5 KB", "5.0 MB"]
