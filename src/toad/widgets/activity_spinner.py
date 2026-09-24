"""One-cell paint-only replacement for busy hourglass markers in Toad views."""

FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


def animated_label(label: str, *, busy: bool, phase: int) -> str:
    if not busy:
        return label
    for marker in ("⌛ ", "● "):
        if label.startswith(marker):
            return f"{FRAMES[phase % len(FRAMES)]} {label[len(marker):]}"
    return label
