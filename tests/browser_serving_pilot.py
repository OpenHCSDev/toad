"""Installed CLI, real vendor server/Toad child and Chromium; no mocked backend."""

import asyncio
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import re
import shlex
import signal
import socket
import sys
import tempfile

from aiohttp import ClientSession, CookieJar, WSServerHandshakeError
from playwright.async_api import async_playwright
import psutil
import pyte


class LocalServer:
    def __init__(self, root, entry):
        self.root, self.entry = root, entry
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self.lines = []
        self.bootstrap = asyncio.Future()
        self.process = None

    async def __aenter__(self):
        self.root.mkdir()
        env = {
            "PATH": f"{Path(sys.executable).parent}:/usr/local/bin:/usr/bin:/bin",
            "HOME": os.environ["HOME"],
            "LANG": "C.UTF-8",
            "TERM": "xterm-256color",
            "PYTHONDONTWRITEBYTECODE": "1",
            "COLUMNS": "200",
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_STATE_HOME": str(self.root / "state"),
            "AGENT_COMMS_ROOT": str(self.root / "wire"),
            "PI_CODING_AGENT_DIR": str(self.root / "pi"),
        }
        flags = ["--host", "127.0.0.1", "--port", str(self.port)]
        if self.entry == "serve":
            args = ["serve", *flags]
        elif self.entry == "run":
            args = ["run", str(self.root), "--serve", *flags]
        else:
            # Actual installed Comms ACP adapter. No prompt is sent and no model
            # response is synthesized. The browser must render its real UI.
            from agent_comms.active_route import resolve_comms_route
            from agent_comms.comms import Comms

            root_id = Comms(self.root / "wire").messaging.initialize_private_initial_protocol()
            env["AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID"] = root_id
            env["AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE"] = str(resolve_comms_route().native_package)
            env["TOAD_LOG"] = str(self.root / "actual-acp.jsonl")
            backend = shlex.join([sys.executable, "-m", "agent_comms.acp"])
            args = ["acp", backend, "--project-dir", str(self.root), "--serve", *flags]
        self.process = await asyncio.create_subprocess_exec(
            str(Path(sys.executable).parent / "toad"),
            *args,
            cwd=self.root,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        self.reader = asyncio.create_task(self.read_output())
        try:
            self.url = await asyncio.wait_for(asyncio.shield(self.bootstrap), 15)
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def read_output(self):
        async for line in self.process.stdout:
            text = line.decode(errors="replace").rstrip()
            match = re.search(r"http://127\.0\.0\.1:\d+/\?token=[A-Za-z0-9_-]+", text)
            if match and not self.bootstrap.done():
                self.bootstrap.set_result(match.group())
            self.lines.append(re.sub(r"token=[A-Za-z0-9_-]+", "token=REDACTED", text))
            self.lines = self.lines[-60:]

    def children(self):
        return psutil.Process(self.process.pid).children(recursive=True)

    async def __aexit__(self, *_):
        if self.process is None:
            return
        # A Toad window intentionally leaves separate owners alive. Retire only
        # processes whose environment identifies this disposable browser root.
        owned = []
        for process in psutil.process_iter(["pid"]):
            try:
                if process.environ().get("AGENT_COMMS_ROOT") == str(self.root / "wire"):
                    owned.append(process)
            except psutil.NoSuchProcess, psutil.AccessDenied:
                pass
        if self.process.returncode is None:
            os.killpg(self.process.pid, signal.SIGTERM)
        for process in owned:
            try:
                process.terminate()
            except psutil.NoSuchProcess:
                pass
        try:
            await asyncio.wait_for(self.process.wait(), 5)
        except TimeoutError:
            os.killpg(self.process.pid, signal.SIGKILL)
            await self.process.wait()
        _, alive = await asyncio.to_thread(psutil.wait_procs, owned, timeout=3)
        for process in alive:
            process.kill()
        await self.reader


async def rejected_ws(client, server, headers):
    try:
        async with client.ws_connect(server.origin + "/ws", headers=headers):
            raise AssertionError("Unauthorized WebSocket accepted")
    except WSServerHandshakeError as error:
        assert error.status == 403


async def gate(client, server):
    for route in ("/", "/static/css/xterm.css", "/download/missing"):
        async with client.get(server.origin + route) as response:
            assert response.status == 403
            assert response.headers["Cache-Control"] == "no-store"
    await rejected_ws(client, server, {"Origin": server.origin})
    assert not server.children(), "Unauthenticated requests spawned a child"
    for query in ("wrong", "界"):
        async with client.get(server.origin + "/?token=" + query, allow_redirects=False) as response:
            assert response.status == 403
    async with client.get(server.url, headers={"Host": "attacker.invalid"}, allow_redirects=False) as response:
        assert response.status == 403
    async with client.get(server.url, allow_redirects=False) as response:
        assert response.status == 303 and response.headers["Location"] == "/"
        assert "HttpOnly" in response.headers["Set-Cookie"] and "SameSite=Strict" in response.headers["Set-Cookie"]
    for headers in (
        {},
        {"Origin": "null"},
        {"Origin": "https://attacker.invalid"},
        {"Origin": server.origin, "Host": "attacker.invalid"},
    ):
        await rejected_ws(client, server, headers)
    async with client.get(server.origin + "/", headers={"Origin": "null"}) as response:
        assert response.status == 403
    for route in ("/", "/static/css/xterm.css", "/download/missing"):
        async with client.get(server.origin + route, headers={"Host": "attacker.invalid"}) as response:
            assert response.status == 403
    assert not server.children(), "Rejected Origin/Host spawned a child"
    async with client.get(server.origin + "/") as response:
        assert response.status == 200 and "token=" not in await response.text()
    async with client.get(server.origin + "/static/css/xterm.css") as response:
        assert response.status == 200 and response.headers["Referrer-Policy"] == "no-referrer"
    async with client.get(server.origin + "/download/missing") as response:
        assert response.status == 404 and response.headers["X-Frame-Options"] == "DENY"


async def main():
    evidence = Path(os.environ["TOAD_BROWSER_EVIDENCE"])
    import toad.web_server

    assert "site-packages" in toad.web_server.__file__
    # Real constructors reject external binds before opening sockets.
    for host in ("0.0.0.0", "localhost.attacker.invalid", "::1"):
        try:
            toad.web_server.ToadWebServer("false", host=host)
        except ValueError:
            pass
        else:
            raise AssertionError("External/non-declared bind accepted")
    try:
        toad.web_server.ToadWebServer("false", public_url="https://attacker.invalid")
    except ValueError:
        pass
    else:
        raise AssertionError("External public URL accepted")
    with tempfile.TemporaryDirectory(prefix="wb-", dir="/home/ts/wt") as directory:
        async with AsyncExitStack() as stack:
            # Two concurrent local ports must work in one browser cookie jar.
            serve = await stack.enter_async_context(LocalServer(Path(directory) / "serve", "serve"))
            run = await stack.enter_async_context(LocalServer(Path(directory) / "run", "run"))
            acp = await stack.enter_async_context(LocalServer(Path(directory) / "acp", "acp"))
            client = await stack.enter_async_context(ClientSession(cookie_jar=CookieJar(unsafe=True)))
            await gate(client, serve)
            await gate(client, run)
            await gate(client, acp)
            for server in (serve, run, acp):
                async with client.get(server.origin + "/") as response:
                    assert response.status == 200
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
                )
                context = await browser.new_context(viewport={"width": 1100, "height": 740})

                # Restrict this browser pilot to loopback; vendor font CSS is
                # external, so the ordinary installed fallback font is used.
                async def local_request(route):
                    if route.request.url.startswith(("http://127.0.0.1:", "http://localhost:")):
                        await route.continue_()
                    else:
                        await route.abort()

                await context.route("**/*", local_request)
                pages = []
                proof = []
                try:
                    for server in (serve, run, acp):
                        page = await context.new_page()
                        sent, received = [], []
                        terminal = pyte.Screen(140, 50)
                        stream = pyte.ByteStream(terminal)

                        def observe(ws, sent=sent, received=received, stream=stream):
                            ws.on("framesent", lambda frame: sent.append(frame))
                            def receive(frame):
                                received.append(frame)
                                if isinstance(frame, bytes):
                                    stream.feed(frame)
                            ws.on("framereceived", receive)

                        page.on("websocket", observe)
                        response = await page.goto(server.url)
                        assert response.status == 200 and page.url == server.origin + "/"
                        await page.wait_for_selector("body.-first-byte .xterm-screen", timeout=25000)
                        assert server.children(), "Authorized browser failed to start actual Toad child"
                        async with asyncio.timeout(35):
                            while not any('Toad' in row or 'Install' in row or 'Ready' in row for row in terminal.display):
                                await asyncio.sleep(.05)
                        await asyncio.sleep(1)
                        await page.screenshot(path=str(evidence / f"{server.entry}-actual-browser.png"))
                        before = len(received)
                        await page.locator(".xterm-helper-textarea").focus()
                        await page.keyboard.press("F2")
                        async with asyncio.timeout(10):
                            while not any(
                                "stdin" in frame and "\\u001bOQ" in frame for frame in sent if isinstance(frame, str)
                            ):
                                # Chromium/xterm may choose the alternate F2 CSI.
                                if any("stdin" in frame for frame in sent if isinstance(frame, str)):
                                    break
                                await asyncio.sleep(0.05)
                            while len(received) <= before:
                                await asyncio.sleep(0.05)
                        await asyncio.sleep(0.3)
                        assert any('Search settings' in row for row in terminal.display), terminal.display[:8]
                        await page.screenshot(path=str(evidence / f"{server.entry}-settings-input.png"))
                        proof.append(
                            {
                                "entry": server.entry,
                                "installed_child": True,
                                "browser_paint": True,
                                "browser_keyboard_response": True,
                                "frames": len(received),
                            }
                        )
                        pages.append(page)
                    # Reload first after second authentication, proving the
                    # second port did not overwrite the first browser cookie.
                    await pages[0].reload()
                    await pages[0].wait_for_selector("body.-first-byte .xterm-screen", timeout=25000)
                    proof[0]["reload_after_second_port"] = True
                finally:
                    await context.close()
                    await browser.close()
            print(
                json.dumps(
                    {
                        "boundary": "installed CLI + real aiohttp/vendor server + Chromium/Toad child; no mocks",
                        "gate": "Host/Origin/cookie/redirect/static/download-negative and zero unauthorized children passed",
                        "ports_independent": True,
                        "proof": proof,
                        "toad_import": toad.web_server.__file__,
                    }
                )
            )


if __name__ == "__main__":
    asyncio.run(main())
