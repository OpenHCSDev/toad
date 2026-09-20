from textual.content import Content


def pill(
    text: Content | str,
    background: str,
    foreground: str,
    *,
    filled: bool = True,
) -> Content:
    """Format text as a pill (half block ends).

    Args:
        text: Pill contents as Content object or text.
        background: Background color.
        foreground: Foreground color.
        filled: Use a filled pill. Unfilled pills avoid unreliable ANSI color pairing.

    Returns:
        Pill content.
    """
    content = Content(text) if isinstance(text, str) else text
    if not filled:
        style = f"{foreground} bold"
        return Content.assemble(("[", style), content.stylize(style), ("]", style))
    main_style = f"{foreground} on {background}"
    end_style = f"{background} on transparent r"
    pill_content = Content.assemble(
        ("▌", end_style),
        content.stylize(main_style),
        ("▐", end_style),
    )
    return pill_content
