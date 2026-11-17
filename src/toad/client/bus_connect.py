"""Toolkit-neutral decision for what the UI offers after a bus-connect attempt.

A peer that answers with a profile opens its bus directly; a peer that refuses carries a
reason that previously landed as a single-line warning banner with a shell command inside
it, offering the phone user nothing to do about it. This module turns that answer into a
structured decision — a short human summary and a tuple of tappable `RemediationOption`s
— so every frontend presents the same options over the same layer.

The classifier matches on the peer's refusal shape (the tailnet-only endpoint message
from `agent_comms.transport.served_endpoints.NothingTailnetOnly.refusal`) and picks
options a phone user can actually take: copy the laptop-side shell command to the
clipboard to run it there next, paste a profile the laptop operator handed over through
`agent_comms-connector grant-ui`, or dismiss. `CommsHost.offer_bus_connect(decision)`
takes over from the raw-string warning banner, and the Qt and Textual overrides render
the decision through their own menu/input surfaces.
"""
from __future__ import annotations

import re
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from agent_comms.transport.connector import HoldUiVerb
from agent_comms.transport.connector_store import ConnectorStore

from toad.client.bus_selection import openable_held
from agent_comms.transport.tailnet_profiles import AskedPeer, PeerAnsweredNothing, PeerRefusedProfile


@dataclass(frozen=True)
class RemediationOption:
    """One tappable option the frontend renders. ``label`` is the short name; ``description``
    explains what it does when the frontend has room for a second line; ``invoke`` runs on
    selection. The frontend never decides what options exist — it only renders them."""

    label: str
    description: str
    invoke: Callable[[], object]


@dataclass(frozen=True)
class BusConnectDecision:
    """Everything a frontend needs to present a failed bus-connect: who the ask was for,
    one-line summary for a status band, and the actions a reader can take."""

    peer_name: str
    summary: str
    options: tuple[RemediationOption, ...]


@runtime_checkable
class BusConnectHost(Protocol):
    """What the frontend-neutral decoder calls back for the actions it picks. A structural
    protocol — any object with these four methods satisfies it. ``CommsHost`` (and its
    native subclasses `QtToadApp` and Textual's `ToadApp`) already supply them, so the
    paste / copy / open-held operations reach back through the frontend's own native
    surfaces without the decoder knowing which frontend it is."""

    def copy_to_clipboard(self, text: str) -> None: ...

    def paste_profile(self, submit: Callable[[str], object]) -> None:
        """Open a paste surface for a profile JSON; call ``submit`` with the text the
        reader pastes, or do nothing on cancel."""
        ...

    def open_held_profile(self, path: Path) -> None:
        """Open the bus a newly-held profile names."""
        ...

    def show_warning(self, text: str, title: str = "") -> None: ...


_SETUP_COMMAND_RE = re.compile(r"tailscale serve --bg --https=\S+ https?://[^\s)]+")


def _hold_pasted_profile(text: str, host: BusConnectHost, peer_name: str) -> None:
    """Write pasted-in profile JSON to a temp file, register it through the same verb the
    APK bootstrap uses, and open the bus it names. Any error is reported through the
    host's warning channel rather than raised, so the paste flow stays recoverable."""
    stripped = text.strip()
    if not stripped:
        host.show_warning("Nothing to paste — the profile was empty.", "Bus")
        return
    temp_path = Path(tempfile.mkstemp(prefix=f"toad-paste-{peer_name}-", suffix=".json")[1])
    try:
        temp_path.write_text(stripped)
        temp_path.chmod(0o600)
        result = HoldUiVerb(profile=temp_path).apply(ConnectorStore.owned())
    except (OSError, ValueError) as error:
        host.show_warning(f"Could not hold that profile: {error}", "Bus")
        return
    finally:
        temp_path.unlink(missing_ok=True)
    if isinstance(result, str):
        host.show_warning(f"Pasted profile refused: {result}", "Bus")
        return
    # Find the just-held entry: the newest `OpenableProfile` whose grant matches
    # (hold_ui writes it with the grant id in the filename). Scan the held directory.
    held = openable_held(time.time())
    if not held:
        host.show_warning("Profile held, but no openable entry was recorded.", "Bus")
        return
    newest = max(held, key=lambda entry: entry.path.stat().st_mtime)
    host.open_held_profile(newest.path)


def _options_for_no_tailnet_endpoint(host: BusConnectHost, peer_name: str,
                                     refusal: str) -> tuple[RemediationOption, ...]:
    """The tailnet-only-endpoint refusal shape (served_endpoints.NothingTailnetOnly):
    offer to copy the setup command the laptop needs, and to paste a profile the
    laptop operator handed over separately."""
    options: list[RemediationOption] = []
    match = _SETUP_COMMAND_RE.search(refusal)
    if match:
        command = match.group(0)
        options.append(RemediationOption(
            label="Copy setup command",
            description=f"Copies `{command}` so you can run it on {peer_name}.",
            invoke=lambda: host.copy_to_clipboard(command),
        ))
    options.append(RemediationOption(
        label="Paste a profile",
        description=f"Paste the JSON {peer_name}'s owner handed over with grant-ui.",
        invoke=lambda: host.paste_profile(lambda text: _hold_pasted_profile(text, host, peer_name)),
    ))
    return tuple(options)


def _generic_options(host: BusConnectHost, peer_name: str) -> tuple[RemediationOption, ...]:
    """Fallback options when the refusal text does not match a known shape: paste is the
    only remediation that always works, regardless of what the peer answered."""
    return (RemediationOption(
        label="Paste a profile",
        description=f"Paste the JSON {peer_name}'s owner handed over with grant-ui.",
        invoke=lambda: host.paste_profile(lambda text: _hold_pasted_profile(text, host, peer_name)),
    ),)


def _summary_for(asked: AskedPeer) -> str:
    """One-line human summary for a status band: the peer and what happened in one phrase.
    Keeps the shell-command out of the headline — the options carry the actionable
    remediation."""
    peer = asked.found.peer.name
    refusal = getattr(asked, "refusal", "") or ""
    if "No tailnet-only endpoint" in refusal:
        return f"{peer} serves no tailnet-only endpoint — it needs tailscale serve, or paste a profile."
    match asked:
        case PeerRefusedProfile():
            return f"{peer} refused a profile."
        case PeerAnsweredNothing():
            return f"{peer} answered with no profile."
        case _:
            return f"{peer}: could not connect."


def decision_for(asked: AskedPeer, host: BusConnectHost) -> BusConnectDecision:
    """Classify a peer's non-opening answer into what the UI should present. Only called
    by `ClientApplication.asked_peer` after the `HoldingPeerProfile` case, so every
    reachable AskedPeer here is a refusal or a non-answer — never a successful hold."""
    peer_name = asked.found.peer.name
    refusal = getattr(asked, "refusal", "") or ""
    if "No tailnet-only endpoint" in refusal:
        options = _options_for_no_tailnet_endpoint(host, peer_name, refusal)
    else:
        options = _generic_options(host, peer_name)
    return BusConnectDecision(
        peer_name=peer_name,
        summary=_summary_for(asked),
        options=options,
    )
