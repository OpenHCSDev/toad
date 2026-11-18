"""Run the Qt app from the shipped bundle alone, against a scratch bus, through every view kind.

    python tools/android/shipped_run.py RUNTIME APP SITE_PACKAGES

bundle_check reads the shipped app's imports without running it, so it cannot see an import
the app makes at run time by name (2026-11-18: the keymap's package walk imported toad.cli
and the phone's DM view died on `No module named 'click'`). This runs it. Exit 0 when the
`shipped` qt_drive scenario passes; non-zero, with the failure, otherwise.

- The app runs on an interpreter with no site-packages, at the APK's optimization level: APP (assembled by assemble.py) and the
  recipe-built packages from SITE_PACKAGES only, entered as the APK enters (android_app.enter),
  from a copy of APP in a scratch folder, since the app keeps its state beside its folder.
- The bus is a scratch one: a fresh root seeded with a CLI thread, a peer, a direct message
  and a `#comms` channel message, served by RUNTIME's connector on a loopback port with a
  throwaway TLS front (the client speaks only HTTPS) and a scratch UI grant. HOME points at
  the scratch folder for the connector, so no live grant or bus is read or written.
- The scenario opens the welcome, every menu action that changes nothing (settings and each
  of its pages, the keymap, the transfer dialogs, channels, direct messages, the bus switcher,
  team), the channel, the CLI thread with its session details, and presses every bound action
  key on each; any exception, an error file or a ModuleNotFoundError anywhere fails the run.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

from recipe_built import import_names, python_optimize

HERE = Path(__file__).resolve().parent
CHECKOUT = HERE.parent.parent
THREAD, PEER, CHANNEL = "scratch-live-pipeline", "scratch-peer", "comms"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def run(*command: str | Path, **options) -> subprocess.CompletedProcess:
    done = subprocess.run([str(word) for word in command], capture_output=True, text=True,
                          timeout=180, check=False, **options)
    if done.returncode:
        raise RuntimeError(f"{' '.join(str(word) for word in command)} failed:\n{done.stdout}{done.stderr}")
    return done


def link_or_copy(source: str, target: str) -> None:
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


class ScratchBus:
    """A seeded bus root served over loopback TLS, and a UI profile granted to it."""

    def __init__(self, runtime: Path, work: Path) -> None:
        self.runtime, self.work = runtime, work
        self.root, self.home = work / "root", work / "home"
        self.processes: list[subprocess.Popen] = []

    def seed(self) -> None:
        # A private root, as an installed bus is: a UI grant is scoped to its namespace.
        run(self.runtime / "bin" / "python", "-c",
            "import sys; from pathlib import Path; from agent_comms.registry.registry_store import RegistryStore; "
            "RegistryStore.at(Path(sys.argv[1])).prepare_native_root()", self.root,
            env=os.environ | {"HOME": str(self.home)})
        cli = self.runtime / "bin" / "agent-comms"
        for name in (THREAD, PEER):
            run(cli, "--root", self.root, "register", "--name", name, "--worktree", self.work,
                "--tags", CHANNEL, "--execution", "external", cwd=self.work)
        for target, body in ((THREAD, "a direct message"), (f"#{CHANNEL}", "a channel message")):
            sent = run(cli, "--root", self.root, "send", "--from", PEER, "--to", target,
                       "--type", "info", "--body", body, cwd=self.work)
            if '"id"' not in sent.stdout:
                raise RuntimeError(f"seeding {target} failed: {sent.stdout}{sent.stderr}")

    def serve(self) -> Path:
        cert, key = self.work / "cert.pem", self.work / "key.pem"
        run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert,
            "-days", "1", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1")
        port, front = free_port(), free_port()
        notify = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        notify.bind(str(self.work / "notify.sock"))
        notify.settimeout(60)
        env = os.environ | {"HOME": str(self.home), "NOTIFY_SOCKET": str(self.work / "notify.sock")}
        self.processes.append(subprocess.Popen(
            [str(self.runtime / "bin" / "agent-comms-connector"), "serve", "--root", str(self.root),
             "--port", str(port), "--issuer", f"https://localhost:{front}"],
            env=env, stdout=open(self.work / "connector.log", "w"), stderr=subprocess.STDOUT))
        if b"READY=1" not in notify.recv(4096):
            raise RuntimeError("the scratch connector did not report ready")
        notify.close()
        tls = subprocess.Popen([sys.executable, str(HERE / "tls_front.py"), str(cert), str(key), str(front), str(port)],
                               stdout=subprocess.PIPE, text=True)
        self.processes.append(tls)
        if tls.stdout.readline().strip() != "ready":
            raise RuntimeError("the TLS front did not start")
        profile = self.work / "profile.json"
        run(self.runtime / "bin" / "agent-comms-connector", "grant-ui", "--root", self.root,
            "--endpoint", f"https://localhost:{front}/mcp", "--profile", profile, "--access", "ui_access",
            env={**env, "HOME": str(self.home)})
        return profile

    def stop(self) -> None:
        for process in self.processes:
            process.terminate()
        for process in self.processes:
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()


def shipped_qt(app: Path, recipes: Path, trust: Path, profile: Path, out: Path) -> subprocess.CompletedProcess:
    """qt_drive's `shipped` scenario on the shipped interpreter: no site-packages, the APK's
    entry, the scratch bus's certificate trusted beside the bundle's own CA file."""
    code = (
        "import os, runpy, sys\n"
        f"sys.path[:0] = [{str(app)!r}, {str(recipes)!r}]\n"
        "from toad.qt.android_app import enter\n"
        "enter()\n"
        f"os.environ['SSL_CERT_FILE'] = {str(trust)!r}\n"
        "os.environ['QT_QPA_PLATFORM'] = 'offscreen'\n"
        f"sys.argv = ['qt_drive.py', 'shipped', {str(profile)!r}, {str(out)!r}]\n"
        f"runpy.run_path({str(CHECKOUT / 'tools' / 'qt_drive.py')!r}, run_name='__main__')\n"
    )
    # -B: the app folder ships the bytecode assemble.py compiled; this run writes none beside it.
    # It runs at the APK's optimization level, so it loads that bytecode, as the phone does.
    return subprocess.run([sys.executable, "-S", "-B", "-c", code], capture_output=True, text=True,
                          timeout=600, cwd=recipes, check=False,
                          env=os.environ | {"PYTHONOPTIMIZE": str(python_optimize())})


def main(runtime: Path, app: Path, site_packages: Path) -> int:
    work = Path(tempfile.mkdtemp(prefix="toad-shipped-"))
    bus = ScratchBus(runtime, work)
    try:
        bus.seed()
        profile = bus.serve()
        shipped = work / "kept" / "app"
        shutil.copytree(app, shipped, copy_function=link_or_copy,
                        ignore=shutil.ignore_patterns(".buildozer", "bin", "*.apk", "build.log"))
        recipes = work / "recipes"
        recipes.mkdir()
        for name in import_names():
            for candidate in site_packages.glob(f"{name}*"):
                if not (recipes / candidate.name).exists():
                    (recipes / candidate.name).symlink_to(candidate)
        trust = work / "trust.pem"
        trust.write_text((app / "cacert.pem").read_text() + (work / "cert.pem").read_text())
        out = work / "out"
        result = shipped_qt(shipped, recipes, trust, profile, out)
        print(result.stdout[-6000:])
        errors = sorted((work / "kept" / "state").rglob("errors/*.txt"))
        failed = (result.returncode != 0 or "ModuleNotFoundError" in result.stdout + result.stderr or errors)
        if failed:
            print(result.stderr[-8000:], file=sys.stderr)
            for error in errors:
                print(f"== {error.name}\n{error.read_text()[-3000:]}", file=sys.stderr)
            print(f"error: the shipped app failed on a scratch bus (exit {result.returncode}, "
                  f"{len(errors)} error file(s)); TOAD_SHIPPED_KEEP=1 keeps its scratch folder", file=sys.stderr)
            return 1
        print("shipped app ran every view kind and bound key on a scratch bus")
        return 0
    finally:
        bus.stop()
        if not os.environ.get("TOAD_SHIPPED_KEEP"):
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2]).resolve(), Path(sys.argv[3])))
