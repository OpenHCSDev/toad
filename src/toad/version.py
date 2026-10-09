from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, NamedTuple, TYPE_CHECKING
from abc import ABC, abstractmethod
from dataclasses import dataclass

if TYPE_CHECKING:
    from packaging.version import Version


VERSION_TOML_URL = "https://www.batrachian.ai/toad.toml"


class VersionMeta(NamedTuple):
    """Information about the current version of Toad."""

    version: str
    upgrade_message: str
    visit_url: str


class VersionCheckFailed(Exception):
    """Something went wrong in the version check."""


class VersionStatus(ABC):
    @abstractmethod
    def print_notice(self) -> None: ...


class CurrentVersion(VersionStatus):
    def print_notice(self) -> None:
        pass


@dataclass(frozen=True)
class AvailableVersion(VersionStatus):
    metadata: VersionMeta

    def print_notice(self) -> None:
        from rich.console import Console
        from rich.panel import Panel
        console = Console()
        console.print(Panel(self.metadata.upgrade_message, style="magenta", border_style="dim green",
                            title="🐸 [bold green not dim]Update available![/] 🐸", expand=False, padding=(1, 2)))
        console.print(f"Please visit {self.metadata.visit_url}")


class VersionMonitor:
    def __init__(self) -> None:
        self.status: VersionStatus = CurrentVersion()

    async def check(
        self, run_thread: Callable[..., Awaitable[Any]] = asyncio.to_thread,
    ) -> None:
        try:
            self.status = await self.check_version(run_thread)
        except VersionCheckFailed:
            return

    @staticmethod
    def prepare_version() -> Version:
        """Acquire cold dependencies and installed metadata outside UI work."""
        import httpx  # noqa: F401 - acquired before the UI consumes the module
        import packaging.version
        import tomllib  # noqa: F401 - acquired before the UI decodes the response

        from toad import get_version

        try:
            return packaging.version.parse(get_version())
        except packaging.version.InvalidVersion as error:
            raise VersionCheckFailed(f"Invalid version;{error}")

    @classmethod
    async def check_version(
        cls, run_thread: Callable[..., Awaitable[Any]] = asyncio.to_thread,
    ) -> VersionStatus:
        """Check for a new version of Toad.

        The outcome owns whether an upgrade notice exists.
        """
        current_version = await run_thread(cls.prepare_version)
        # These modules were acquired by the preparation worker above.
        import httpx
        import packaging.version
        import tomllib

        try:
            client = await run_thread(httpx.AsyncClient)
            async with client:
                response = await client.get(VERSION_TOML_URL)
                version_toml_bytes = await response.aread()
        except httpx.HTTPError as error:
            # The network check is optional; an unreachable server means no notice.
            raise VersionCheckFailed(f"Failed to retrieve version;{error}")

        try:
            version_toml = version_toml_bytes.decode("utf-8", "replace")
            version_meta = tomllib.loads(version_toml)
        except tomllib.TOMLDecodeError as error:
            raise VersionCheckFailed(f"Failed to decode version TOML;{error}")

        if not isinstance(version_meta, dict):
            raise VersionCheckFailed("Response isn't TOML")

        toad_version = str(version_meta.get("version", "0"))
        version_message = str(version_meta.get("upgrade_message", ""))
        version_message = version_message.replace("$VERSION", toad_version)
        verison_meta = VersionMeta(
            version=toad_version,
            upgrade_message=version_message,
            visit_url=str(version_meta.get("visit_url", "")),
        )

        try:
            new_version = packaging.version.parse(verison_meta.version)
        except packaging.version.InvalidVersion as error:
            raise VersionCheckFailed(f"Invalid remote version;{error}")

        return AvailableVersion(verison_meta) if new_version > current_version else CurrentVersion()


if __name__ == "__main__":

    async def run() -> None:
        result = await VersionMonitor.check_version()
        from rich import print

        print(result)

    import asyncio

    asyncio.run(run())
