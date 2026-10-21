"""A write selected on the legacy root is refused once the default route is published."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
import agent_comms.private_nk_entrypoint as private_nk_entrypoint
from agent_comms.active_route import publish_active_route
from agent_comms.route_selection import current_root, run_selected_write

from support.routes import private_root, select_root_by_default_route, selecting_route


@pytest.fixture
def published(tmp_path, monkeypatch, native_package):
    """A legacy root, and a private root published as the default route."""
    tmp_path.chmod(0o700)
    for name in ("CONFIG", "DATA", "STATE"):
        monkeypatch.setenv(f"XDG_{name}_HOME", str(tmp_path / name.lower()))
    home = select_root_by_default_route(monkeypatch, tmp_path)
    legacy = home / ".agent-comms"
    legacy.mkdir(mode=0o700)
    private = private_root(tmp_path / "wire", tmp_path, "PRIVATE-ONLY")
    route = selecting_route(private)
    assert current_root() == legacy
    with patch.object(private_nk_entrypoint, "_trusted_package", lambda _: None):
        publish_active_route(route)
    assert current_root() == private
    return SimpleNamespace(legacy=legacy, private=private, route=route, cwd=tmp_path)


def test_a_write_selected_before_the_flip_is_refused_after_it(published):
    invoked = []
    with pytest.raises(ValueError):
        run_selected_write(published.legacy, invoked.append, None, implicit=True)
    assert not invoked
