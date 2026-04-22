"""Amazon product + reviews fetcher.

Amazon's PDP (``amazon.com/dp/<ASIN>``) is — contrary to its Tier 3
reputation — reachable with plain httpx and a current Chrome UA. The
server-rendered HTML carries:

- The canonical product fields (title, price, rating, review count,
  availability, image) in well-known ``#productTitle`` / ``#acrPopover``
  / ``.priceToPay`` / ``#landingImage`` containers.
- A set of ``<table class="prodDetTable">`` key-value tables covering
  the "Product information" section (Hard-Drive Size, Graphics
  Coprocessor, RAM, ports, dimensions, warranty type, ...).
- The **top N reviews** embedded inline as
  ``<li data-hook="review" id="<R...>">`` blocks with rating, title,
  date, author, body, verified-purchase badge, and helpful-vote count.

The dedicated ``/product-reviews/<ASIN>/`` surface redirects to a
sign-in wall for unauthenticated clients, so deeper review pagination
is not reachable without credentials. The fetcher therefore caps review
coverage at whatever the PDP inlines (typically 8–10); the
``amazon_reviews`` source is registered separately from ``amazon``
so consumers can ask for product-only or reviews-only fetches.

Amazon stays in **Tier 3** despite plain-httpx reachability because:

- Repeated requests from one IP get rate-limited / challenged.
- Redesigns are frequent and the ``productDetails`` table variants
  shift without notice.
- Without auth, review coverage is partial by design.

Verified on two unrelated ASINs — Alienware 16 Area-51 (B0F8P6MRQT,
gaming, Dell-brand) and ASUS ROG Strix G16 2025 (B0DW1FVPK8, gaming,
different-brand) — which returned identical container shapes.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import httpx

from scrapers_lib.core.attribution import amazon_review_id, attribute_url
from scrapers_lib.core.registry import register
from scrapers_lib.core.schemas import (
    Anchor,
    Attribution,
    ProductSnapshot,
    RawMention,
)
from scrapers_lib.core.scheduler import BlockedError
from scrapers_lib.tier2.base import normalize_spec_value

logger = logging.getLogger(__name__)

SOURCE = "amazon"
SOURCE_REVIEWS = "amazon_reviews"

_ASIN_PATH_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?#]|$)")

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

# Tight block markers. Amazon PDPs legitimately embed the word
# "captcha" in analytics/referrer scripts and "something went wrong"
# in stock error-UI templates, so these must be anchored against
# block-page shape (title element, form action URL, prompt phrasing)
# rather than arbitrary occurrences.
_BLOCK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<title>\s*robot check", re.I),
    re.compile(r"automated access to amazon data", re.I),
    re.compile(r"<title>\s*sorry!?\s*something went wrong", re.I),
    re.compile(r'action="[^"]*/errors/validateCaptcha"', re.I),
    re.compile(r"type the characters you see in this image", re.I),
)

# "Reviewed in the United States on December 14, 2025"
# "Reviewed in Canada on December 14, 2025"
_REVIEW_DATE_RE = re.compile(
    r"Reviewed in\s+(?P<country>.+?)\s+on\s+(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})"
)

# "4.5 out of 5 stars" or "4 out of 5 stars"
_STAR_RATING_RE = re.compile(r"(\d+(?:\.\d+)?)\s*out of\s*5\s*stars?", re.I)

# "28 Reviews" / "28 ratings" / "1,234 global ratings"
_REVIEW_COUNT_RE = re.compile(r"([\d,]+)")

# "/gp/profile/amzn1.account.<ID>" — Amazon's opaque customer account ID.
_AUTHOR_ID_RE = re.compile(r"/gp/profile/(amzn1\.account\.[A-Z0-9]+)")

# "7 people found this helpful" / "One person found this helpful"
_HELPFUL_RE = re.compile(r"^(?:(\d+)|one)\s+", re.I)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@register(SOURCE)
def fetch_amazon_product(
    url: str,
    anchors: list[Anchor] | None = None,
    *,
    timeout: float = 30.0,
    **_: Any,
) -> list[ProductSnapshot]:
    """Fetch an Amazon PDP; return exactly one :class:`ProductSnapshot`.

    Plain httpx with a current Chrome UA. Raises :class:`BlockedError`
    if the response looks like a bot challenge.

    Attribution uses the URL-map gate: one of ``anchors`` must have
    ``source_urls["amazon"] == url`` (exact string match).
    """
    html = _fetch_html(url, timeout=timeout)
    return parse_amazon_product_page(html, url, anchors=anchors)


@register(SOURCE_REVIEWS)
def fetch_amazon_reviews(
    url: str,
    anchors: list[Anchor] | None = None,
    *,
    timeout: float = 30.0,
    **_: Any,
) -> list[RawMention]:
    """Fetch an Amazon PDP; return one :class:`RawMention` per inlined review.

    The PDP embeds the first ~8–10 reviews. Full pagination at
    ``/product-reviews/<ASIN>/`` is auth-gated and out of scope.
    """
    html = _fetch_html(url, timeout=timeout)
    return parse_amazon_reviews(html, url, anchors=anchors)


def parse_amazon_product_page(
    html: str,
    url: str,
    *,
    anchors: list[Anchor] | None = None,
) -> list[ProductSnapshot]:
    """Pure parse: PDP HTML → one :class:`ProductSnapshot`.

    Partial success: ``price``, ``rating``, ``image_url``,
    ``availability_text``, and individual spec rows may be absent
    without failing the whole parse. ``title`` is required by the
    schema; falls back to an ASIN-derived placeholder if Amazon's
    ``#productTitle`` is empty.

    Raises :class:`BlockedError` if the response looks like a challenge
    page and :class:`ValueError` if no anchor claims the URL.
    """
    if _looks_blocked(html):
        raise BlockedError(f"amazon: response appears blocked at {url}")

    attribution = attribute_url(url, SOURCE, anchors or [])
    if attribution is None:
        raise ValueError(
            f"no Anchor has source_urls[{SOURCE!r}] == {url!r}; "
            f"provide one that matches the fetched URL exactly"
        )

    asin = _extract_asin(url)

    from bs4 import BeautifulSoup  # noqa: I001

    soup = BeautifulSoup(html, "html.parser")

    title = _get_title(soup) or f"Amazon ASIN {asin}"
    brand = _get_brand(soup)
    price = _get_price(soup)
    rating = _get_rating(soup)
    review_count = _get_review_count(soup)
    image_url = _get_image_url(soup)
    availability_text = _get_availability(soup)
    in_stock = _derive_in_stock(availability_text)
    feature_bullets = _get_feature_bullets(soup)
    specs = _parse_prod_detail_tables(soup)

    config_summary: str | None = None
    if feature_bullets:
        config_summary = " / ".join(feature_bullets[:3])

    return [
        ProductSnapshot(
            source=SOURCE,
            source_id=asin,
            variant_key=asin,
            anchor_id=attribution.anchor_id,
            url=url,
            title=title,
            brand=brand,
            price=price,
            rating=rating,
            review_count=review_count,
            image_url=image_url,
            availability_text=availability_text,
            in_stock=in_stock,
            config_summary=config_summary,
            specs=specs,
            raw={
                "spec_source": "prodDetTable",
                "asin": asin,
                "feature_bullets": feature_bullets,
            },
        )
    ]


def parse_amazon_reviews(
    html: str,
    url: str,
    *,
    anchors: list[Anchor] | None = None,
) -> list[RawMention]:
    """Pure parse: PDP HTML → one :class:`RawMention` per inlined review.

    Reviews without a body (e.g. video-only reviews that Amazon renders
    with an empty ``[data-hook="review-body"]``) are skipped with a
    warning rather than emitted as empty mentions — :class:`RawMention`
    requires ``raw_text`` to be non-empty after stripping.

    Raises :class:`BlockedError` / :class:`ValueError` with the same
    semantics as :func:`parse_amazon_product_page`.
    """
    if _looks_blocked(html):
        raise BlockedError(f"amazon_reviews: response appears blocked at {url}")

    attribution = attribute_url(url, SOURCE, anchors or [])
    if attribution is None:
        raise ValueError(
            f"no Anchor has source_urls[{SOURCE!r}] == {url!r}; "
            f"provide one that matches the fetched URL exactly"
        )

    asin = _extract_asin(url)

    from bs4 import BeautifulSoup  # noqa: I001

    soup = BeautifulSoup(html, "html.parser")

    mentions: list[RawMention] = []
    for li in soup.select('li[data-hook="review"]'):
        m = _parse_review_li(li, asin=asin, product_url=url, attribution=attribution)
        if m is not None:
            mentions.append(m)

    if not mentions:
        logger.info("amazon_reviews: no inline reviews found on %s", url)

    return mentions


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _fetch_html(url: str, *, timeout: float) -> str:
    """Fetch the PDP HTML via plain httpx with a current Chrome UA."""
    headers = {
        "User-Agent": _DEFAULT_USER_AGENT,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    }
    r = httpx.get(url, headers=headers, follow_redirects=True, timeout=timeout)
    r.raise_for_status()
    return r.text


def _looks_blocked(html: str) -> bool:
    return any(p.search(html) for p in _BLOCK_PATTERNS)


# ---------------------------------------------------------------------------
# URL → ASIN
# ---------------------------------------------------------------------------


def _extract_asin(url: str) -> str:
    """Return the 10-char ASIN from a ``/dp/<ASIN>`` or ``/gp/product/<ASIN>`` URL."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host and "amazon." not in host:
        raise ValueError(
            f"amazon: URL host {host!r} is not an amazon domain; "
            f"pass an /dp/ or /gp/product/ URL"
        )
    m = _ASIN_PATH_RE.search(parsed.path + "/")
    if m is None:
        raise ValueError(
            f"amazon: URL path {parsed.path!r} does not match "
            f"/(dp|gp/product)/<ASIN>"
        )
    return m.group(1)


