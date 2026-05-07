"""Acer product PDP fetcher.

Acer's PDP URL is the canonical spec surface: every laptop has a
``/pdp/<SKU>`` variant whose HTML is server-rendered with thirteen
``<table class="agw-table agw-table_techSpec">`` blocks. Each table
carries a ``<caption>`` (category name like "Processor" or
"Interfaces/Ports") and rows of the shape::

    <tr><th>Label</th><td>Value</td></tr>

There is no anti-bot gate on these pages — plain ``httpx`` with a
modern Chrome User-Agent returns 200 OK and the full HTML, including
the JSON-LD ``Product`` block carrying name / brand / image / SKU /
offer (price + availability). One :class:`ProductSnapshot` per
``/pdp/<SKU>`` URL; ``variant_key`` is ``None`` because the SKU itself
is the granularity.

URL shapes seen during recon (all match ``.*/pdp/<SKU>``):

- ``/us-en/predator/laptops/helios/helios-neo-16s-ai/pdp/NH.U0KAA.001``
  (Predator carries an extra ``/predator`` brand-line segment before
  ``/laptops``.)
- ``/us-en/laptops/nitro/nitro-v-16s-ai-amd/pdp/NH.U10AA.001`` (Nitro
  goes straight to ``/laptops/<line>``.)
- ``/us-en/laptops/aspire/aspire-7-intel/pdp/NH.Q81AA.001`` (Aspire
  same shape as Nitro.)

The validator is intentionally permissive on what comes before
``/pdp/<SKU>`` — any path ending in ``/pdp/<NH.alphanumeric.with.dots>``
is accepted, so future Acer line additions (Swift, ConceptD, TravelMate)
work without code changes.

Verified on Predator Helios Neo 16S AI + Acer Nitro V 16S AI AMD +
Aspire 7 Intel — three different brand-lines, same 13-table structure,
60+/55+ unique labels per page.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import httpx

from scrapers_lib.core.attribution import attribute_url
from scrapers_lib.core.registry import register
from scrapers_lib.core.schemas import Anchor, ProductSnapshot
from scrapers_lib.tier2.base import normalize_spec_value, parse_product_jsonld

logger = logging.getLogger(__name__)

SOURCE = "acer"

# Spec table marker class. Acer puts every techspec table at
# ``class="agw-table agw-table_techSpec"``; the second token is the
# distinguishing one — the bare ``agw-table`` class also appears on
# unrelated layout tables.
_TECHSPEC_CLASS = "agw-table_techSpec"

# Acer SKU pattern: prefix ``NH`` followed by dot-separated alphanumeric
# segments (e.g. ``NH.U0KAA.001``, ``NH.QGEAA.002``). Captured greedily
# to preserve any future Acer extensions to the format.
_SKU_RE = re.compile(r"^[A-Z]{2}\.[A-Z0-9]+\.[A-Z0-9]+$")

# Path validator: any path ending in ``/pdp/<SKU>`` (optional trailing
# slash). Everything before ``/pdp/`` is permissive — Acer's URL form
# varies between brand-lines (Predator carries a ``/predator/`` segment
# before ``/laptops``; Nitro/Aspire/Swift go straight to ``/laptops/``).
_PDP_PATH_RE = re.compile(r"^.+/pdp/([A-Z]{2}\.[A-Z0-9]+\.[A-Z0-9]+)/?$")

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

# Config-summary axes for Acer — match Demo-2 max-spec-comparison hints.
# Acer's labels are stable across the 13 categories, so substring
# matching against label keys works.
_CONFIG_SUMMARY_HINTS = (
    "Graphics Controller Model",
    "Standard Memory",
    "Total Solid State Drive Capacity",
    "Screen Size",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@register(SOURCE)
def fetch_acer_product(
    url: str,
    anchors: list[Anchor] | None = None,
    *,
    timeout: float = 30.0,
    **_: Any,
) -> list[ProductSnapshot]:
    """Fetch an Acer PDP; return a list containing one :class:`ProductSnapshot`.

    The input ``url`` must point at an Acer ``/pdp/<SKU>`` page
    (e.g. ``https://www.acer.com/us-en/laptops/nitro/nitro-v-16s-ai-amd/
    pdp/NH.U10AA.001``). Plain ``httpx`` is sufficient — Acer does not
    gate the PDP HTML.

    Attribution uses the URL-map gate: one of ``anchors`` must have
    ``source_urls["acer"] == url``. Raises :class:`ValueError` otherwise.

    Returns a list with exactly one snapshot on success. The list shape
    matches the registry contract shared with multi-tile fetchers
    (Dell/HP).
    """
    body = _fetch_pdp(url, timeout=timeout)
    return parse_acer_product_page(body, url, anchors=anchors)


def parse_acer_product_page(
    html: str,
    url: str,
    *,
    anchors: list[Anchor] | None = None,
) -> list[ProductSnapshot]:
    """Pure parse: PDP HTML → one :class:`ProductSnapshot`.

    Walks every ``<table class="agw-table_techSpec">`` block, capturing
    each ``<th>``/``<td>`` row verbatim into ``specs``. Labels are
    preserved exactly as they appear on the page (the downstream
    cleaner handles cross-vendor normalization). When the same label
    appears in multiple categories (defensive — not observed in recon),
    the first occurrence wins and later duplicates are logged at debug.

    JSON-LD ``Product`` enrichment supplies name / brand / image / price
    / currency / availability. The fetcher degrades gracefully when
    JSON-LD is absent — it falls back to the URL slug for ``title`` and
    fixes ``brand`` to ``"Acer"`` (sub-brand "predator" preserved under
    ``raw["jsonld_brand"]`` like the ASUS/ROG handling).

    Raises :class:`ValueError` on missing attribution or malformed URL.
    Raises :class:`RuntimeError` if no spec tables are found (structural
    contract break).
    """
    attribution = attribute_url(url, SOURCE, anchors or [])
    if attribution is None:
        raise ValueError(
            f"no Anchor has source_urls[{SOURCE!r}] == {url!r}; "
            f"provide one that matches the fetched URL exactly"
        )

    sku = _sku_from_url(url)

    from bs4 import BeautifulSoup  # noqa: I001

    soup = BeautifulSoup(html, "html.parser")
    specs = _flatten_spec_tables(soup)
    if not specs:
        raise RuntimeError(
            f"acer: no <table class*={_TECHSPEC_CLASS!r}> blocks "
            f"matched at {url}; page structure may have changed"
        )

    products_ld = parse_product_jsonld(html)
    shared = _jsonld_shared(products_ld[0] if products_ld else {})

    title = (shared.get("name") or sku).strip()

    return [
        ProductSnapshot(
            source=SOURCE,
            source_id=sku,
            variant_key=None,
            anchor_id=attribution.anchor_id,
            url=url,
            title=title,
            # Normalize to parent brand "Acer" for cross-vendor grouping
            # consistency. Predator JSON-LD declares brand="predator", a
            # sub-brand; preserve the original under raw.
            brand="Acer",
            config_summary=_config_summary(specs),
            price=shared.get("price"),
            list_price=shared.get("price"),
            currency=shared.get("currency") or "USD",
            in_stock=shared.get("in_stock"),
            availability_text=shared.get("availability_text"),
            image_url=shared.get("image"),
            specs=specs,
            raw={
                "spec_source": "ssr_table",
                "sku": sku,
                "jsonld_brand": shared.get("brand"),
            },
        )
    ]


# ---------------------------------------------------------------------------
# URL handling (pure)
# ---------------------------------------------------------------------------


def _sku_from_url(url: str) -> str:
    """Extract the ``/pdp/<SKU>`` segment from an Acer PDP URL.

    Validates host (``acer.com``) and path shape. Raises
    :class:`ValueError` on any mismatch — fail-fast so callers don't
    waste a network round-trip on an obviously wrong URL.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host and "acer.com" not in host:
        raise ValueError(
            f"acer: URL host {host!r} is not an acer.com domain; "
            f"pass an acer.com PDP URL ending in /pdp/<SKU>"
        )
    path = parsed.path.rstrip("/")
    m = _PDP_PATH_RE.match(path)
    if not m:
        raise ValueError(
            f"acer: URL path {path!r} does not end in "
            f"/pdp/<SKU> (expected SKU shape like NH.U0KAA.001)"
        )
    sku = m.group(1)
    if not _SKU_RE.match(sku):
        raise ValueError(
            f"acer: SKU {sku!r} from {url!r} does not match "
            f"the expected NH.<segment>.<segment> shape"
        )
    return sku


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _fetch_pdp(url: str, *, timeout: float) -> str:
    """Fetch the Acer PDP and return its HTML body.

    Validates URL shape up front. Plain ``httpx`` with a modern Chrome
    UA — Acer PDPs are not anti-bot-gated.
    """
    _sku_from_url(url)
    headers = {
        "User-Agent": _DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    r = httpx.get(url, headers=headers, follow_redirects=True, timeout=timeout)
    r.raise_for_status()
    return r.text


# ---------------------------------------------------------------------------
# Spec extraction (pure)
# ---------------------------------------------------------------------------


def _flatten_spec_tables(soup: Any) -> dict[str, str]:
    """Walk every techspec table; collect ``{label: value}`` verbatim.

    Each ``<table class="agw-table agw-table_techSpec">`` has a
    ``<caption>`` carrying the category name and rows of
    ``<tr><th>label</th><td>value</td></tr>``. Labels are preserved
    exactly as published — the downstream cleaner handles
    normalization.

    On duplicate labels across categories (defensive — not observed in
    recon), first occurrence wins and the duplicate is logged at
    debug level.
    """
    out: dict[str, str] = {}
    for table in _find_techspec_tables(soup):
        for tr in table.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if th is None or td is None:
                continue
            label = normalize_spec_value(th.get_text(" ", strip=True))
            value = normalize_spec_value(td.get_text(" ", strip=True))
            if not label or not value:
                continue
            if label in out:
                logger.debug(
                    "acer: duplicate label %r across spec tables; "
                    "keeping first value",
                    label,
                )
                continue
            out[label] = value
    return out


def _find_techspec_tables(soup: Any) -> list[Any]:
    """Find every ``<table>`` whose class list contains ``agw-table_techSpec``."""
    result: list[Any] = []
    for table in soup.find_all("table"):
        classes = table.get("class") or []
        if _TECHSPEC_CLASS in classes:
            result.append(table)
    return result


def _table_categories(soup: Any) -> list[str]:
    """Return the ``<caption>`` text of every techspec table, in document order.

    Exposed for callers (and tests) that want to verify how many
    categories were captured without re-walking the DOM.
    """
    out: list[str] = []
    for table in _find_techspec_tables(soup):
        cap = table.find("caption")
        if cap is None:
            continue
        text = normalize_spec_value(cap.get_text(" ", strip=True))
        if text:
            out.append(text)
    return out


# ---------------------------------------------------------------------------
# JSON-LD enrichment (pure)
# ---------------------------------------------------------------------------


def _jsonld_shared(p: dict[str, Any]) -> dict[str, Any]:
    """Pull name / brand / image / price / availability from a JSON-LD Product.

    Brand may arrive nested (``{"@type": "Brand", "name": "predator"}``)
    or as a string. Image may be a single URL or a list. Offers may
    carry ``price`` / ``priceCurrency`` / ``availability``; an explicit
    ``"price": "0"`` is treated as missing because Acer ships out-of-
    stock SKUs with a placeholder zero price.
    """
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
    if isinstance(offers, dict):
        price = _coerce_decimal(offers.get("price"))
        # Treat an explicit zero as missing — Acer uses "0" as a placeholder
        # for unpriced / out-of-stock listings.
        if price is not None and price > 0:
            out["price"] = price
        currency = offers.get("priceCurrency")
        if currency:
            out["currency"] = currency
        availability = offers.get("availability") or ""
        if availability:
            out["availability_text"] = availability
            low = availability.lower()
            # schema.org Availability tokens; Acer uses the bare names
            # ("InStock", "OutOfStock") plus the schema.org URL form.
            if "outofstock" in low or "discontinued" in low:
                out["in_stock"] = False
            elif "instock" in low or "preorder" in low or "limited" in low:
                out["in_stock"] = True

    return out


def _coerce_decimal(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Config summary (pure)
# ---------------------------------------------------------------------------


def _config_summary(specs: dict[str, str]) -> str | None:
    """Short ``GPU / RAM / Storage / Display`` summary for human eyeballing.

    Acer's spec labels are stable enough that exact-match is reliable;
    the hint list above is the canonical Acer label set for these
    axes. Returns ``None`` when none of the hints match.
    """
    parts: list[str] = []
    for hint in _CONFIG_SUMMARY_HINTS:
        if hint in specs:
            val = specs[hint].strip()
            if val:
                parts.append(val)
    return " / ".join(parts) if parts else None
