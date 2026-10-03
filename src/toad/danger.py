from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import bashlex
from bashlex import ast

SAFE_COMMANDS = {
    # Display & Output
    "echo",
    "cat",
    "less",
    "more",
    "head",
    "tail",
    "tac",
    "nl",
    # File & Directory Information
    "ls",
    "tree",
    "pwd",
    "file",
    "stat",
    "du",
    "df",
    # Search & Find
    "find",
    "locate",
    "which",
    "whereis",
    "type",
    "grep",
    "egrep",
    "fgrep",
    # Text Processing (read-only)
    "wc",
    "sort",
    "uniq",
    "cut",
    "paste",
    "column",
    "tr",
    "diff",
    "cmp",
    "comm",
    # System Information
    "whoami",
    "who",
    "w",
    "id",
    "hostname",
    "uname",
    "uptime",
    "date",
    "cal",
    "env",
    "printenv",
    # Process Information
    "ps",
    "top",
    "htop",
    "pgrep",
    "jobs",
    "pstree",
    # Network (read-only operations)
    "ping",
    "traceroute",
    "nslookup",
    "dig",
    "host",
    "netstat",
    "ss",
    "ifconfig",
    "ip",
    # View compressed files (without extracting)
    "zcat",
    "zless",
    # History & Help
    "history",
    "man",
    "help",
    "info",
    "apropos",
    "whatis",
    # Comparison & Checksums
    "md5sum",
    "sha256sum",
    "sha1sum",
    "cksum",
    "sum",
    # Other Safe Commands
    "bc",
    "expr",
    "test",
    "sleep",
    "true",
    "false",
    "yes",
    "seq",
    "basename",
    "dirname",
    "realpath",
    "readlink",
}

UNSAFE_COMMANDS = {
    # File/Directory Creation
    "mkdir",
    "touch",
    "mktemp",
    "mkfifo",
    "mknod",
    # File/Directory Deletion
    "rm",
    "rmdir",
    "shred",
    # File/Directory Moving/Copying
    "mv",
    "cp",
    "rsync",
    "scp",
    "install",
    # File Modification/Editing
    "sed",  # with -i flag
    "awk",  # can write files
    "tee",  # writes to files and stdout
    # Permissions/Ownership
    "chmod",
    "chown",
    "chgrp",
    "chattr",
    "setfacl",
    # Linking
    "ln",
    "link",
    "unlink",
    # Archive/Compression (extract/compress operations)
    "tar",
    "untar",
    "zip",
    "unzip",
    "gzip",
    "gunzip",
    "bzip2",
    "bunzip2",
    "xz",
    "unxz",
    "7z",
    "rar",
    "unrar",
    # Download Tools
    "wget",
    "curl",
    "fetch",
    "aria2c",
    # Low-level Disk Operations
    "dd",
    "truncate",
    "fallocate",
    # File Splitting
    "split",
    "csplit",
    # Synchronization
    "sync",
    # System Administration
    "useradd",
    "userdel",
    "usermod",
    "groupadd",
    "groupdel",
    "passwd",
    "mount",
    "umount",
    "mkfs",
    "fdisk",
    "parted",
    "swapon",
    "swapoff",
    # Other Potentially Dangerous
    "patch",
}


@dataclass(frozen=True)
class DangerStyles:
    dangerous: str
    destructive: str


class DangerLevel(ABC):
    """A command's effect owns highlighting and path escalation."""

    @abstractmethod
    def highlight(self, styles: DangerStyles) -> str: ...

    def at_path(self, project: Path, target: Path) -> DangerLevel:
        return self


class Unhighlighted(DangerLevel):
    def highlight(self, styles: DangerStyles) -> str:
        return ""


class Safe(Unhighlighted):
    """Known read-only commands."""


class Unknown(Unhighlighted):
    """Unclassified commands do not claim destructive behavior."""


class Dangerous(DangerLevel):
    def highlight(self, styles: DangerStyles) -> str:
        return styles.dangerous

    def at_path(self, project: Path, target: Path) -> DangerLevel:
        return self if target.is_relative_to(project) else Destructive()


class Destructive(DangerLevel):
    def highlight(self, styles: DangerStyles) -> str:
        return styles.destructive


@dataclass(frozen=True)
class CommandAtom:
    level: DangerLevel
    span: tuple[int, int]


class CommandVisitor(ast.nodevisitor):
    """Use bashlex's visitor boundary to follow words, redirects and commands."""

    def __init__(self, project: Path, cwd: Path):
        self.project = project
        self.cwd = cwd
        self.atoms: list[CommandAtom] = []
        self.command: str | None = None
        self.level: DangerLevel = Unknown()

    def visitcommand(self, node, parts):
        outer_command, outer_level = self.command, self.level
        self.command, self.level = None, Unknown()
        for part in parts:
            self.visit(part)
        self.atoms.append(CommandAtom(self.level, node.pos))
        self.command, self.level = outer_command, outer_level
        return False

    def visitword(self, node, word):
        if self.command is None:
            self.command = word
            if word in SAFE_COMMANDS:
                self.level = Safe()
            elif word in UNSAFE_COMMANDS:
                self.level = Dangerous()
        elif not word.startswith(("-", "+")):
            target = (self.cwd / Path(word).expanduser()).resolve()
            if self.command == "cd":
                self.cwd = target
            else:
                self.level = self.level.at_path(self.project, target)
        # bashlex visits substitutions within this word as commands as well.

    def visitredirect(self, node, input, type, output, heredoc):
        # File descriptor duplication and heredocs have no file target. The
        # operator spelling belongs to the external shell grammar.
        if type in (">", ">>", ">|", "&>", "&>>") and isinstance(output, ast.node):
            target = (self.cwd / Path(output.word).expanduser()).resolve()
            level = Dangerous().at_path(self.project, target)
            self.atoms.append(CommandAtom(level, node.pos))
        return False

    def visitcommandsubstitution(self, node, command):
        # A subshell's cd must not change the enclosing command's directory.
        cwd = self.cwd
        self.visit(command)
        self.cwd = cwd
        return False

    visitprocesssubstitution = visitcommandsubstitution


@lru_cache(maxsize=1024)
def analyze(
    project_directory: str, current_working_directory: str, command_line: str
) -> tuple[CommandAtom, ...]:
    """Retain bounded analysis data; frontends own its native presentation."""
    try:
        visitor = CommandVisitor(
            Path(project_directory).resolve(), Path(current_working_directory).resolve()
        )
        try:
            nodes = bashlex.parse(command_line)
        except bashlex.errors.ParsingError, NotImplementedError:
            return ()
        for node in nodes:
            visitor.visit(node)
    except OSError:
        return ()
    return tuple(visitor.atoms)
