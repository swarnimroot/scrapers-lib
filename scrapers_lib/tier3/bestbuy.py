"""BestBuy PDP review fetcher (reviews only — product data lives in ``tier1/bestbuy_api``).

BestBuy's retail PDP at ``bestbuy.com/site/.../<SKU>.p`` is Akamai-
protected at both the TLS and HTTP/2 layers: plain httpx drops with
``RemoteProtocolError``, stealth Playwright fails at ``net::
ERR_HTTP2_PROTOCOL_ERROR`` at navigation, and curl_cffi with Chrome
TLS impersonation still gets ``HTTP/2 INTERNAL_ERROR`` RST_STREAM on
any request to ``/site/...`` — but **curl_cffi with Chrome
impersonation on HTTP/1.1** goes through cleanly.

The fetcher uses a curl_cffi session that:

1. Warms against ``https://www.bestbuy.com/`` to seat Akamai cookies.
2. Fetches the target PDP at HTTP/1.1.
3. Parses the inline ``<script type="application/ld+json">`` blocks
   for ``@type: Product`` → ``review[*]`` (list of ``Review`` objects
   with ``name`` / ``author.name`` / ``reviewBody`` / ``reviewRating.
   ratingValue``). BestBuy embeds the top ~5 reviews; deeper
   pagination lives at ``bestbuy.com/site/reviews/name/<SKU>`` — same
   gate pattern, deferred to a future wave once multi-page traversal
   and an AggregateRating snapshot type land.

No product-snapshot output from this module. Retail price / stock /
spec data comes from the Tier 1 ``bestbuy_api`` fetcher via the
Developer API. This split matches ``docs/ARCHITECTURE.md`` §11:
Developer API for stable fields, scraped PDP for reviews only.

**Coverage caveats:**

- ``published_at`` is ``None`` — JSON-LD Review objects on BestBuy
  PDPs do not carry ``datePublished``. The ``/site/reviews/name/<SKU>``
  surface does; that is the upgrade path.
- Review count caps at ~5 per fetch (PDP inlines that many).

Verified on two unrelated Alienware SKUs (6628371 + 6630638) which
returned identical JSON-LD shape.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

from scrapers_lib.core.attribution import attribute_url, bestbuy_review_id
from scrapers_lib.core.registry import register
from scrapers_lib.core.schemas import Anchor, Attribution, RawMention
from scrapers_lib.core.scheduler import BlockedError
from scrapers_lib.tier2.base import normalize_spec_value, parse_product_jsonld

logger = logging.getLogger(__name__)

SOURCE = "bestbuy"
SOURCE_REVIEWS = "bestbuy_reviews"

HOME_URL = "https://www.bestbuy.com/"

# Same 7-digit SKU shape as tier1/bestbuy_api — path ``/<SKU>.p`` or
# query ``?skuId=<SKU>``.
_SKU_PATH_RE = re.compile(r"/(\d{7})\.p(?:[/?#]|$)")

# Block markers anchored against Akamai's public block-page shape.
_BLOCK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"pardon our interruption", re.I),
    re.compile(r"<title>[^<]*access denied", re.I),
    re.compile(r"errors\.edgesuite", re.I),
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@register(SOURCE_REVIEWS)
def fetch_bestbuy_reviews(
    url: str,
    anchors: list[Anchor] | None = None,
    *,
    timeout: float = 30.0,
    warm: bool = True,
    impersonate: str = "chrome",
    **_: Any,
) -> list[RawMention]:
    """Fetch a BestBuy PDP; return one :class:`RawMention` per JSON-LD review.

    Uses curl_cffi with Chrome TLS impersonation forced onto HTTP/1.1
    (the combination that gets past BestBuy's Akamai HTTP/2 RST-stream
    gate). Warms against the homepage first so cookies settle.

    Attribution uses the URL-map gate: one of ``anchors`` must have
    ``source_urls["bestbuy"] == url`` (exact string match).
    """
    html = _fetch_pdp(url, timeout=timeout, warm=warm, impersonate=impersonate)
    return parse_bestbuy_pdp_reviews(html, url, anchors=anchors)


def parse_bestbuy_pdp_reviews(
    html: str,
    url: str,
    *,
    anchors: list[Anchor] | None = None,
) -> list[RawMention]:
    """Pure parse: PDP HTML → one :class:`RawMention` per JSON-LD review.

    Reviews without a non-empty ``reviewBody`` are skipped (the schema
    validator requires non-empty ``raw_text``).

    Raises :class:`BlockedError` if the response looks like an Akamai
    challenge and :class:`ValueError` if no anchor claims the URL.
    """
    if _looks_blocked(html):
        raise BlockedError(f"bestbuy: response appears blocked at {url}")

    attribution = attribute_url(url, SOURCE, anchors or [])
    if attribution is None:
        raise ValueError(
            f"no Anchor has source_urls[{SOURCE!r}] == {url!r}; "
            f"provide one that matches the fetched URL exactly"
        )

    sku = _extract_sku(url)

    products = parse_product_jsonld(html)
    if not products:
        logger.info("bestbuy: no JSON-LD Product block on %s", url)
        return []

    mentions: list[RawMention] = []
    for product in products:
        for review in _iter_reviews(product):
            m = _parse_review(
                review, sku=sku, product_url=url, attribution=attribution
            )
            if m is not None:
                mentions.append(m)
    return mentions


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _fetch_pdp(
    url: str,
    *,
    timeout: float,
    warm: bool,
    impersonate: str,
) -> str:
    """Warm against the homepage, then fetch the target PDP over HTTP/1.1.

    ``curl_cffi`` is imported lazily so ``import scrapers_lib`` stays
    cheap for consumers who do not touch Tier 3.
    """
    from curl_cffi import CurlHttpVersion, requests  # noqa: I001

    with requests.Session(
        impersonate=impersonate,
        http_version=CurlHttpVersion.V1_1,
    ) as s:
        if warm:
            try:
                s.get(HOME_URL, timeout=timeout)
                time.sleep(1)
            except Exception as e:  # pragma: no cover - warming best-effort
                logger.debug("bestbuy: warm failed: %s", e)

        r = s.get(url, timeout=timeout)
        r.raise_for_status()
        return r.text


def _looks_blocked(html: str) -> bool:
    return any(p.search(html) for p in _BLOCK_PATTERNS)


# ---------------------------------------------------------------------------
# URL → SKU
# ---------------------------------------------------------------------------


def _extract_sku(url: str) -> str:
    """Return the 7-digit SKU from a BestBuy PDP URL."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host and "bestbuy.com" not in host:
        raise ValueError(
            f"bestbuy: URL host {host!r} is not bestbuy.com; "
            f"pass a bestbuy.com PDP URL"
        )
    m = _SKU_PATH_RE.search(parsed.path + "/")
    if m is not None:
        return m.group(1)
    # Fall back to ?skuId=<SKU>.
    for part in parsed.query.split("&"):
        if part.startswith("skuId="):
            cand = part[len("skuId=") :]
            if cand.isdigit():
                return cand
    raise ValueError(
        f"bestbuy: URL {url!r} does not carry a SKU in /<SKU>.p "
        f"or ?skuId=<SKU> form"
    )


