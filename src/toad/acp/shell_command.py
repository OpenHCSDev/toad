"""Shell syntax is decoded at the command boundary, not at retirement."""
from abc import abstractmethod
import os
from agent_comms.declared_family import DeclaredFamily


class ShellCommand(DeclaredFamily, affix="ShellCommand"):
    @classmethod
    def current(cls):
        return cls.member_named(os.name)()

    @abstractmethod
    def argv(self, command: str, *, accepts_comms_root: bool = False) -> tuple[str, ...]: ...


class PosixShellCommand(ShellCommand):
    def argv(self, command, *, accepts_comms_root=False):
        if accepts_comms_root:
            # Core appends the typed launch arguments after this shell's $0.
            # Without $@ they become shell positionals, not ACP child arguments.
            return ("/bin/sh", "-c", f'{command} "$@"', "toad-acp")
        return ("/bin/sh", "-c", command)


class NtShellCommand(ShellCommand):
    def argv(self, command, *, accepts_comms_root=False):
        return (os.environ.get("COMSPEC", "cmd.exe"), "/c", command)
