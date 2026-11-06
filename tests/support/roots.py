"""The private directories one test works in."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, ClassVar

from toad.paths import APP_NAME

if TYPE_CHECKING:
    from agent_comms.comms import Comms

ATTEMPT = "TOAD_TEST_ATTEMPT"


def installed_wire(root: Path) -> Comms:
    """Prepare the same bus and native schemas that an installed owner uses."""
    from agent_comms.bus import Bus
    from agent_comms.comms import Comms

    from agent_comms.active_route import resolve_comms_route

    comms = Comms(resolve_comms_route(root))
    comms.registry.store.prepare_native_root()
    Bus.install(Bus.path_in(root))
    return comms


@dataclass(frozen=True)
class Roots:
    """One disposable directory holding the wire, the settings and the project of a test."""

    attempt: Path

    # Every test's Toad starts from these settings: no test reports usage to the real
    # analytics service or fetches the latest release (both default on), so no app test
    # touches the network. It starts installed, as Tristan's Toad does: with no anon_id,
    # every start mints one and saves the whole settings file again (ensure_installation),
    # about 0.3 s that no test is about. Its theme is one every test host has: the default,
    # wal, exists only once pywal has written its palette, so without it every app opened
    # with a theme warning toast over the bottom-right controls.
    SETTINGS: ClassVar[dict[str, object]] = {"anon_id": "00000000-0000-0000-0000-000000000002",
                                             "statistics": {"allow_collect": False},
                                             "updates": {"check": False},
                                             "ui": {"theme": "textual-dark"}}

    @classmethod
    def create(cls) -> Roots:
        # tempfile owns the configured scratch location, including TMPDIR.
        roots = cls(Path(tempfile.mkdtemp(prefix="toad-test-")))
        roots.save_settings({})
        return roots

    @property
    def config(self) -> Path:
        """This test's XDG_CONFIG_HOME."""
        return self.attempt / "config"

    @property
    def settings(self) -> Path:
        """Toad's settings file under this test's config."""
        return self.config / APP_NAME / "toad.json"

    def save_settings(self, settings: dict[str, object]) -> Path:
        """Toad's saved settings for this test: SETTINGS with ``settings`` over them."""
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        self.settings.write_text(json.dumps(self.SETTINGS | settings))
        return self.settings

    @classmethod
    def of_this_process(cls) -> Roots:
        """The roots the test runner gave this process."""
        return cls(Path(os.environ[ATTEMPT]))

    @property
    def wire(self) -> Path:
        return self.attempt / "wire"

    @property
    def project(self) -> Path:
        return self.attempt / "project"

    def environment(self, inherited: dict[str, str]) -> dict[str, str]:
        """The environment of a process that may only touch these roots."""
        env = {key: value for key, value in inherited.items()
               if not key.startswith("AGENT_COMMS_") and key != "NO_COLOR"}
        env.update({
            ATTEMPT: str(self.attempt),
            "AGENT_COMMS_ROOT": str(self.wire),
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_DATA_HOME": str(self.attempt / "data"),
            "XDG_STATE_HOME": str(self.attempt / "state"),
            "XDG_CACHE_HOME": str(self.attempt / "cache"),
            "PI_CODING_AGENT_DIR": str(self.attempt / "pi"),
            "TMPDIR": str(self.attempt),
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "FORCE_COLOR": "1",
        })
        return env
