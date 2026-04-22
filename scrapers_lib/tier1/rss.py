"""RSS / Atom feed fetcher — Tier 1 source.

Uses :mod:`feedparser` to normalize RSS 2.0 and Atom into a shared
entry shape, emits :class:`RawMention` per entry in one of two modes:

- **Discovery mode** (``anchors=None``) — every feed entry becomes one
  ``RawMention`` with ``attribution=None``. Downstream consumers apply
  their own filters (trending-term scans, co-mention graphs, top-title
  by engagement, etc.). Use this when you want to see what's being
  talked about without pre-filtering. This is Demo 3's primary mode.
- **Anchor-driven mode** (``anchors=[...]``) — every entry is scanned
  for matches against each Anchor's ``attribution_regex`` via
  :func:`attribute_regex_all`; one ``RawMention`` is emitted per match.
  Entries matching no anchor are dropped. Use this when you know what
  you're tracking. This is Demo 1's primary mode.

The fetcher consumes any feed; the caller supplies ``source_slug`` to
label the resulting mentions (``"ign"``, ``"polygon"``, etc.). When
``source_slug`` is omitted, it is derived from the feed URL's hostname
(``feeds.ign.com`` → ``ign``) as a best-effort fallback.

``feedparser`` is imported lazily so ``import scrapers_lib`` stays
cheap for consumers that never touch Wave 3.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from scrapers_lib.core.attribution import (
    attribute_regex_all,
    rss_article_id,
)
from scrapers_lib.core.registry import register
from scrapers_lib.core.schemas import Anchor, Attribution, RawMention

logger = logging.getLogger(__name__)

SOURCE = "rss"

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; scrapers-lib/0.5; +https://github.com/)"
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@register(SOURCE)
def fetch_rss_feed(
    url: str,
    anchors: list[Anchor] | None = None,
    *,
    source_slug: str | None = None,
    timeout: float = 30.0,
    **_: Any,
) -> list[RawMention]:
    """Fetch a feed URL and return :class:`RawMention` objects.

    When ``anchors`` is ``None`` the fetcher runs in discovery mode
    (one mention per entry, ``attribution=None``). When ``anchors`` is
    a non-empty list the fetcher runs in anchor-driven mode (one mention
    per matching anchor per entry; entries matching nothing are dropped).

    ``source_slug`` is used as the :attr:`RawMention.source` label
    (typically the short site name: ``"ign"``, ``"polygon"``,
    ``"rockpapershotgun"``). When omitted, a fallback slug is derived
    from the feed URL's hostname.
    """
    body = _fetch_feed_bytes(url, timeout=timeout)
    return parse_rss_feed(body, url, anchors=anchors, source_slug=source_slug)


def parse_rss_feed(
    body: str | bytes,
    url: str,
    *,
    anchors: list[Anchor] | None = None,
    source_slug: str | None = None,
) -> list[RawMention]:
    """Pure parse: feed bytes → list of :class:`RawMention`.

    Dual-mode behavior matches :func:`fetch_rss_feed`. Entries with no
    stable identifier (no ``id``, no ``link``, no title) are skipped
    with a warning — they would collide on re-fetch. Entries with no
    usable text (no title, no summary, no content) are also skipped.
    """
    import feedparser  # noqa: I001  (lazy: keeps core import cheap)

    feed = feedparser.parse(body)
    effective_slug = source_slug or _derive_slug(url)
    channel = (feed.feed.get("title") if feed.feed else None) or None

    mentions: list[RawMention] = []
    for entry in feed.entries:
        raw_text = _compose_entry_text(entry)
        if not raw_text:
            logger.debug("rss: entry with no title/summary/content skipped")
            continue

        guid = _entry_guid(entry)
        if not guid:
            logger.warning(
                "rss: entry on %s has no id/link/title; skipping (would collide)",
                url,
            )
            continue

        base = _build_entry_mention_base(
            entry=entry,
            raw_text=raw_text,
            source=effective_slug,
            channel=channel,
            guid=guid,
        )

        if anchors is None:
            mentions.append(
                _finalize_mention(
                    base=base, slug=effective_slug, guid=guid, attribution=None
                )
            )
        else:
            for match in attribute_regex_all(raw_text, anchors):
                mentions.append(
                    _finalize_mention(
                        base=base, slug=effective_slug, guid=guid, attribution=match
                    )
                )

    return mentions


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _fetch_feed_bytes(url: str, *, timeout: float) -> bytes:
    """Fetch a feed URL with a conservative User-Agent; return body bytes."""
    r = httpx.get(
        url,
        headers={
            "User-Agent": _DEFAULT_USER_AGENT,
            "Accept": (
                "application/rss+xml, application/atom+xml, application/xml, "
                "text/xml, */*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
        follow_redirects=True,
        timeout=timeout,
    )
    r.raise_for_status()
    return r.content


# ---------------------------------------------------------------------------
# Entry helpers (pure)
# ---------------------------------------------------------------------------


def _derive_slug(url: str) -> str:
    """Best-effort slug from a feed URL hostname.

    Strips ``www.`` / ``feeds.`` prefixes and takes the first domain
    label (``feeds.ign.com`` → ``ign``, ``www.polygon.com`` → ``polygon``).
    Falls back to ``"rss"`` if parsing yields nothing useful. Consumers
    should prefer passing ``source_slug`` explicitly; this exists so
    ``RawMention.source`` is never empty.
    """
    host = urlparse(url).hostname or ""
    for prefix in ("www.", "feeds."):
        if host.startswith(prefix):
            host = host[len(prefix) :]
            break
    first_label = host.split(".", 1)[0] if host else ""
    return first_label or SOURCE


def _entry_guid(entry: Any) -> str:
    """Return a stable identifier for a feed entry.

    Preference order: ``id`` (feedparser's normalized GUID), ``link``,
    then ``title + published`` as a fallback. Empty string if none.
    """
    guid = entry.get("id")
    if guid:
        return str(guid)
    link = entry.get("link")
    if link:
        return str(link)
    title = (entry.get("title") or "").strip()
    published = (entry.get("published") or entry.get("updated") or "").strip()
    combo = f"{title}|{published}".strip("|")
    return combo


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_INLINE_WS_RE = re.compile(r"[ \t\r\f\v]+")


def _strip_html(html: str) -> str:
    """Minimal HTML strip — tags only, not entities."""
    return _HTML_TAG_RE.sub(" ", html)


def _compose_entry_text(entry: Any) -> str:
    """Build ``raw_text`` from title + summary + content.

    Concatenates available pieces with newlines, strips HTML tags,
    collapses intra-line whitespace. Returns empty string if nothing
    usable is present.
    """
    parts: list[str] = []

    title = (entry.get("title") or "").strip()
    if title:
        parts.append(title)

    summary = entry.get("summary") or ""
    if summary:
        parts.append(_strip_html(summary))

    content = entry.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict):
            value = first.get("value") or ""
            if value:
                parts.append(_strip_html(value))

    if not parts:
        return ""

    composed = "\n".join(p for p in parts if p)
    lines = [_INLINE_WS_RE.sub(" ", line).strip() for line in composed.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _entry_published(entry: Any) -> datetime | None:
    """Parse ``published_parsed`` (preferred) or ``updated_parsed`` to UTC datetime."""
    for field in ("published_parsed", "updated_parsed"):
        struct = entry.get(field)
        if struct is None:
            continue
        try:
            return datetime(*struct[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
    return None


def _entry_author(entry: Any) -> str | None:
    """Extract author name, preferring ``author`` over ``author_detail.name``."""
    author = entry.get("author") or None
    if author:
        return str(author).strip() or None
    detail = entry.get("author_detail")
    if isinstance(detail, dict):
        name = detail.get("name")
        if name:
            return str(name).strip() or None
    return None


def _build_entry_mention_base(
    *,
    entry: Any,
    raw_text: str,
    source: str,
    channel: str | None,
    guid: str,
) -> dict[str, Any]:
    """Per-entry fields used by both discovery and anchor modes."""
    return {
        "source": source,
        "source_type": "article",
        "source_url": entry.get("link") or guid,
        "source_title": (entry.get("title") or None),
        "author": _entry_author(entry),
        "channel": channel,
        "published_at": _entry_published(entry),
        "raw_text": raw_text,
        "raw": {"entry_guid": guid},
    }


def _finalize_mention(
    *,
    base: dict[str, Any],
    slug: str,
    guid: str,
    attribution: Attribution | None,
) -> RawMention:
    """Stamp ``mention_id`` + ``attribution`` onto an entry base.

    In anchor-driven mode the mention_id is suffixed with the anchor_id
    so two anchor hits on the same article produce distinct deterministic
    IDs. In discovery mode the article guid alone is the identifier.
    """
    base_id = rss_article_id(slug, guid)
    if attribution is None:
        mention_id = base_id
    else:
        mention_id = f"{base_id}_{attribution.anchor_id}"
    return RawMention(mention_id=mention_id, attribution=attribution, **base)
