"""ASUS ROG product spec page fetcher.

ASUS publishes authoritative spec sheets at
``rog.asus.com/laptops/<line>/<model>/spec/`` (and returns the same content
without the trailing ``/spec/``). The page is ~1 MB of SSR'd HTML with a
rich section of ``<h2>`` headings — typically 20+ — each followed by a
sibling ``<div>`` containing one child per ship-able SKU variant. ASUS's
internal CSS-module naming (``ProductSpec__productSpecItemTitle__<hash>``
on h2s, ``ProductSpec__rowItem__<hash>`` on variant rows) is the stable
contract we match against via substring rather than exact class.

Unlike HP, ROG's spec page ships all the "Tech Specs" categories
(Dimensions, Weight, I/O Ports, Power Supply, Expansion Slots, Security,
Wireless band & version) in the initial httpx response — no JavaScript
required. Comparable coverage to Lenovo PSREF, different DOM shape.

``shop.asus.com`` is gated by DataDome and is NOT the target of this
fetcher — that surface would need professional anti-bot bypass. ROG's
marketing spec page carries no prices; like Lenovo PSREF this fetcher
emits no ``price`` / ``list_price`` / ``in_stock`` fields.

Granularity is per-model-family (one :class:`ProductSnapshot` per URL).
Multi-SKU option alternatives for every spec are embedded inside the
spec value as newline-joined rows, deduplicated in first-occurrence
order so 22 identical "Core Ultra 9 275HX" entries (repeated once per
SKU permutation) collapse to a single line.
"""

from __future__ import annotations

import html as html_module
import json
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import httpx

from scrapers_lib.core.attribution import attribute_url
from scrapers_lib.core.registry import register
from scrapers_lib.core.schemas import Anchor, ProductSnapshot
from scrapers_lib.tier2._base import normalize_spec_value, parse_product_jsonld

logger = logging.getLogger(__name__)

SOURCE = "asus"

# CSS-module class-name prefixes — ASUS recompiles hashes on every build, so
# we match on the literal prefix rather than exact token.
_SPEC_TITLE_CLASS_PREFIX = "ProductSpec__productSpecItemTitle__"
_SPEC_ROW_ITEM_CLASS_PREFIX = "ProductSpec__rowItem__"

# ROG product page URL shape: /laptops/<line>/<model>/ (optionally + spec/).
_PRODUCT_PATH_RE = re.compile(
    r"^/laptops/[a-z0-9-]+/[a-z0-9-]+(?:/spec)?/?$"
)

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

# Patterns for trimming whitespace around ® / ™. BS4 pulls those symbols
# out of their inline containers with stray whitespace; re-join cleanly.
_SYMBOL_LEADING_SPACE = re.compile(r"\s+([®™])")
_SYMBOL_TRAILING_SPACE = re.compile(r"([®™])\s+")

# Config-summary axes for ASUS — same Demo-2 max-spec-comparison set.
# ASUS category names are stable enough that substring matching works.
_CONFIG_SUMMARY_HINTS = ("Graphics", "Memory", "Storage", "Display")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@register(SOURCE)
def fetch_asus_product(
    url: str,
    anchors: list[Anchor] | None = None,
    *,
    timeout: float = 30.0,
    **_: Any,
) -> list[ProductSnapshot]:
    """Fetch a ROG spec page; return a list containing one :class:`ProductSnapshot`.

    ``url`` may be either ``.../spec/`` (the direct spec surface) or the
    product-root form ``.../<model>/`` — ASUS serves the same content at
    both, and the fetcher does not rewrite the URL so attribution stays
    under the caller's control.

    Raises :class:`ValueError` on unrecognized URL shape or when no
    anchor in ``anchors`` has ``source_urls["asus"] == url``.
    Raises :class:`RuntimeError` if no recognizable ``<h2>`` spec titles
    are found in the response (structural contract break).

    Returns a list with exactly one snapshot on success. The list shape
    matches the registry contract shared with per-SKU fetchers (Dell/HP).
    """
    body = _fetch_spec_page(url, timeout=timeout)
    return parse_asus_product_page(body, url, anchors=anchors)


