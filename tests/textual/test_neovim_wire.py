"""The retained native win_viewport handle must survive the actual RPC decoder."""

import msgpack
import pytest

from toad.neovim_editing import (
    BufferHandle,
    NeovimCall,
    NeovimEditing,
    NeovimWireFailure,
    TabpageHandle,
    WindowHandle,
)


async def test_native_redraw_and_response_keep_nominal_window() -> None:
    owner = NeovimEditing()
    owner.accept_api_info([1, {"types": {
        "Buffer": {"id": 0, "prefix": "nvim_buf_"},
        "Window": {"id": 1, "prefix": "nvim_win_"},
        "Tabpage": {"id": 2, "prefix": "nvim_tabpage_"},
    }}])
    # Root's real nvim 0.12.4 first redraw carried this extension in win_viewport.
    native_window = msgpack.ExtType(1, b"\xcd\x03\xe8")
    owner._unpacker.feed(msgpack.packb([
        2, "redraw", [["win_viewport", [1, native_window, 0, 1, 0, 0, 1, 0]]],
    ], use_bin_type=True))
    redraw, = owner._unpacker
    window = redraw[2][0][1][1]
    assert window == WindowHandle(1000)
    assert window != BufferHandle(1000)
    assert window != TabpageHandle(1000)
    await owner._receive(redraw)

    request = NeovimCall("nvim_get_current_win", [])
    owner._register(request)
    owner._unpacker.feed(msgpack.packb([1, request.identity, None, native_window]))
    response, = owner._unpacker
    await owner._receive(response)
    assert request.reply.result() == window
    assert owner._encode_handle(window) == native_window

    with pytest.raises(NeovimWireFailure, match="arity"):
        await owner._receive([2, "redraw"])
    owner._unpacker.feed(msgpack.packb([
        2, "redraw", [msgpack.ExtType(127, msgpack.packb(1000))],
    ]))
    with pytest.raises(NeovimWireFailure, match="Unknown Neovim extension code"):
        tuple(owner._unpacker)
