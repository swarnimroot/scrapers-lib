"""Reddit fetcher — Tier 1 source, unauthenticated JSON endpoints.

**Historical note:** Reddit's Nov-2025 "Responsible Builder Policy"
closed self-service PRAW OAuth registration for individual researchers.
The formal application path is also closed for our use case (see
``project_reddit_api_blocked`` memory). This module therefore uses
Reddit's **unauthenticated** JSON endpoints (``reddit.com/r/<sub>/new.json``,
``reddit.com/r/<sub>/comments/<id>.json``) which remain available at
~60 req/min with a descriptive ``User-Agent``.

Public function signatures are PRAW-compatible so an OAuth-backed
implementation can swap in behind the same contract if the policy
ever reopens — sorts (``"new"`` / ``"hot"`` / ``"top"`` / ``"rising"``),
pagination (``after`` cursor + ``limit``), and ``time_filter`` are all
idiomatic PRAW kwargs.

Two registered fetchers:

- ``fetch_reddit_listing`` (``@register("reddit")``) — subreddit listing
  → one :class:`RawMention` per post (``source_type="post"``).
- ``fetch_reddit_comments`` (``@register("reddit_comments")``) — post
  permalink → one :class:`RawMention` per comment (``source_type="comment"``,
  ``parent_id`` set to the post fullname). The post itself is emitted
  first with ``source_type="post"`` so a single call covers the whole
  post+comments tree the way PRAW's ``submission.comments.list()`` does.

Dual-mode (discovery / anchor-driven) matches :mod:`tier1.rss` and
:mod:`tier1.article`.

Deleted / removed content (``author="[deleted]"`` / ``body="[removed]"``)
is skipped rather than emitted as empty-text mentions. "More comments"
stubs (Reddit's ``kind="more"``) are not followed in this version —
counted in ``raw`` as a ``more_count`` so consumers know when they're
missing depth.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx

from scrapers_lib.core.attribution import (
    attribute_regex_all,
    reddit_comment_id,
    reddit_post_id,
)
from scrapers_lib.core.registry import register
from scrapers_lib.core.schemas import Anchor, Attribution, RawMention

logger = logging.getLogger(__name__)

SOURCE = "reddit"
SOURCE_COMMENTS = "reddit_comments"

# Reddit asks for descriptive User-Agents. The format here is the
# classic "bot-name/version (by author, purpose)" Reddit suggests.
_DEFAULT_USER_AGENT = (
    "scrapers-lib/0.5 (personal research; unauthenticated JSON)"
)

_REDDIT_HOSTS = ("reddit.com", "www.reddit.com", "old.reddit.com")

_VALID_SORTS = {"new", "hot", "top", "rising"}
_VALID_TIME_FILTERS = {"hour", "day", "week", "month", "year", "all"}

# Reddit markers that signal content has been deleted / removed.
_DELETED_AUTHOR_TOKENS = {"[deleted]", "[removed]"}
_DELETED_BODY_TOKENS = {"[deleted]", "[removed]"}


# ---------------------------------------------------------------------------
# Public API — subreddit listing
# ---------------------------------------------------------------------------


@register(SOURCE)
def fetch_reddit_listing(
    url: str,
    anchors: list[Anchor] | None = None,
    *,
    sort: str = "new",
    time_filter: str = "day",
    limit: int = 100,
    after: str | None = None,
    timeout: float = 30.0,
    user_agent: str = _DEFAULT_USER_AGENT,
    **_: Any,
) -> list[RawMention]:
    """Fetch a subreddit listing; emit one :class:`RawMention` per post.

    ``url`` accepts any of:

    - ``https://www.reddit.com/r/Games/`` — canonical subreddit URL
    - ``https://reddit.com/r/Games`` — host/trailing variations
    - ``r/Games`` — shorthand (expanded internally)
    - ``Games`` — bare subreddit name

    ``sort`` is one of ``"new"`` / ``"hot"`` / ``"top"`` / ``"rising"``.
    ``time_filter`` (``"hour"`` / ``"day"`` / ``"week"`` / ``"month"`` /
    ``"year"`` / ``"all"``) only applies when ``sort="top"``.

    ``limit`` caps entries per fetch (Reddit caps at 100 without auth).
    ``after`` is Reddit's opaque pagination cursor (``name`` of the last
    entry from a prior fetch); pass it through to walk multiple pages.

    Raises :class:`ValueError` on an unrecognized ``sort`` or
    ``time_filter``; :class:`httpx.HTTPStatusError` on non-2xx.
    """
    if sort not in _VALID_SORTS:
        raise ValueError(
            f"reddit: sort={sort!r} not in {_VALID_SORTS}"
        )
    if sort == "top" and time_filter not in _VALID_TIME_FILTERS:
        raise ValueError(
            f"reddit: time_filter={time_filter!r} not in {_VALID_TIME_FILTERS}"
        )

    subreddit = _extract_subreddit_name(url)
    api_url = f"https://www.reddit.com/r/{subreddit}/{sort}.json"
    params: dict[str, Any] = {"limit": max(1, min(100, int(limit)))}
    if sort == "top":
        params["t"] = time_filter
    if after:
        params["after"] = after

    body = _fetch_json(api_url, params=params, timeout=timeout, user_agent=user_agent)
    return parse_reddit_listing(body, subreddit=subreddit, anchors=anchors)


def parse_reddit_listing(
    body: dict[str, Any],
    *,
    subreddit: str,
    anchors: list[Anchor] | None = None,
) -> list[RawMention]:
    """Pure parse: subreddit listing JSON → list of post :class:`RawMention`.

    Dual-mode matches :func:`fetch_reddit_listing`. Deleted / removed
    posts (no meaningful text to attribute) are skipped.
    """
    children = (body.get("data") or {}).get("children") or []

    mentions: list[RawMention] = []
    for child in children:
        if child.get("kind") != "t3":
            continue
        post = child.get("data") or {}
        mentions.extend(
            _post_to_mentions(post, subreddit=subreddit, anchors=anchors)
        )
    return mentions


# ---------------------------------------------------------------------------
# Public API — post comments
# ---------------------------------------------------------------------------


@register(SOURCE_COMMENTS)
def fetch_reddit_comments(
    url: str,
    anchors: list[Anchor] | None = None,
    *,
    sort: str = "confidence",
    limit: int | None = None,
    timeout: float = 30.0,
    user_agent: str = _DEFAULT_USER_AGENT,
    **_: Any,
) -> list[RawMention]:
    """Fetch comments for a Reddit post; emit :class:`RawMention` objects.

    The first element is always the post itself (``source_type="post"``)
    so one call returns the complete post+comments bundle — mirrors
    PRAW's ``submission`` + ``submission.comments.list()`` usage.

    ``url`` accepts any of:

    - ``https://www.reddit.com/r/Games/comments/abc123/some_slug/``
    - ``https://reddit.com/comments/abc123``
    - ``t3_abc123`` — PRAW-style fullname
    - ``abc123`` — bare post ID

    ``sort`` passes through to Reddit's ``sort`` query param (accepted
    values: ``"confidence"`` / ``"top"`` / ``"new"`` / ``"controversial"``
    / ``"old"`` / ``"qa"``). ``limit`` caps top-level comment count if
    the caller wants a quick skim.

    Raises :class:`httpx.HTTPStatusError` on non-2xx.
    """
    subreddit, post_id = _extract_post_location(url)
    # Reddit accepts post-id-only URLs and redirects to canonical.
    api_url = f"https://www.reddit.com/comments/{post_id}.json"
    params: dict[str, Any] = {"sort": sort}
    if limit is not None:
        params["limit"] = max(1, int(limit))

    body = _fetch_json(api_url, params=params, timeout=timeout, user_agent=user_agent)
    return parse_reddit_comments(body, subreddit=subreddit, anchors=anchors)


def parse_reddit_comments(
    body: list[dict[str, Any]],
    *,
    subreddit: str | None,
    anchors: list[Anchor] | None = None,
) -> list[RawMention]:
    """Pure parse: comments endpoint response → mentions for post + comments.

    Reddit returns a two-element list: ``[post_listing, comments_listing]``.
    This parser walks both and emits one mention per post plus one per
    comment in pre-order (depth-first, same order Reddit renders them).
    Deleted / removed comments are skipped. ``kind="more"`` stubs (more-
    comments placeholders) are counted but not followed; the count is
    stored in each post's ``raw.more_count`` for downstream awareness.
    """
    if not isinstance(body, list) or len(body) < 2:
        logger.info(
            "reddit_comments: unexpected shape for r/%s; expected [post, comments] list",
            subreddit,
        )
        return []

    post_listing = body[0]
    comment_listing = body[1]

    post_children = (post_listing.get("data") or {}).get("children") or []
    if not post_children:
        return []
    post = (post_children[0] or {}).get("data") or {}

    sub = subreddit or post.get("subreddit") or ""

    more_count = _count_more_stubs(comment_listing)

    mentions: list[RawMention] = _post_to_mentions(
        post, subreddit=sub, anchors=anchors, extra_raw={"more_count": more_count}
    )

    for raw_comment in _walk_comments(comment_listing):
        mentions.extend(
            _comment_to_mentions(raw_comment, subreddit=sub, anchors=anchors)
        )

    return mentions


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _fetch_json(
    url: str,
    *,
    params: dict[str, Any],
    timeout: float,
    user_agent: str,
) -> Any:
    """GET ``url`` with JSON expectations and a descriptive User-Agent."""
    r = httpx.get(
        url,
        params=params,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        },
        follow_redirects=True,
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# URL / subreddit parsing (pure)
# ---------------------------------------------------------------------------


def _extract_subreddit_name(url_or_shorthand: str) -> str:
    """Accept ``"Games"`` / ``"r/Games"`` / full URL; return ``"Games"``.

    Case-preserving on the subreddit name — Reddit URLs are
    case-insensitive but users often capitalize (``"r/Games"`` vs
    ``"r/games"``); we echo back whatever the caller gave.
    """
    s = (url_or_shorthand or "").strip()
    if not s:
        raise ValueError("reddit: empty subreddit name or URL")

    if "://" in s:
        parsed = urlparse(s)
        host = (parsed.hostname or "").lower()
        if host and host not in _REDDIT_HOSTS:
            raise ValueError(
                f"reddit: URL host {host!r} is not a Reddit domain"
            )
        path = parsed.path.strip("/").split("/")
        if len(path) >= 2 and path[0].lower() == "r":
            return path[1]
        raise ValueError(
            f"reddit: URL path {parsed.path!r} does not match /r/<subreddit>"
        )

    # Shorthand forms.
    if s.lower().startswith("r/"):
        return s[2:].strip("/")
    return s.strip("/")


def _extract_post_location(url_or_id: str) -> tuple[str | None, str]:
    """Accept post URL / shortlink / ``t3_<id>`` / bare ID. Return ``(subreddit, id)``.

    ``subreddit`` is ``None`` when the input doesn't carry it (bare ID
    or ``/comments/<id>`` shortlink — Reddit will 301 to the canonical
    URL on fetch).
    """
    s = (url_or_id or "").strip()
    if not s:
        raise ValueError("reddit: empty post URL or ID")

    # Fullname form: t3_<id>.
    if s.startswith("t3_"):
        return None, s[3:]

    # URL form.
    if "://" in s:
        parsed = urlparse(s)
        host = (parsed.hostname or "").lower()
        if host and host not in _REDDIT_HOSTS:
            raise ValueError(
                f"reddit: URL host {host!r} is not a Reddit domain"
            )
        parts = parsed.path.strip("/").split("/")
        # Shapes:
        # r/<sub>/comments/<id>/<slug>  -> parts[0..4]
        # comments/<id>                 -> parts[0..1]
        if len(parts) >= 4 and parts[0].lower() == "r" and parts[2] == "comments":
            return parts[1], parts[3]
        if len(parts) >= 2 and parts[0] == "comments":
            return None, parts[1]
        raise ValueError(
            f"reddit: URL path {parsed.path!r} does not match "
            f"/r/<sub>/comments/<id>/<slug> or /comments/<id>"
        )

    # Bare ID.
    if s.isalnum():
        return None, s

    raise ValueError(f"reddit: cannot interpret {url_or_id!r} as a post reference")


# ---------------------------------------------------------------------------
# Post + comment flatteners (pure)
# ---------------------------------------------------------------------------


def _compose_post_text(post: dict[str, Any]) -> str:
    """Post title + selftext (when non-empty), joined with a newline."""
    title = (post.get("title") or "").strip()
    selftext = (post.get("selftext") or "").strip()
    if selftext in _DELETED_BODY_TOKENS:
        selftext = ""
    parts = [p for p in (title, selftext) if p]
    return "\n".join(parts)


def _cleaned_author(raw_author: Any) -> str | None:
    """Map Reddit's ``[deleted]`` / ``[removed]`` author sentinels to ``None``."""
    if not raw_author:
        return None
    s = str(raw_author).strip()
    if not s or s in _DELETED_AUTHOR_TOKENS:
        return None
    return s


