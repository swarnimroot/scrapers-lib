"""Attribution gates and deterministic mention-ID helpers.

Two gates decide whether a fetched unit (a comment, a paragraph, a transcript chunk,
a product page) belongs to one of a consumer's Anchors:

- :func:`attribute_regex` — token matching against ``Anchor.attribution_regex``.
  Used for community text, reviews, articles, transcripts.
- :func:`attribute_url` — exact URL match against ``Anchor.source_urls``.
  Used for product or review pages that are uniquely identified by URL.

Drop-over-guess discipline: if a unit matches multiple Anchors, it is logged and
returns ``None`` rather than being force-attributed to one of them.

Mention-ID helpers produce deterministic IDs so re-fetches collide rather than
duplicate.
"""

from __future__ import annotations

import hashlib
import logging
import re

from scrapers_lib.core.schemas import Anchor, Attribution

logger = logging.getLogger(__name__)


def _check_tokens(text: str, tokens: list[str]) -> list[str]:
    """Return the subset of ``tokens`` that occur in ``text`` (case-insensitive).

    Tokens prefixed with ``re:`` are treated as raw regex; others are literal
    substrings (auto-escaped). No automatic word boundaries — consumers who want
    them should use ``re:\\bfoo\\b``.
    """
    matched: list[str] = []
    for token in tokens:
        if token.startswith("re:"):
            pattern = token[3:]
        else:
            pattern = re.escape(token)
        try:
            if re.search(pattern, text, re.IGNORECASE):
                matched.append(token)
        except re.error as e:
            logger.warning("invalid regex token %r skipped: %s", token, e)
    return matched


def attribute_regex(text: str, anchors: list[Anchor]) -> Attribution | None:
    """Return an :class:`Attribution` if exactly one Anchor matches ``text``.

    Matching rules per Anchor:

    - Any ``exclusion`` token match drops the Anchor.
    - At least one ``primary`` token must match.
    - If ``corroboration`` is non-empty, at least one must also match.

    Returns ``None`` when no Anchor matches, when multiple Anchors match
    (ambiguous — logged at info level), or when inputs are empty.
    """
    if not text or not anchors:
        return None

    candidates: list[tuple[Anchor, list[str]]] = []

    for anchor in anchors:
        rules = anchor.attribution_regex

        if _check_tokens(text, rules.exclusion):
            continue

        primary_hits = _check_tokens(text, rules.primary)
        if not primary_hits:
            continue

        if rules.corroboration:
            corrob_hits = _check_tokens(text, rules.corroboration)
            if not corrob_hits:
                continue
            matched = primary_hits + corrob_hits
        else:
            matched = primary_hits

        candidates.append((anchor, matched))

    if not candidates:
        return None

    if len(candidates) > 1:
        logger.info(
            "attribution ambiguous: text matched %d anchors (%s); dropped",
            len(candidates),
            ", ".join(a.anchor_id for a, _ in candidates),
        )
        return None

    anchor, matched = candidates[0]
    return Attribution(
        anchor_id=anchor.anchor_id,
        confidence=1.0,
        method="regex",
        matched_tokens=matched,
    )


def attribute_url(url: str, source: str, anchors: list[Anchor]) -> Attribution | None:
    """Return an :class:`Attribution` if exactly one Anchor has ``source_urls[source] == url``.

    Exact string match — consumers are responsible for providing canonical URLs
    (trailing slashes, query strings, fragments all matter).

    Returns ``None`` when no Anchor matches or when multiple Anchors claim the
    same URL (ambiguous — logged at info level).
    """
    if not url or not source or not anchors:
        return None

    matches = [a for a in anchors if a.source_urls.get(source) == url]

    if not matches:
        return None

    if len(matches) > 1:
        logger.info(
            "url attribution ambiguous: source=%s url=%s matched anchors %s",
            source,
            url,
            [a.anchor_id for a in matches],
        )
        return None

    return Attribution(
        anchor_id=matches[0].anchor_id,
        confidence=1.0,
        method="url_map",
        matched_tokens=[],
    )


def _slugify(s: str) -> str:
    """Lowercase ASCII slug, underscores between runs of non-alphanumerics."""
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _hash_short(s: str, length: int = 12) -> str:
    """Short deterministic hash of ``s`` (sha256 truncated)."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:length]


def reddit_post_id(post_id: str) -> str:
    return f"reddit_post_{post_id}"


def reddit_comment_id(comment_id: str) -> str:
    return f"reddit_comment_{comment_id}"


def rss_article_id(source_slug: str, article_guid: str) -> str:
    """Deterministic ID for an RSS article.

    ``source_slug`` is a human-readable source name (e.g., ``"IGN"``, ``"The Verge"``);
    it is slugified. ``article_guid`` is whatever unique identifier the feed provides
    (often a URL); it is hashed to keep IDs short.
    """
    return f"rss_{_slugify(source_slug)}_{_hash_short(article_guid)}"


def paragraph_id(source: str, anchor_id: str, paragraph_index: int) -> str:
    """Deterministic ID for a paragraph on a page pre-attributed to an Anchor."""
    return f"{source}_{anchor_id}_p{paragraph_index}"


def youtube_chunk_id(video_id: str, chunk_index: int) -> str:
    """Deterministic ID for a chunk of a YouTube transcript."""
    return f"youtube_{video_id}_chunk_{chunk_index}"


def amazon_review_id(asin: str, review_id: str) -> str:
    """Deterministic ID for an Amazon review. ``review_id`` is Amazon's own R-prefix ID."""
    return f"amazon_{asin}_{review_id}"


def bestbuy_review_id(sku: str, author: str, body: str) -> str:
    """Deterministic ID for a BestBuy review.

    BestBuy's PDP JSON-LD does not carry stable per-review IDs, so the
    ID is a short hash of ``(author, body_prefix)`` — stable for the
    same review and unlikely to collide across reviews on the same SKU.
    """
    return f"bestbuy_{sku}_{_hash_short(author + '|' + body[:200])}"
