"""BestBuy review fetcher (reviews only — product data lives in ``tier1/bestbuy_api``).

BestBuy's retail surface at ``bestbuy.com/site/...`` is Akamai-
protected at both the TLS and HTTP/2 layers: plain httpx drops with
``RemoteProtocolError``, stealth Playwright fails at ``net::
ERR_HTTP2_PROTOCOL_ERROR`` at navigation, and curl_cffi with Chrome
TLS impersonation still gets ``HTTP/2 INTERNAL_ERROR`` RST_STREAM on
any request to ``/site/...`` — but **curl_cffi with Chrome
impersonation on HTTP/1.1** goes through cleanly on both the PDP
(``/site/<slug>/<SKU>.p``) and the dedicated reviews surface
(``/site/reviews/name/<SKU>?page=N``).

**Two modes** (v1.1.0):

1. **Default (``paginate=False``)** — fetches the PDP and parses the
   inline ``<script type="application/ld+json">`` blocks for
   ``@type: Product`` → ``review[*]``. Returns ~5 reviews, no
   ``published_at`` (PDP JSON-LD does not carry ``datePublished``).
   Cheap: one HTTP request.
2. **Pagination (``paginate=True``)** — walks
   ``bestbuy.com/site/reviews/name/<SKU>?page=1..N``. Each page is
   SSR'd with 20 ``<li class="review-item">`` containers; each
   container holds its own ``<script type="application/ld+json">``
   ``@type: Review`` block (body / title / author / rating) plus a
   ``<time class="submission-date" title="Mon DD, YYYY H:MM AM/PM">``
   element for the timestamp (JSON-LD has no ``datePublished`` on
   either surface — dates live in the DOM). Pagination continues
   while a ``<link rel="next">`` is present; walker also stops
   defensively on an empty review page. ``max_pages`` caps the walk
   for busy SKUs; ``page_delay_seconds`` paces politely.

No product-snapshot output from this module. Retail price / stock /
spec data comes from the Tier 1 ``bestbuy_api`` fetcher via the
Developer API (indefinitely dormant without a credential; see
``project_bestbuy_api_dormant`` memory).

Verified in Wave 2c on two unrelated Alienware SKUs (6628371 +
6630638) for the PDP path; Wave 2d recon (2026-04-22) confirmed the
pagination path on SKU 6628371 across 3 captured pages.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
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
REVIEWS_URL_TEMPLATE = "https://www.bestbuy.com/site/reviews/name/{sku}?page={page}"

# BestBuy renders timestamps as ``Mon DD, YYYY H:MM AM/PM`` in each review's
# ``<time class="submission-date" title="...">`` attribute. No explicit
# timezone is given; stored as UTC-naive promoted to UTC-aware to keep
# downstream processing free of mixed naive/aware datetimes.
_BESTBUY_DATE_FORMAT = "%b %d, %Y %I:%M %p"

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
    paginate: bool = False,
    max_pages: int | None = None,
    page_delay_seconds: float = 3.0,
    **_: Any,
) -> list[RawMention]:
    """Fetch BestBuy reviews for a PDP URL; return one :class:`RawMention` per review.

    Two modes:

    - ``paginate=False`` (default, unchanged from v1.0.0): fetches the
      PDP itself and parses the inline JSON-LD ``Product.review[*]``
      list. Returns ~5 reviews with ``published_at=None`` (the PDP's
      JSON-LD does not carry ``datePublished``).
    - ``paginate=True``: walks ``bestbuy.com/site/reviews/name/<SKU>?
      page=1..N`` until a page has no reviews or no next-link.
      Returns every review across every page with ``published_at``
      populated from the per-review ``<time title="...">`` element.
      Use ``max_pages`` to cap the walk for busy SKUs;
      ``page_delay_seconds`` paces between page fetches (default 3 s
      matches the Wave 2d recon probe's polite pace).

    Both modes use curl_cffi with Chrome TLS impersonation forced onto
    HTTP/1.1 (the combination that gets past BestBuy's Akamai HTTP/2
    RST-stream gate). Warms against the homepage first so cookies settle.

    Attribution uses the URL-map gate: one of ``anchors`` must have
    ``source_urls["bestbuy"] == url`` (exact string match). ``url``
    is always the PDP URL; in paginate mode the fetcher derives the
    reviews-surface URL internally from the SKU.
    """
    if not paginate:
        html = _fetch_pdp(url, timeout=timeout, warm=warm, impersonate=impersonate)
        return parse_bestbuy_pdp_reviews(html, url, anchors=anchors)

    # Paginate mode: walk the reviews-page surface.
    sku = _extract_sku(url)
    attribution = attribute_url(url, SOURCE, anchors or [])
    if attribution is None:
        raise ValueError(
            f"no Anchor has source_urls[{SOURCE!r}] == {url!r}; "
            f"provide one that matches the fetched URL exactly"
        )

    mentions: list[RawMention] = []
    for page_html, page_num in _iter_reviews_pages(
        sku,
        timeout=timeout,
        warm=warm,
        impersonate=impersonate,
        max_pages=max_pages,
        page_delay_seconds=page_delay_seconds,
    ):
        page_mentions = parse_bestbuy_reviews_page(
            page_html,
            product_url=url,
            sku=sku,
            attribution=attribution,
        )
        if not page_mentions:
            logger.info(
                "bestbuy: page %d for SKU %s had zero reviews; ending walk",
                page_num,
                sku,
            )
            break
        mentions.extend(page_mentions)
        if not _has_next_reviews_page(page_html):
            logger.info(
                "bestbuy: page %d for SKU %s had no rel=next; ending walk",
                page_num,
                sku,
            )
            break
    return mentions


def parse_bestbuy_reviews_page(
    html: str,
    *,
    product_url: str,
    sku: str,
    attribution: Attribution,
) -> list[RawMention]:
    """Pure parse: one reviews-page HTML → :class:`RawMention` per review.

    Walks every ``<li class="review-item">`` container on the page.
    For each container:

    - Extracts the embedded ``<script type="application/ld+json">``
      ``@type: Review`` block for ``reviewBody``, ``reviewRating.
      ratingValue``, ``author.name``, ``name`` (the review title).
    - Extracts the ``<time class="submission-date" title="...">``
      ``title`` attribute for the timestamp (format
      ``"Mon DD, YYYY H:MM AM/PM"``; no explicit timezone, stored as
      UTC-aware).
    - Extracts the ``<button class="helpfulness-button" aria-label=
      "... N people/person found this review to be helpful.">`` count.
    - Detects "Verified Purchase" badge presence and "Owned for X"
      ownership-duration text.

    Raises :class:`BlockedError` if the response looks like an Akamai
    challenge. Reviews with an empty ``reviewBody`` are skipped (the
    schema validator requires non-empty ``raw_text``).
    """
    if _looks_blocked(html):
        raise BlockedError(f"bestbuy: reviews page for SKU {sku} appears blocked")

    soup = _get_soup(html)
    mentions: list[RawMention] = []

    for li in soup.select("li.review-item"):
        mention = _parse_review_item(
            li,
            sku=sku,
            product_url=product_url,
            attribution=attribution,
        )
        if mention is not None:
            mentions.append(mention)
    return mentions


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


def _iter_reviews_pages(
    sku: str,
    *,
    timeout: float,
    warm: bool,
    impersonate: str,
    max_pages: int | None,
    page_delay_seconds: float,
):
    """Walk ``/site/reviews/name/<SKU>?page=1..N``; yield ``(html, page)`` per page.

    Stops at the first non-200 response, at ``max_pages``, or when the
    caller's outer loop breaks (e.g. no more reviews / no rel=next).
    Sleeps ``page_delay_seconds`` between page fetches after page 1.

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

        page = 1
        while True:
            if max_pages is not None and page > max_pages:
                logger.info(
                    "bestbuy: max_pages=%d reached for SKU %s", max_pages, sku
                )
                return

            url = REVIEWS_URL_TEMPLATE.format(sku=sku, page=page)
            r = s.get(url, timeout=timeout)
            if r.status_code != 200:
                logger.info(
                    "bestbuy: page %d for SKU %s returned %d; ending walk",
                    page,
                    sku,
                    r.status_code,
                )
                return
            yield r.text, page
            page += 1
            time.sleep(page_delay_seconds)


def _has_next_reviews_page(html: str) -> bool:
    """Return True if the reviews page has a ``rel="next"`` link."""
    return bool(re.search(r'<link[^>]+rel="next"', html, re.I))


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


def _get_soup(html: str) -> Any:
    """Return a BeautifulSoup tree parsed with the stdlib ``html.parser``.

    Lazy import keeps ``import scrapers_lib`` cheap for consumers that
    never touch Tier 3.
    """
    from bs4 import BeautifulSoup  # noqa: I001

    return BeautifulSoup(html, "html.parser")


def _parse_review_item(
    li: Any,
    *,
    sku: str,
    product_url: str,
    attribution: Attribution,
) -> RawMention | None:
    """One ``<li class="review-item">`` → :class:`RawMention`, or ``None`` on empty body."""
    # Embedded JSON-LD carries the structured review fields.
    ld_script = li.find("script", attrs={"type": "application/ld+json"})
    if ld_script is None:
        return None
    try:
        ld = json.loads(ld_script.string or ld_script.get_text() or "")
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(ld, dict) or ld.get("@type") != "Review":
        return None

    body = normalize_spec_value(str(ld.get("reviewBody") or ""))
    if not body:
        return None

    title_raw = ld.get("name")
    title = normalize_spec_value(str(title_raw)) if title_raw else None

    author_obj = ld.get("author") or {}
    if isinstance(author_obj, dict):
        author = author_obj.get("name")
    elif isinstance(author_obj, str):
        author = author_obj
    else:
        author = None
    author = normalize_spec_value(str(author)) if author else None

    rating_obj = ld.get("reviewRating") or {}
    rating_value: float | None = None
    if isinstance(rating_obj, dict):
        raw_rating = rating_obj.get("ratingValue")
        try:
            rating_value = float(raw_rating) if raw_rating is not None else None
        except (TypeError, ValueError):
            rating_value = None

    # DOM-sourced fields.
    time_el = li.find("time", class_="submission-date")
    published_at = _parse_bestbuy_date(time_el.get("title")) if time_el else None

    helpful_count = _extract_helpful_count(li)
    verified_purchase = _extract_verified_purchase(li)
    ownership_duration = _extract_ownership_duration(li)

    raw: dict[str, Any] = {
        "sku": sku,
        "product_url": product_url,
        "star_rating": rating_value,
        "verified_purchase": verified_purchase,
        "helpful_count": helpful_count,
    }
    if ownership_duration:
        raw["ownership_duration"] = ownership_duration

    return RawMention(
        mention_id=bestbuy_review_id(sku, author or "", body),
        source=SOURCE,
        source_type="post",
        source_url=f"https://www.bestbuy.com/site/reviews/name/{sku}",
        source_title=title,
        author=author,
        parent_id=sku,
        published_at=published_at,
        raw_text=body,
        attribution=attribution,
        raw=raw,
    )


def _parse_bestbuy_date(title_attr: str | None) -> datetime | None:
    """Parse ``"Mon DD, YYYY H:MM AM/PM"`` → timezone-aware UTC datetime.

    BestBuy does not declare a timezone; treating the naive value as
    UTC keeps the library free of mixed naive/aware datetimes without
    pretending to know a timezone we don't have.
    """
    if not title_attr:
        return None
    try:
        naive = datetime.strptime(title_attr.strip(), _BESTBUY_DATE_FORMAT)
    except ValueError:
        logger.debug("bestbuy: could not parse review date %r", title_attr)
        return None
    return naive.replace(tzinfo=timezone.utc)


_HELPFUL_RE = re.compile(r"(\d+)\s+(?:person|people)\s+found", re.I)


def _extract_helpful_count(li: Any) -> int | None:
    """Parse the helpfulness button's aria-label for its vote count."""
    button = li.find("button", class_="helpfulness-button")
    if button is None:
        return None
    label = button.get("aria-label") or ""
    m = _HELPFUL_RE.search(label)
    return int(m.group(1)) if m else None


def _extract_verified_purchase(li: Any) -> bool:
    """True if a Verified Purchase badge is present anywhere in the ``<li>``."""
    for btn in li.find_all("button"):
        if btn.get("data-track") == "Verified Purchase Badge":
            return True
    return False


_OWNERSHIP_RE = re.compile(r"Owned for\s+([^<.]+?)\s+when reviewed", re.I)


def _extract_ownership_duration(li: Any) -> str | None:
    """Extract the ``Owned for X when reviewed`` phrase if present."""
    text = li.get_text(" ", strip=True)
    m = _OWNERSHIP_RE.search(text)
    return m.group(1).strip() if m else None


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