def _created_at(raw: dict[str, Any]) -> datetime | None:
    """Convert Reddit's ``created_utc`` (seconds-since-epoch float) to UTC datetime."""
    ts = raw.get("created_utc")
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _post_to_mentions(
    post: dict[str, Any],
    *,
    subreddit: str,
    anchors: list[Anchor] | None,
    extra_raw: dict[str, Any] | None = None,
) -> list[RawMention]:
    text = _compose_post_text(post)
    if not text:
        # Fully deleted/removed with no title — skip.
        return []

    post_id = post.get("id") or ""
    if not post_id:
        return []

    permalink = post.get("permalink") or ""
    source_url = (
        f"https://www.reddit.com{permalink}" if permalink else
        (post.get("url") or f"https://www.reddit.com/r/{subreddit}/comments/{post_id}")
    )

    raw: dict[str, Any] = {
        "post_id": post_id,
        "score": post.get("score"),
        "num_comments": post.get("num_comments"),
        "url": post.get("url"),  # linked URL for link posts
        "over_18": post.get("over_18"),
        "is_self": post.get("is_self"),
    }
    if extra_raw:
        raw.update(extra_raw)

    base = {
        "source": SOURCE,
        "source_type": "post",
        "source_url": source_url,
        "source_title": (post.get("title") or None),
        "author": _cleaned_author(post.get("author")),
        "channel": f"r/{subreddit}" if subreddit else None,
        "parent_id": None,
        "published_at": _created_at(post),
        "raw_text": text,
        "raw": raw,
    }

    base_mention_id = reddit_post_id(post_id)
    return list(_fan_out(base, base_mention_id, text, anchors))


