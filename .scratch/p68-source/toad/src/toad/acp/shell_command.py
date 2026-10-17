"""Shell syntax is decoded at the command boundary, not at retirement."""
from abc import abstractmethod
import os
from agent_comms.declared_family import DeclaredFamily


class ShellCommand(DeclaredFamily, affix="ShellCommand"):
    @classmethod
    def current(cls):
        return cls.decode(os.name)()

    @abstractmethod
    def argv(self, command: str) -> tuple[str, ...]: ...


class PosixShellCommand(ShellCommand):
    def argv(self, command):
        return ("/bin/sh", "-c", command)


class NtShellCommand(ShellCommand):
    def argv(self, command):
        return (os.environ.get("COMSPEC", "cmd.exe"), "/c", command)
