"""The operating system Toad runs on, and the desktop notifier it offers."""

from __future__ import annotations

import platform
from typing import ClassVar, Literal, Mapping

type OS = Literal["linux", "macos", "windows", "*"]


class DesktopService:
    """The platform's notification service, as notifypy detects it."""

    def notification(self):
        from notifypy import Notify

        return Notify()

    def send(self, app, notification) -> DesktopService:
        notification.send()
        return self


class DBusDesktop(DesktopService):
    """notifypy's notify-send path inherits Toad's terminal as stderr; its D-Bus
    notifier starts no child process that could write over the TUI."""

    def notification(self):
        from notifypy import Notify
        from notifypy.os_notifiers.linux import LinuxNotifier

        return Notify(use_custom_notifier=LinuxNotifier)


class UncheckedDBusDesktop(DBusDesktop):
    """Asks the session bus once whether anything serves notifications, because
    notifypy's D-Bus notifier reports an error reply as a delivery."""

    name: ClassVar[str] = "org.freedesktop.Notifications"

    def send(self, app, notification) -> DesktopService:
        return self.served(app).send(app, notification)

    def served(self, app) -> DesktopService:
        from jeepney import DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection

        bus = DBusAddress("/org/freedesktop/DBus", bus_name="org.freedesktop.DBus",
                          interface="org.freedesktop.DBus")
        try:
            with open_dbus_connection(bus="SESSION") as connection:
                owned = connection.send_and_get_reply(
                    new_method_call(bus, "NameHasOwner", "s", (self.name,)), timeout=2).body[0]
                activatable = self.name in connection.send_and_get_reply(
                    new_method_call(bus, "ListActivatableNames"), timeout=2).body[0]
        except OSError:
            owned = activatable = False
        if owned or activatable:
            return DBusDesktop()
        app.call_from_thread(
            app.notify,
            "Desktop notifications are off for this session: no notification daemon is running.",
            severity="warning",
        )
        return AbsentDesktop()


class AbsentDesktop(DesktopService):
    """Nothing serves notifications; asking again per message only fails again."""

    def send(self, app, notification) -> DesktopService:
        return self


class Platform:
    """The operating system Toad runs on; each member owns what differs there."""

    system: ClassVar[str]
    key: ClassVar[OS]
    application_name: ClassVar[str] = "Toad"
    members: ClassVar[dict[str, type[Platform]]] = {}

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        Platform.members[cls.system] = cls

    @classmethod
    def select[V](cls, matrix: Mapping[OS, V]) -> V | None:
        """The catalog's exact platform entry, or its declared wildcard."""
        return matrix.get(cls.key, matrix.get("*"))

    @classmethod
    def desktop(cls) -> DesktopService:
        return DesktopService()

    @classmethod
    def decode(cls, system: str) -> type[Platform]:
        """`platform.system()` names the member; anything undeclared is unknown."""
        return cls.members.get(system, UnknownPlatform)


class LinuxPlatform(Platform):
    system = "Linux"
    key = "linux"

    @classmethod
    def desktop(cls) -> DesktopService:
        return UncheckedDBusDesktop()


class MacPlatform(Platform):
    system = "Darwin"
    key = "macos"
    application_name = "🐸 Toad"


class WindowsPlatform(Platform):
    system = "Windows"
    key = "windows"


class UnknownPlatform(Platform):
    """A system Toad has no declaration for: the base defaults and the catalog wildcard."""

    system = ""
    key = "*"


host: type[Platform] = Platform.decode(platform.system())