def _comment_to_mentions(
    comment: dict[str, Any],
    *,
    subreddit: str,
    anchors: list[Anchor] | None,
) -> list[RawMention]:
    body = (comment.get("body") or "").strip()
    if not body or body in _DELETED_BODY_TOKENS:
        return []

    comment_id = comment.get("id") or ""
    if not comment_id:
        return []

    permalink = comment.get("permalink") or ""
    source_url = (
        f"https://www.reddit.com{permalink}" if permalink else
        f"https://www.reddit.com/r/{subreddit}/comments//{comment_id}"
    )

    link_id = comment.get("link_id")  # "t3_<post_id>"
    raw: dict[str, Any] = {
        "comment_id": comment_id,
        "parent_id": comment.get("parent_id"),
        "link_id": link_id,
        "depth": comment.get("depth"),
        "score": comment.get("score"),
    }

    base = {
        "source": SOURCE,
        "source_type": "comment",
        "source_url": source_url,
        "source_title": None,
        "author": _cleaned_author(comment.get("author")),
        "channel": f"r/{subreddit}" if subreddit else None,
        # parent_id on RawMention = the Reddit link_id (post fullname)
        # — this lets consumers group comments under their post.
        "parent_id": link_id,
        "published_at": _created_at(comment),
        "raw_text": body,
        "raw": raw,
    }

    base_mention_id = reddit_comment_id(comment_id)
    return list(_fan_out(base, base_mention_id, body, anchors))