def parse_asus_product_page(
    html: str,
    url: str,
    *,
    anchors: list[Anchor] | None = None,
) -> list[ProductSnapshot]:
    """Pure parse: ROG spec-page HTML → one :class:`ProductSnapshot`.

    Flattens every ``<h2>`` spec block into ``specs[<h2 text>]``. Each
    value is the newline-joined, de-duplicated sequence of variant-row
    texts (preserving first-occurrence order). HTML entities decoded,
    whitespace around ``®`` / ``™`` tightened.
    """
    attribution = attribute_url(url, SOURCE, anchors or [])
    if attribution is None:
        raise ValueError(
            f"no Anchor has source_urls[{SOURCE!r}] == {url!r}; "
            f"provide one that matches the fetched URL exactly"
        )

    from bs4 import BeautifulSoup  # noqa: I001

    soup = BeautifulSoup(html, "html.parser")

    specs = _flatten_spec_sections(soup)
    if not specs:
        raise RuntimeError(
            f"asus: no <h2 class*={_SPEC_TITLE_CLASS_PREFIX!r}>...</h2> "
            f"blocks matched at {url}; page structure may have changed"
        )

    products_ld = parse_product_jsonld(html)
    shared = _jsonld_shared(products_ld[0] if products_ld else {})

    source_id = _source_id_from_url(url)
    title = (shared.get("name") or source_id.replace("-", " ")).strip()

    return [
        ProductSnapshot(
            source=SOURCE,
            source_id=source_id,
            variant_key=None,
            anchor_id=attribution.anchor_id,
            url=url,
            title=title,
            # Fix brand to the parent manufacturer for cross-vendor grouping
            # consistency (Dell/HP/Lenovo all report parent, not sub-brand).
            # JSON-LD on ROG pages advertises brand="ROG" — preserved under raw.
            brand="ASUS",
            config_summary=_config_summary(specs),
            price=shared.get("price_low"),
            list_price=shared.get("price_high") or shared.get("price_low"),
            currency=shared.get("currency") or "USD",
            image_url=shared.get("image"),
            specs=specs,
            raw={
                "spec_source": "rog_spec_page",
                "product_slug": source_id,
                "jsonld_brand": shared.get("brand"),
            },
        )
    ]


# ---------------------------------------------------------------------------
# URL handling
# ---------------------------------------------------------------------------


