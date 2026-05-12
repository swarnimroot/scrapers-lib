"""Article body fetcher (trafilatura) — Tier 1 source.

Follow-up body extraction for URLs whose summary (from RSS, newsletter,
hand-curated list, etc.) is too terse for analysis. Fetches via the
shared ``warmed_curl_session()`` helper (Chrome TLS impersonation +
HTTP/1.1 + per-host homepage warming) so Cloudflare-fronted reviewer
sites (notebookcheck.net and the broader gaming/tech reviewer set)
return real HTML instead of a 403. The HTML then goes through
``trafilatura.bare_extraction`` which returns a ``Document`` with the
main body text plus metadata (title, author, date, sitename) —
resilient to most news / blog layouts.

Dual-mode matches :mod:`tier1.rss`:

- **Discovery mode** (``anchors=None``) — one :class:`RawMention` with
  ``attribution=None``.
- **Anchor-driven mode** (``anchors=[...]``) — one ``RawMention`` per
  matching anchor via :func:`attribute_regex_all`; empty list if no
  anchor matches.

**Partial-success posture**: returns an empty list (not an exception)
when trafilatura can't pull a usable body — paywalls, 404 pages with
navigation chrome only, pages below ``min_length`` chars. HTTP errors
(non-2xx) still raise via ``httpx.HTTPStatusError`` (curl_cffi response
errors are re-wrapped to preserve the documented exception contract,
since the Scheduler's retry / backoff logic keys off that type) — the
caller / the Scheduler handles retry and domain-level backoff.

``trafilatura`` is imported lazily so ``import scrapers_lib`` stays
cheap for consumers that never touch Wave 3.

Verified on two unrelated real articles during Wave 3 recon (IGN games
post + Polygon news post); both returned clean body + full metadata
with identical ``Document`` shape.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from scrapers_lib._version import __version__
from scrapers_lib.core.attribution import (
    article_mention_id,
    attribute_regex_all,
)
from scrapers_lib.core.curl_session import warmed_curl_session
from scrapers_lib.core.registry import register
from scrapers_lib.core.schemas import Anchor, Attribution, RawMention

logger = logging.getLogger(__name__)

SOURCE = "article"

_DEFAULT_USER_AGENT = (
    f"Mozilla/5.0 (compatible; scrapers-lib/{__version__}; +https://github.com/)"
)

# Minimum extracted body length to accept. Below this, the extraction is
# almost certainly paywall chrome / nav boilerplate / 404 page content
# and emitting it would pollute the corpus.
_DEFAULT_MIN_LENGTH = 200


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@register(SOURCE)
def fetch_article(
    url: str,
    anchors: list[Anchor] | None = None,
    *,
    source_slug: str | None = None,
    timeout: float = 30.0,
    min_length: int = _DEFAULT_MIN_LENGTH,
    **_: Any,
) -> list[RawMention]:
    """Fetch ``url``, extract the article body, return :class:`RawMention` list.

    ``source_slug`` is used as :attr:`RawMention.source`. When omitted,
    falls back to the URL's hostname (stripped of ``www.``).

    ``min_length`` gates the extracted body: extractions below this
    character count are treated as failed and the call returns ``[]``.

    Raises :class:`httpx.HTTPStatusError` on non-2xx HTTP responses.
    Returns ``[]`` when the page returns 200 but trafilatura can't
    extract a usable body (paywall, empty page, nav chrome only).
    """
    html = _fetch_html(url, timeout=timeout)
    return parse_article(
        html,
        url,
        anchors=anchors,
        source_slug=source_slug,
        min_length=min_length,
    )


def parse_article(
    html: str,
    url: str,
    *,
    anchors: list[Anchor] | None = None,
    source_slug: str | None = None,
    min_length: int = _DEFAULT_MIN_LENGTH,
) -> list[RawMention]:
    """Pure parse: HTML → list of :class:`RawMention`.

    Dual-mode behavior matches :func:`fetch_article`. Returns ``[]``
    when trafilatura returns ``None`` (no extractable content), when
    the extracted body is below ``min_length``, or — in anchor-driven
    mode — when the body matches no anchor.
    """
    import trafilatura  # noqa: I001  (lazy: keeps core import cheap)

    doc = trafilatura.bare_extraction(html, url=url, with_metadata=True)
    if doc is None:
        logger.info("article: trafilatura returned no content for %s", url)
        return []

    body = (doc.text or "").strip()
    if len(body) < min_length:
        logger.info(
            "article: extracted body for %s is %d chars (below min_length=%d); "
            "treating as extraction failure",
            url,
            len(body),
            min_length,
        )
        return []

    effective_slug = source_slug or _derive_slug(url)

    base = {
        "source": effective_slug,
        "source_type": "article",
        "source_url": url,
        "source_title": (doc.title or None),
        "author": (doc.author or None),
        # Prefer sitename (human-readable, e.g. "IGN") over hostname
        # ("ign.com") for channel labeling.
        "channel": (doc.sitename or doc.hostname or None),
        "published_at": _parse_date(doc.date),
        "raw_text": body,
        "raw": {
            "extractor": "trafilatura",
            "hostname": doc.hostname,
            "sitename": doc.sitename,
            "image": doc.image,
            "description": doc.description,
        },
    }

    if anchors is None:
        return [_finalize_mention(base, url, effective_slug, attribution=None)]

    mentions: list[RawMention] = []
    for match in attribute_regex_all(body, anchors):
        mentions.append(
            _finalize_mention(base, url, effective_slug, attribution=match)
        )
    return mentions


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _fetch_html(url: str, *, timeout: float) -> str:
    """Fetch article HTML via a warmed, Chrome-impersonated curl_cffi session.

    Uses :func:`warmed_curl_session` (Chrome TLS impersonation + HTTP/1.1
    + per-host homepage warming) so Cloudflare-fronted reviewer sites
    return real HTML instead of 403. curl_cffi response errors on the
    target fetch are translated into :class:`httpx.HTTPStatusError` so
    the documented exception contract — and the Scheduler's retry /
    backoff logic that keys off it — keep working.

    Raises :class:`httpx.HTTPStatusError` on non-2xx.
    """
    homepage = _homepage_for(url)
    with warmed_curl_session(homepage, timeout=timeout) as s:
        r = s.get(
            url,
            headers={
                "User-Agent": _DEFAULT_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=timeout,
        )
    status = getattr(r, "status_code", 0)
    if status >= 400:
        request = httpx.Request("GET", url)
        response = httpx.Response(status, request=request)
        kind = "Client" if status < 500 else "Server"
        raise httpx.HTTPStatusError(
            f"{kind} error '{status}' for url '{url}'",
            request=request,
            response=response,
        )
    return r.text


def _homepage_for(url: str) -> str:
    """Return the ``scheme://host/`` form of ``url`` for session warming.

    Used as the warm-up GET target before the article fetch — settles
    CDN cookies under the same hostname. Falls back to the input URL if
    parsing yields no host (defensive — should not happen for valid
    inputs).
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    return f"{parsed.scheme}://{parsed.netloc}/"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _derive_slug(url: str) -> str:
    """Best-effort slug from an article URL (hostname minus ``www.``).

    Falls back to ``"article"`` so :attr:`RawMention.source` is never
    empty.
    """
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[len("www.") :]
    first_label = host.split(".", 1)[0] if host else ""
    return first_label or SOURCE


def _parse_date(date_str: str | None) -> datetime | None:
    """trafilatura gives back a ``YYYY-MM-DD`` string; parse to UTC datetime.

    Returns ``None`` on missing / malformed inputs (trafilatura's date
    extraction is best-effort — some sites have no machine-readable
    date).
    """
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        logger.debug("article: could not parse date %r", date_str)
        return None


def _finalize_mention(
    base: dict[str, Any],
    url: str,
    slug: str,
    attribution: Attribution | None,
) -> RawMention:
    """Stamp ``mention_id`` + ``attribution`` onto the shared base.

    In anchor-driven mode the mention_id suffixes the anchor_id so two
    anchor hits on the same article produce distinct deterministic IDs
    (same pattern as :mod:`tier1.rss`).
    """
    base_id = article_mention_id(slug, url)
    if attribution is None:
        mention_id = base_id
    else:
        mention_id = f"{base_id}_{attribution.anchor_id}"
    return RawMention(mention_id=mention_id, attribution=attribution, **base)
