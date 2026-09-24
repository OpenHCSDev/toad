"""Ctrl+V captures a PNG without blocking and forwards it through real ACP/Pi RPC."""

import asyncio
import base64
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from runtime_fixture import ToadApp
from toad.prompt.extract import extract_paths_from_prompt
from toad.widgets.agent_response import AgentResponse

PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aDqkAAAAASUVORK5CYII="


async def until(predicate):
    async with asyncio.timeout(15):
        while not predicate():
            await asyncio.sleep(.02)


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-image-paste-") as directory:
        root = Path(directory)
        capture = root / "prompts.jsonl"
        stub = root / "pi-images"
        stub.write_text(f"#!{sys.executable}\n" + """
import json, os, sys
def emit(data): print(json.dumps(data), flush=True)
for line in sys.stdin:
    command = json.loads(line)
    kind = command['type']
    if kind == 'prompt':
        emit({'type': 'response', 'id': command.get('id'), 'command': kind, 'success': True})
        with open(os.environ['TEST_IMAGE_CAPTURE'], 'a') as output:
            output.write(json.dumps(command) + '\\n')
        emit({'type': 'message_update', 'assistantMessageEvent': {
            'type': 'text_delta', 'delta': 'IMAGE-RECEIVED:' + str(len(command.get('images', [])))}})
        emit({'type': 'agent_settled'})
    else:
        emit({'type': 'response', 'id': command.get('id'), 'command': kind, 'success': True, 'data': {}})
""")
        stub.chmod(0o755)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data with spaces"), AGENT_COMMS_ROOT=str(root / "wire"),
                          AGENT_COMMS_AGENT_BIN=str(stub), AGENT_COMMS_AGENT_ARGS="--model test/image",
                          AGENT_COMMS_AGENT_MODELS="test/image", TEST_IMAGE_CAPTURE=str(capture))
        agent = {"name": "Image test", "identity": "images-test", "short_name": "images",
                 "run_command": {"*": f"{sys.executable} -m agent_comms.acp"}, "protocol": "acp"}
        app = ToadApp(project_dir=str(root), agent_data=agent)
        async with app.run_test(size=(120, 40)) as pilot:
            await until(lambda: getattr(app.screen, "conversation", None) is not None
                        and app.screen.conversation.agent_ready)
            view = app.screen.conversation
            started, release = asyncio.Event(), asyncio.Event()

            async def clipboard_image():
                started.set()
                await release.wait()
                return base64.b64decode(PNG)

            with patch("toad.clipboard_image.read_clipboard_png", clipboard_image):
                view.prompt.focus()
                await pilot.press("ctrl+v")
                await asyncio.wait_for(started.wait(), 3)
                await pilot.press(*"Inspect image")
                assert view.prompt.text == "Inspect image"
                release.set()
                await until(lambda: "clipboard-" in view.prompt.text)
                assert len(list(extract_paths_from_prompt(view.prompt.text))) == 1, view.prompt.text
                reference = next(extract_paths_from_prompt(view.prompt.text))[0]
                attachment = Path(reference)
                assert attachment.read_bytes() == base64.b64decode(PNG)
                assert attachment.stat().st_mode & 0o777 == 0o600
                assert view.agent.supports_prompt_images
                original = view.prompt.text.strip()
                view.agent.supports_prompt_images = False
                await pilot.press("enter")
                await until(lambda: view.prompt.text == original)
                assert not capture.exists() and app._exception is None
                view.agent.supports_prompt_images = True
                await pilot.press("enter")
                await until(lambda: capture.exists() and view.turn == "client")
                sent = [json.loads(line) for line in capture.read_text().splitlines()]
                assert sent[-1]["images"] == [{"type": "image", "data": PNG, "mimeType": "image/png"}], sent[-1]["images"]
                assert "Inspect image" in sent[-1]["message"]
                assert str(attachment) not in sent[-1]["message"]
                await until(lambda: any("IMAGE-RECEIVED:1" in block.source for block in view.query(AgentResponse)))
                # An image-only prompt must launch a coding turn rather than
                # treating its @file reference as a direct-message recipient.
                await pilot.press("ctrl+v")
                await until(lambda: "clipboard-" in view.prompt.text)
                await pilot.press("enter")
                await until(lambda: len(capture.read_text().splitlines()) == 2 and view.turn == "client")
                assert json.loads(capture.read_text().splitlines()[-1])["images"][0]["data"] == PNG
            async def no_image():
                return None
            with patch("toad.clipboard_image.read_clipboard_png", no_image), patch("pyperclip.paste", return_value="first\nsecond"):
                view.prompt.focus()
                await pilot.press("ctrl+v")
                await until(lambda: view.prompt.text == "first\nsecond")
                await pilot.press("enter")
                await until(lambda: len(capture.read_text().splitlines()) == 3 and view.turn == "client")
                assert "images" not in json.loads(capture.read_text().splitlines()[-1])
    print("image paste: responsive capture, private retained attachment, image-only and captioned RPC, text fallback")


if __name__ == "__main__":
    asyncio.run(main())