def _source_id_from_url(url: str) -> str:
    """Model slug from ``/laptops/<line>/<model>[/spec]/`` URL."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host and "asus.com" not in host:
        raise ValueError(
            f"asus: URL host {host!r} is not an asus.com domain; "
            f"pass a rog.asus.com/laptops/<line>/<model>/ URL"
        )
    path = parsed.path.rstrip("/")
    if not _PRODUCT_PATH_RE.match(path):
        raise ValueError(
            f"asus: URL path {path!r} does not match "
            f"/laptops/<line>/<model>[/spec]"
        )
    # Drop trailing /spec if present; the preceding segment is the slug.
    parts = path.split("/")
    if parts[-1] == "spec":
        return parts[-2]
    return parts[-1]


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _fetch_spec_page(url: str, *, timeout: float) -> str:
    """Fetch the ROG spec-page URL and return its HTML body."""
    # Validate URL up-front so network isn't wasted on obvious mistakes.
    _source_id_from_url(url)
    headers = {
        "User-Agent": _DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    r = httpx.get(url, headers=headers, follow_redirects=True, timeout=timeout)
    r.raise_for_status()
    return r.text


# ---------------------------------------------------------------------------
# Spec extraction (pure)
# ---------------------------------------------------------------------------


def _flatten_spec_sections(soup: Any) -> dict[str, str]:
    """Walk every recognized h2 spec title; collect deduped variant rows.

    Returns ``{spec_name: "variant1\\nvariant2\\n..."}`` — unique-in-order.
    """
    out: dict[str, str] = {}
    for h2 in _find_spec_title_h2s(soup):
        name = normalize_spec_value(
            html_module.unescape(h2.get_text(" ", strip=True))
        )
        if not name:
            continue
        val_div = h2.find_next_sibling("div")
        if val_div is None:
            continue
        variants = _collect_variant_rows(val_div)
        if variants and name not in out:
            out[name] = "\n".join(variants)
    return out


def _find_spec_title_h2s(soup: Any) -> list[Any]:
    """Find every ``<h2>`` whose class contains the spec-title prefix."""
    result: list[Any] = []
    for h2 in soup.find_all("h2"):
        classes = h2.get("class") or []
        if any(c.startswith(_SPEC_TITLE_CLASS_PREFIX) for c in classes):
            result.append(h2)
    return result


def _collect_variant_rows(val_div: Any) -> list[str]:
    """One spec's sibling-div → ordered unique variant-text rows.

    Each direct child ``<div>`` carrying a ``ProductSpec__rowItem__*`` class
    is one SKU variant's text. Duplicates (ASUS repeats identical rows
    once per SKU permutation) are collapsed to their first occurrence.
    If no class-matched children are found, falls back to all direct
    ``<div>`` children — defensive against CSS-module hash changes.
    """
    variants: list[str] = []
    seen: set[str] = set()

    class_matched = [
        ch
        for ch in val_div.find_all("div", recursive=False)
        if any(
            c.startswith(_SPEC_ROW_ITEM_CLASS_PREFIX) for c in (ch.get("class") or [])
        )
    ]
    children = class_matched or val_div.find_all("div", recursive=False)

    for child in children:
        text = _clean_variant_text(child)
        if not text or text in seen:
            continue
        seen.add(text)
        variants.append(text)

    # Last-resort fallback: no child divs at all → take the whole val_div
    # as a single value.
    if not variants:
        text = _clean_variant_text(val_div)
        if text:
            variants.append(text)

    return variants


def _clean_variant_text(el: Any) -> str:
    """Extract and normalize one variant row's text.

    BeautifulSoup splits ``<sup>®</sup>`` / ``<sup>™</sup>`` away from
    their surrounding words, so ``get_text(' ', strip=True)`` produces
    ``"Intel ® Core™"``. We tighten those back to ``"Intel® Core™"``.
    Remaining whitespace runs are collapsed.
    """
    text = html_module.unescape(el.get_text(" ", strip=True))
    text = _SYMBOL_LEADING_SPACE.sub(r"\1", text)
    text = _SYMBOL_TRAILING_SPACE.sub(r"\1 ", text)
    return normalize_spec_value(text)


# ---------------------------------------------------------------------------
# Enrichment helpers (pure)
# ---------------------------------------------------------------------------


def _jsonld_shared(p: dict[str, Any]) -> dict[str, Any]:
    """Pull name / brand / image / price bounds from a JSON-LD Product."""
    out: dict[str, Any] = {"name": p.get("name")}

    brand = p.get("brand")
    if isinstance(brand, dict):
        out["brand"] = brand.get("name")
    elif isinstance(brand, str):
        out["brand"] = brand

    image = p.get("image")
    if isinstance(image, str):
        out["image"] = image
    elif isinstance(image, list) and image and isinstance(image[0], str):
        out["image"] = image[0]

    offers = p.get("offers")
    low: Decimal | None = None
    high: Decimal | None = None
    currency: str | None = None
    if isinstance(offers, dict):
        low = _coerce_decimal(
            offers.get("lowPrice") or offers.get("price")
        )
        high = _coerce_decimal(
            offers.get("highPrice") or offers.get("price")
        )
        currency = offers.get("priceCurrency")
    elif isinstance(offers, list):
        prices = [
            p
            for p in (_coerce_decimal(o.get("price")) for o in offers if isinstance(o, dict))
            if p is not None
        ]
        if prices:
            low, high = min(prices), max(prices)
        for o in offers:
            if isinstance(o, dict) and o.get("priceCurrency"):
                currency = o["priceCurrency"]
                break
    if low is not None:
        out["price_low"] = low
    if high is not None:
        out["price_high"] = high
    if currency:
        out["currency"] = currency

    return out


def _coerce_decimal(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _config_summary(specs: dict[str, str]) -> str | None:
    """Short ``GPU / RAM / Storage / Display`` summary from the first variant.

    Multi-variant spec values have the top-spec option typically on line 0
    (ASUS lists the highest SKU first on ROG Strix pages); if that
    ordering shifts, the summary becomes the first variant rather than
    the top variant — still useful.
    """
    parts: list[str] = []
    seen: set[str] = set()
    for hint in _CONFIG_SUMMARY_HINTS:
        for key, val in specs.items():
            if hint in key and key not in seen:
                first_line = val.split("\n", 1)[0].strip()
                if first_line:
                    # Keep the summary readable — truncate long CPU+GPU prose.
                    parts.append(first_line[:120])
                    seen.add(key)
                    break
    return " / ".join(parts) if parts else None
