"""Frontend-neutral declaration for 160 ms text-inversion tap feedback.

Both Qt's document tap highlights (`TapHighlight`: message headers, horizontal rules, links)
and Qt's interactive text controls (`TapFlashControl`: goal actions, session disclosures,
sort buttons, toolbar/composer buttons, queue links) inherit `TapFeedback` so every
clickable text surface shares one timing constant and one nominal ownership root.
"""

from __future__ import annotations

from typing import ClassVar

TAP_FLASH_MS: int = 160


class TapFeedback:
    """Nominal root for controls and overlays that invert ink/background on tap."""

    tap_flash_duration_ms: ClassVar[int] = TAP_FLASH_MS