# ---------------------------------------------------------------------------
# Product-field extractors (pure)
# ---------------------------------------------------------------------------


def _get_title(soup: Any) -> str | None:
    el = soup.select_one("#productTitle")
    if el is None:
        return None
    return normalize_spec_value(el.get_text(" ", strip=True)) or None


def _get_brand(soup: Any) -> str | None:
    """Try Amazon's three brand surfaces in order.

    - ``#bylineInfo`` — standard PDP anchor, text "Visit the <Brand> Store".
    - ``#visitStoreDesktopUrl`` — premium-PDP (CE/Home) anchor in the same
      shape; used when bylineInfo is empty (Amazon hides one of the two to
      avoid double-rendering).
    - ``#brandLogoHiResByline`` — brand-logo image on premium PDPs; the
      ``alt`` attribute is the brand name directly.
    """
    for selector in ("#bylineInfo", "#visitStoreDesktopUrl"):
        el = soup.select_one(selector)
        if el is None:
            continue
        text = normalize_spec_value(el.get_text(" ", strip=True))
        if not text:
            continue
        for pat in (r"^Visit the (.+?) Store$", r"^Brand:\s*(.+)$"):
            m = re.match(pat, text, re.I)
            if m:
                return m.group(1).strip()
        return text

    img = soup.select_one("#brandLogoHiResByline")
    if img is not None:
        alt = (img.get("alt") or "").strip()
        if alt:
            return alt

    return None


