from collections.abc import Sequence
from urllib.parse import urlencode


def tweet_intent_url(text: str, *, url: str, via: str, hashtags: Sequence[str]) -> str:
    """A pre-filled Twitter/X tweet intent URL.

    Args:
        text: The pre-filled tweet text.
        url: The URL appended to the tweet.
        via: The username the tweet is attributed to.
        hashtags: Hashtags to include (without '#').

    Returns:
        The full tweet intent URL.
    """
    params = {"text": text, "url": url, "hashtags": ",".join(hashtags), "via": via.lstrip("@")}
    return f"https://twitter.com/intent/tweet?{urlencode(params)}"