# ---------------------------------------------------------------------------
# JSON-LD review extractor (pure)
# ---------------------------------------------------------------------------


def _iter_reviews(product: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the ``review`` list from a JSON-LD Product, normalized to list shape."""
    raw = product.get("review")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def _parse_review(
    review: dict[str, Any],
    *,
    sku: str,
    product_url: str,
    attribution: Attribution,
) -> RawMention | None:
    """One JSON-LD Review object → :class:`RawMention`, or ``None`` on empty body."""
    body = normalize_spec_value(str(review.get("reviewBody") or ""))
    if not body:
        return None

    name = review.get("name")
    title = normalize_spec_value(str(name)) if name else None

    author_obj = review.get("author") or {}
    if isinstance(author_obj, dict):
        author = author_obj.get("name")
    elif isinstance(author_obj, str):
        author = author_obj
    else:
        author = None
    author = normalize_spec_value(str(author)) if author else None

    rating_obj = review.get("reviewRating") or {}
    rating_value: float | None = None
    if isinstance(rating_obj, dict):
        raw_rating = rating_obj.get("ratingValue")
        try:
            rating_value = float(raw_rating) if raw_rating is not None else None
        except (TypeError, ValueError):
            rating_value = None

    raw: dict[str, Any] = {
        "sku": sku,
        "product_url": product_url,
        "star_rating": rating_value,
    }

    return RawMention(
        mention_id=bestbuy_review_id(sku, author or "", body),
        source=SOURCE,
        source_type="post",
        source_url=f"https://www.bestbuy.com/site/reviews/name/{sku}",
        source_title=title,
        author=author,
        parent_id=sku,
        raw_text=body,
        attribution=attribution,
        raw=raw,
    )
