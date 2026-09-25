"""Readable Markdown for owner-provided coordination metadata, retaining its source."""

from __future__ import annotations

import json
import re


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate context key")
        result[key] = value
    return result


_decoder = json.JSONDecoder(object_pairs_hook=_unique_object)


def _inline(value: object) -> str:
    text = ("—" if value is None else "true" if value is True else
            "false" if value is False else str(value))
    # Metadata is literal text, not Markdown links, emphasis, or table syntax.
    return re.sub(r"([\\`*_{}\[\]<>|])", r"\\\1", text.replace("\n", " / ").replace("\r", "")) or "(empty)"


def _label(key: object) -> str:
    return _inline(str(key).replace("_", " ").capitalize())


def _render(value: object, depth: int = 0) -> str:
    indent = "  " * depth
    if isinstance(value, dict):
        rows = []
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                rows.append(f"{indent}- **{_label(key)}:**\n{_render(item, depth + 1)}")
            else:
                shown = "None listed" if isinstance(item, (dict, list)) else _inline(item)
                rows.append(f"{indent}- **{_label(key)}:** {shown}")
        return "\n".join(rows) or f"{indent}None listed."
    if isinstance(value, list):
        if not value:
            return f"{indent}None listed."
        if depth == 0 and all(isinstance(item, dict) for item in value):
            columns = list(dict.fromkeys(key for item in value for key in item))
            if 0 < len(columns) <= 6 and all(
                not isinstance(cell, (dict, list)) for item in value for cell in item.values()
            ):
                labels = {"name": "Thread", "activity_detail": "Details"}
                heading = "| " + " | ".join(labels.get(key, _label(key)) for key in columns) + " |"
                divider = "| " + " | ".join("---" for _ in columns) + " |"
                rows = ["| " + " | ".join(_inline(item.get(key)) for key in columns) + " |"
                        for item in value]
                return "\n".join((heading, divider, *rows))
        return "\n".join(
            f"{indent}- Item {index}:\n{_render(item, depth + 1)}"
            if isinstance(item, (dict, list)) else f"{indent}- {_inline(item)}"
            for index, item in enumerate(value, 1)
        )
    return f"{indent}{_inline(value)}"


def format_coordination_context(content: str) -> str:
    """Format JSON or the native Peer state section; leave other Markdown intact."""
    try:
        value = _decoder.decode(content)
        if isinstance(value, (dict, list)):
            return "## Coordination context\n\n" + _render(value)
    except (ValueError, RecursionError):
        pass
    prefix, marker, remainder = content.partition("Peer state:")
    if not marker:
        return content
    remainder = remainder.lstrip()
    try:
        peers, end = _decoder.raw_decode(remainder)
        if not isinstance(peers, list):
            return content
        before = prefix.removeprefix("Coordination context:").strip()
        after = remainder[end:].strip()
        sections = (["## Coordination\n\n" + before] if before else [])
        sections.append("## Peers\n\n" + _render(peers))
        if after:
            sections.append("## Task context\n\n" + after)
        return "\n\n".join(sections)
    except (ValueError, RecursionError):
        return content


def literal_context(content: str) -> str:
    """A code fence that cannot be closed by backticks in the original payload."""
    longest = max((len(match.group()) for match in re.finditer(r"`+", content)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{content}\n{fence}"
