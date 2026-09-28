"""Environment owned by Toad's terminal launch boundary."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import ClassVar


class TerminalEnvironment:
    variables: ClassVar[Mapping[str, str]] = MappingProxyType(
        {
            "FORCE_COLOR": "1",
            "TTY_COMPATIBLE": "1",
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "TOAD": "1",
            "CLICOLOR": "1",
        }
    )
    default_shell: ClassVar[str] = "sh"

    @classmethod
    def for_child(cls, base: Mapping[str, str]) -> dict[str, str]:
        return {**base, **cls.variables}

    @classmethod
    def login_shell(cls, base: Mapping[str, str]) -> str:
        return base.get("SHELL") or cls.default_shell
