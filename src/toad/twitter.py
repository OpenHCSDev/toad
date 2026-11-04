from urllib.parse import urlencode


def tweet_intent_url(
    text: str,
    *,
    url: str | None = None,
    hashtags: list[str] | None = None,
    via: str | None = None,
    in_reply_to: str | None = None,
) -> str:
    """A pre-filled Twitter/X tweet intent URL.

    Args:
        text: The pre-filled tweet text.
        url: An optional URL to append to the tweet.
        hashtags: An optional list of hashtags to include (without '#').
        via: An optional username to attribute the tweet to.
        in_reply_to: An optional tweet ID to reply to.

    Returns:
        The full tweet intent URL.
    """
    params: dict[str, str] = {"text": text}

    if url is not None:
        params["url"] = url
    if hashtags:
        params["hashtags"] = ",".join(hashtags)
    if via is not None:
        params["via"] = via.lstrip("@")
    if in_reply_to is not None:
        params["in_reply_to"] = in_reply_to

    return f"https://twitter.com/intent/tweet?{urlencode(params)}"
