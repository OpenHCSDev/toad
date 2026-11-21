"""The Android renderer's service transport, exercised with a real separate process."""

import asyncio
import multiprocessing
import os
from dataclasses import dataclass

from toad.render_backend import RenderTask
from toad.render_socket_service import SocketServiceRenderer, serve_render_socket


@dataclass(frozen=True)
class ProcessIdRenderTask(RenderTask[int]):
    def execute(self) -> int:
        return os.getpid()


async def test_socket_renderer_executes_in_its_owned_process(tmp_path) -> None:
    socket_path = tmp_path / "render.sock"
    process = multiprocessing.get_context("spawn").Process(
        target=serve_render_socket, args=(socket_path,),
    )
    process.start()
    renderer = SocketServiceRenderer(socket_path)
    try:
        assert await asyncio.wait_for(renderer.submit(ProcessIdRenderTask()), 10) == process.pid
    finally:
        await renderer.aclose()
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(10)
    assert process.exitcode == 0
