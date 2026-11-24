"""Android bus startup must not crash when held or bundled UI profiles have expired."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from agent_comms.nominal.field_codec import FieldCodec, RootId
from agent_comms.transport.connector_profile import (
    BearerSecret,
    HttpsMcpEndpoint,
    UiConnectionProfile,
    UiCredential,
    UiGrantId,
)
from agent_comms.transport.held_ui_profiles import HeldUiProfiles
from yarl import URL

from toad.client.bus_connect import _hold_pasted_profile
from toad.qt import android_bus


def _write_profile(path: Path, *, grant_id: str, expires_at: float) -> UiConnectionProfile:
    profile = UiConnectionProfile(
        endpoint=HttpsMcpEndpoint(URL("https://ts-gaming.tail553874.ts.net/mcp")),
        credential=UiCredential(
            grant_id=UiGrantId(grant_id),
            namespace=RootId("45344e2e85274b2f8526d1a5cb5b5d34"),
            expires_at=expires_at,
            token=BearerSecret("test-secret-token"),
        ),
    )
    profile.write_new(path)
    return profile


def test_held_connection_with_expired_held_and_bundled_profile_does_not_crash(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    expired_at = time.time() - 3600.0
    grant_id = "2ac98a3ef41b48fa95e343a0ef64234a"

    bundled = tmp_path / "app" / "profile.json"
    _write_profile(bundled, grant_id=grant_id, expires_at=expired_at)
    # The same grant is already held on disk and has expired (the exact crash seen on Pixel 8a).
    held_path = HeldUiProfiles.directory() / f"ts-gaming.tail553874.ts.net-{grant_id}.json"
    assert held_path.is_relative_to(tmp_path)
    _write_profile(held_path, grant_id=grant_id, expires_at=expired_at)

    monkeypatch.setattr(android_bus, "BUNDLED_PROFILE", bundled)

    connection = android_bus.held_connection()
    assert connection.endpoint.url == URL("https://ts-gaming.tail553874.ts.net/mcp")
    assert connection.credential.grant_id == UiGrantId(grant_id)


def test_held_connection_seeds_fresh_bundled_profile_when_existing_held_is_expired(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    now = time.time()
    old_grant = "2ac98a3ef41b48fa95e343a0ef64234a"
    new_grant = "103ed2f336fc4832b0ae79d7ff888493"

    held_old = HeldUiProfiles.directory() / f"ts-gaming.tail553874.ts.net-{old_grant}.json"
    assert held_old.is_relative_to(tmp_path)
    _write_profile(held_old, grant_id=old_grant, expires_at=now - 3600.0)

    bundled = tmp_path / "app" / "profile.json"
    _write_profile(bundled, grant_id=new_grant, expires_at=now + 3600.0)
    monkeypatch.setattr(android_bus, "BUNDLED_PROFILE", bundled)

    connection = android_bus.held_connection()
    assert connection.credential.grant_id == UiGrantId(new_grant)
    assert (HeldUiProfiles.directory() / f"ts-gaming.tail553874.ts.net-{new_grant}.json").is_file()


class _FakeBusConnectHost:
    def __init__(self) -> None:
        self.opened: list[Path] = []
        self.warnings: list[tuple[str, str]] = []

    def copy_to_clipboard(self, text: str) -> None:
        pass

    def paste_profile(self, submit) -> None:
        pass

    def open_held_profile(self, path: Path) -> None:
        self.opened.append(path)

    def show_warning(self, text: str, title: str = "") -> None:
        self.warnings.append((text, title))


def test_hold_pasted_profile_stores_and_opens_profile_without_connector_cli(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    grant_id = "103ed2f336fc4832b0ae79d7ff888493"
    profile = UiConnectionProfile(
        endpoint=HttpsMcpEndpoint(URL("https://ts-gaming.tail553874.ts.net/mcp")),
        credential=UiCredential(
            grant_id=UiGrantId(grant_id),
            namespace=RootId("45344e2e85274b2f8526d1a5cb5b5d34"),
            expires_at=time.time() + 3600.0,
            token=BearerSecret("test-secret-token"),
        ),
    )
    payload = FieldCodec.compact(FieldCodec.encode(profile), allow_nan=False)

    host = _FakeBusConnectHost()
    _hold_pasted_profile(payload, host, "ts-gaming")
    expected = HeldUiProfiles.directory() / f"ts-gaming.tail553874.ts.net-{grant_id}.json"
    assert expected.is_relative_to(tmp_path)
    assert expected.is_file()
    assert host.opened == [expected]
    assert host.warnings == []

    # Pasting the same grant again warns instead of raising FileExistsError.
    _hold_pasted_profile(payload, host, "ts-gaming")
    assert len(host.warnings) == 1
    assert host.warnings[0][1] == "Bus"


def test_android_client_startup_does_not_import_connector_server_cli() -> None:
    source_root = str(Path(android_bus.__file__).parents[2])
    probe = (
        "import sys, toad.qt.android; toad.qt.android.load_client(); "
        "from toad.client.connection import RemoteCoreConnection; "
        "object.__new__(RemoteCoreConnection).prewarm(); "
        "assert 'agent_comms.transport.connector' not in sys.modules, "
        "'Android startup pulled server-side agent_comms.transport.connector'; "
        "assert 'nominal_refactor_advisor' not in sys.modules, "
        "'Android startup pulled server-side nominal_refactor_advisor'"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True, text=True, timeout=60,
        env={"PYTHONPATH": source_root, "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
