"""Fail when a drawn string literal in src/toad spells an emoji-default character without U+FE0E.

Most symbols Toad draws (``▶``, ``✔``, ``⚠``, ``↗``) default to text presentation; the bundled
glyph fonts (`toad.qt.glyph_fonts`) sit ahead of the colour emoji font, so they ink in the
row's colour. A few code points default to *emoji* presentation in Unicode (Emoji_Presentation=Yes,
such as ``⏪`` ``⏳`` ``⚡`` ``⚫`` ``❓``): terminals and the phone draw them as coloured pictures
unless U+FE0E (VARIATION SELECTOR-15) follows. Each must be declared with it.

Usage: python tools/glyph_check.py   (from the checkout root; exit 1 on a finding)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Basic Multilingual Plane code points with Emoji_Presentation=Yes (Unicode emoji-data.txt):
# the ones a symbol might be mistaken for. Astral pictographs are emoji by intent.
EMOJI_DEFAULT = frozenset(
    "⌚⌛⏩⏪⏫⏬⏰⏳◽◾☔☕♈♉♊♋♌♍♎♏♐♑♒♓♿⚓⚡⚪⚫⚽⚾⛄⛅⛎⛔⛪⛲⛳⛵⛺⛽"
    "✅✊✋✨❌❎❓❔❕❗➕➖➗➰➿⬛⬜⭐⭕"
)
TEXT_PRESENTATION = "︎"


def findings(root: Path) -> list[str]:
    found = []
    for path in sorted((root / "src/toad").rglob("*.py")):
        relative = path.relative_to(root)
        tree = ast.parse(path.read_text(encoding="utf-8"), str(relative))
        docstrings = {id(body[0].value) for body in
                      (getattr(owner, "body", None) for owner in ast.walk(tree)
                       if isinstance(owner, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)))
                      if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)}
        for node in ast.walk(tree):
            if id(node) in docstrings or not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue  # documentation is never drawn
            text = node.value
            for index, character in enumerate(text):
                if character in EMOJI_DEFAULT and text[index + 1:index + 2] != TEXT_PRESENTATION:
                    found.append(f"{relative}:{node.lineno}: U+{ord(character):04X} {character} defaults to "
                                 f"emoji presentation; follow it with U+FE0E")
    return found


def main() -> int:
    found = findings(Path.cwd())
    for line in found:
        print(line)
    print(f"emoji-default characters drawn without U+FE0E: {len(found)}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