def _fan_out(
    base: dict[str, Any],
    base_mention_id: str,
    match_text: str,
    anchors: list[Anchor] | None,
) -> Iterable[RawMention]:
    """Common discovery / anchor-driven emission logic."""
    if anchors is None:
        yield RawMention(mention_id=base_mention_id, attribution=None, **base)
        return
    for match in attribute_regex_all(match_text, anchors):
        yield RawMention(
            mention_id=f"{base_mention_id}_{match.anchor_id}",
            attribution=match,
            **base,
        )


def _walk_comments(listing: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield every ``t1`` (comment) dict in pre-order, following nested ``replies``.

    Skips ``more`` stubs (Reddit's placeholder for "click to load more
    comments"); the caller should count these separately via
    :func:`_count_more_stubs`.
    """
    children = (listing.get("data") or {}).get("children") or []
    for child in children:
        kind = child.get("kind")
        if kind != "t1":
            continue
        data = child.get("data") or {}
        yield data
        replies = data.get("replies")
        if isinstance(replies, dict):
            yield from _walk_comments(replies)


def _count_more_stubs(listing: Any) -> int:
    """Count ``kind="more"`` placeholders nested anywhere in a comment tree.

    Represents "unfetched comments" the consumer is missing — useful
    telemetry even though we do not recursively follow them in v1.
    """
    if not isinstance(listing, dict):
        return 0
    count = 0
    for child in (listing.get("data") or {}).get("children") or []:
        if child.get("kind") == "more":
            children_ids = (child.get("data") or {}).get("children") or []
            # "more" stubs list the IDs they cover; count size as lower bound.
            count += len(children_ids)
            continue
        data = child.get("data") or {}
        replies = data.get("replies")
        if isinstance(replies, dict):
            count += _count_more_stubs(replies)
    return count