def _get_price(soup: Any) -> Decimal | None:
    """Parse the "price to pay" — the headline offer price.

    Prefers the ``.priceToPay`` container; falls back to any ``#apex-
    pricetopay-accessibility-label``. Both carry the full ``$X,XXX.YY``
    string. Returns ``None`` if no price container is present (e.g.
    out-of-stock listings).
    """
    for selector in (".priceToPay .a-offscreen", "#apex-pricetopay-accessibility-label"):
        el = soup.select_one(selector)
        if el is None:
            continue
        text = el.get_text(" ", strip=True)
        dec = _parse_dollars(text)
        if dec is not None:
            return dec
    # Fallback: stitch .a-price-whole + .a-price-fraction inside .priceToPay
    whole = soup.select_one(".priceToPay .a-price-whole")
    fraction = soup.select_one(".priceToPay .a-price-fraction")
    if whole is not None:
        raw = whole.get_text("", strip=True).replace(",", "").rstrip(".")
        if fraction is not None:
            raw = f"{raw}.{fraction.get_text('', strip=True)}"
        try:
            return Decimal(raw)
        except InvalidOperation:
            return None
    return None


def _parse_dollars(text: str) -> Decimal | None:
    m = re.search(r"\$?\s*([\d,]+(?:\.\d{1,2})?)", text)
    if m is None:
        return None
    try:
        return Decimal(m.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def _get_rating(soup: Any) -> float | None:
    el = soup.select_one("#acrPopover")
    if el is None:
        return None
    text = el.get("title") or el.get_text(" ", strip=True)
    m = _STAR_RATING_RE.search(text or "")
    if m is None:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    if 0.0 <= v <= 5.0:
        return v
    return None


def _get_review_count(soup: Any) -> int | None:
    el = soup.select_one("#acrCustomerReviewText")
    if el is None:
        return None
    # aria-label is usually the cleanest ("28 Reviews"); inner text wraps
    # parens ("(28)").
    source = el.get("aria-label") or el.get_text(" ", strip=True)
    m = _REVIEW_COUNT_RE.search(source or "")
    if m is None:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _get_image_url(soup: Any) -> str | None:
    el = soup.select_one("#landingImage") or soup.select_one("#imgBlkFront")
    if el is None:
        return None
    # ``data-old-hires`` is the full-resolution variant when present;
    # ``src`` is the thumbnail fallback.
    return el.get("data-old-hires") or el.get("src") or None


def _get_availability(soup: Any) -> str | None:
    el = soup.select_one("#availability")
    if el is None:
        return None
    text = normalize_spec_value(el.get_text(" ", strip=True))
    return text or None


def _derive_in_stock(availability_text: str | None) -> bool | None:
    if not availability_text:
        return None
    low = availability_text.lower()
    if "in stock" in low or "only " in low:
        return True
    if (
        "currently unavailable" in low
        or "out of stock" in low
        or "temporarily out of stock" in low
    ):
        return False
    return None


def _get_feature_bullets(soup: Any) -> list[str]:
    container = soup.select_one("#feature-bullets")
    if container is None:
        return []
    bullets: list[str] = []
    for li in container.select("ul li:not(.aok-hidden) span.a-list-item"):
        text = normalize_spec_value(li.get_text(" ", strip=True))
        if text:
            bullets.append(text)
    return bullets


def _parse_prod_detail_tables(soup: Any) -> dict[str, str]:
    """Merge every ``<table class="prodDetTable">`` into one spec dict.

    Amazon partitions specs across multiple expanders on the PDP
    (Additional details / Memory / Battery / Ports & Slots / ...); each
    is its own table with the same shape. Later-encountered duplicate
    keys lose — first occurrence wins (consistent with
    ``base.parse_spec_table``).

    Warranty/feedback tables on the same page use the same class but
    contain free-prose ``<span>`` content rather than ``<tr><th><td>``
    rows; those yield zero pairs and are silently skipped.
    """
    specs: dict[str, str] = {}
    for table in soup.select("table.prodDetTable"):
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            key = normalize_spec_value(cells[0].get_text(" ", strip=True))
            value = normalize_spec_value(cells[-1].get_text(" ", strip=True))
            if not key or not value:
                continue
            if key in specs:
                continue
            specs[key] = value
    return specs


# ---------------------------------------------------------------------------
# Review extractor (pure)
# ---------------------------------------------------------------------------


def _parse_review_li(
    li: Any,
    *,
    asin: str,
    product_url: str,
    attribution: Attribution,
) -> RawMention | None:
    """One ``<li data-hook="review">`` → one :class:`RawMention`, or ``None``.

    Returns ``None`` for video-only or otherwise empty-body reviews
    (``raw_text`` must be non-empty per the schema validator).
    """
    review_id = (li.get("id") or "").strip()
    if not review_id:
        return None

    body_el = li.select_one('[data-hook="review-body"] span:not([class])')
    if body_el is None:
        # Fallback: any span inside the body container.
        body_el = li.select_one('[data-hook="review-body"]')
    body = normalize_spec_value(body_el.get_text(" ", strip=True)) if body_el else ""
    if not body:
        logger.info("amazon_reviews: skipping empty-body review %s", review_id)
        return None

    title_el = li.select_one('[data-hook="review-title"] span:not([class])')
    if title_el is None:
        # Older layout: title is inside [data-hook="review-title"] directly.
        title_el = li.select_one('[data-hook="review-title"]')
    title = normalize_spec_value(title_el.get_text(" ", strip=True)) if title_el else None

    rating_el = li.select_one('[data-hook="review-star-rating"] .a-icon-alt')
    rating_text = rating_el.get_text(" ", strip=True) if rating_el else ""
    rating_match = _STAR_RATING_RE.search(rating_text)
    rating = float(rating_match.group(1)) if rating_match else None

    author_el = li.select_one(".a-profile-name")
    author = (
        normalize_spec_value(author_el.get_text(" ", strip=True))
        if author_el is not None
        else None
    )
    author_link = li.select_one("a.a-profile")
    author_id: str | None = None
    if author_link is not None:
        m = _AUTHOR_ID_RE.search(author_link.get("href") or "")
        if m is not None:
            author_id = m.group(1)

    date_el = li.select_one('[data-hook="review-date"]')
    published_at: datetime | None = None
    if date_el is not None:
        date_text = date_el.get_text(" ", strip=True)
        dm = _REVIEW_DATE_RE.search(date_text)
        if dm is not None:
            try:
                published_at = datetime.strptime(
                    dm.group("date"), "%B %d, %Y"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                published_at = None

    verified = li.select_one('[data-hook="avp-badge"]') is not None

    helpful_el = li.select_one('[data-hook="helpful-vote-statement"]')
    helpful_count: int | None = None
    if helpful_el is not None:
        helpful_text = helpful_el.get_text(" ", strip=True)
        hm = _HELPFUL_RE.match(helpful_text)
        if hm is not None:
            helpful_count = int(hm.group(1)) if hm.group(1) else 1

    review_url = f"https://www.amazon.com/gp/customer-reviews/{review_id}/"

    raw: dict[str, Any] = {
        "asin": asin,
        "review_id": review_id,
        "product_url": product_url,
        "star_rating": rating,
        "verified_purchase": verified,
        "helpful_count": helpful_count,
        "author_id": author_id,
    }

    return RawMention(
        mention_id=amazon_review_id(asin, review_id),
        source=SOURCE,
        source_type="post",
        source_url=review_url,
        source_title=title,
        author=author,
        author_id=author_id,
        parent_id=asin,
        published_at=published_at,
        raw_text=body,
        attribution=attribution,
        raw=raw,
    )
