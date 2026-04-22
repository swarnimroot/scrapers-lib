"""BestBuy Developer API fetcher — product data, prices, availability.

The BestBuy Developer API (``api.bestbuy.com``) exposes the full retail
catalog over a documented JSON endpoint at
``/v1/products/<SKU>.json?apiKey=<key>``. It is stable, documented, and
rate-limited at 5 requests per second by default — a textbook Tier 1
source.

The fetcher takes a BestBuy *website* product URL (the form consumers
naturally land on, e.g.
``bestbuy.com/site/<slug>/<sku>.p?skuId=<sku>``), extracts the SKU
from the path, and calls the API's per-SKU lookup endpoint. The API
response carries:

- Price fields: ``regularPrice``, ``salePrice``, ``onSale``,
  ``dollarSavings``, ``percentSavings``.
- Availability: ``onlineAvailability``, ``inStoreAvailability``,
  ``orderable``.
- Identity: ``sku``, ``modelNumber``, ``manufacturer``, ``name``.
- Ratings: ``customerReviewAverage`` (string), ``customerReviewCount``.
- Images: ``largeFrontImage`` / ``image`` / ``thumbnailImage``.
- Specs: ``details`` — a flat list of ``{name, value}`` pairs covering
  the PDP's "Specifications" section.
- Category: ``categoryPath`` — a nested breadcrumb (last element is
  the leaf category).

No reviews — the Developer API does not expose user reviews; those
come from ``tier3/bestbuy.py``.

Credential: ``BESTBUY_API_KEY`` in the environment (loaded via
``python-dotenv`` by the consumer, per ``docs/ARCHITECTURE.md`` §15).
Missing key raises :class:`RuntimeError` rather than returning an
empty or synthetic snapshot — silent failures are banned.

Verified contract shape against BestBuy's public documentation at
bestbuyapis.github.io; live integration test gated behind the API key
confirms the fixture shape against the real API when a key is
available.
"""

from __future__ import annotations

import json
import logging
import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from scrapers_lib.core.attribution import attribute_url
from scrapers_lib.core.registry import register
from scrapers_lib.core.schemas import Anchor, ProductSnapshot
from scrapers_lib.tier2._base import normalize_spec_value

logger = logging.getLogger(__name__)

SOURCE = "bestbuy_api"
API_BASE = "https://api.bestbuy.com/v1/products"
API_KEY_ENV = "BESTBUY_API_KEY"

# BestBuy product URL path ends with ``/<SKU>.p`` where SKU is 7 digits.
# The ``?skuId=<SKU>`` query form also appears; we accept either.
_SKU_PATH_RE = re.compile(r"/(\d{7})\.p(?:[/?#]|$)")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@register(SOURCE)
def fetch_bestbuy_api_product(
    url: str,
    anchors: list[Anchor] | None = None,
    *,
    timeout: float = 30.0,
    api_key: str | None = None,
    **_: Any,
) -> list[ProductSnapshot]:
    """Fetch a BestBuy product via the Developer API; return one :class:`ProductSnapshot`.

    ``url`` is the BestBuy *website* URL for the product. The SKU is
    extracted from the path (``.../<SKU>.p``) or the ``skuId`` query
    parameter. The API is then hit at
    ``api.bestbuy.com/v1/products/<SKU>.json``.

    ``api_key`` defaults to ``os.environ["BESTBUY_API_KEY"]``. Raises
    :class:`RuntimeError` if neither is set.

    Attribution uses the URL-map gate: one of ``anchors`` must have
    ``source_urls["bestbuy_api"] == url`` (exact string match).
    """
    key = api_key or os.environ.get(API_KEY_ENV)
    if not key:
        raise RuntimeError(
            f"bestbuy_api: {API_KEY_ENV} not set; register a Developer API "
            f"key at developer.bestbuy.com and add it to your .env"
        )

    sku = _extract_sku(url)
    body = _fetch_product(sku, api_key=key, timeout=timeout)
    return parse_bestbuy_product_response(body, url, anchors=anchors)


def parse_bestbuy_product_response(
    response_body: str | bytes,
    url: str,
    *,
    anchors: list[Anchor] | None = None,
) -> list[ProductSnapshot]:
    """Pure parse: BestBuy API JSON body → one :class:`ProductSnapshot`.

    Raises :class:`ValueError` on missing attribution or on JSON that
    doesn't carry a ``sku`` + ``name`` minimum. Partial success on
    missing optional fields (rating, image, specs) — a snapshot is
    still emitted with whatever was present.
    """
    attribution = attribute_url(url, SOURCE, anchors or [])
    if attribution is None:
        raise ValueError(
            f"no Anchor has source_urls[{SOURCE!r}] == {url!r}; "
            f"provide one that matches the fetched URL exactly"
        )

    if isinstance(response_body, bytes):
        response_body = response_body.decode("utf-8")
    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError as e:
        raise ValueError(f"bestbuy_api: response body is not valid JSON: {e}") from e

    sku_raw = payload.get("sku")
    name = payload.get("name") or ""
    if sku_raw is None or not name:
        raise ValueError(
            "bestbuy_api: response missing sku or name; product likely not found"
        )

    sku = str(sku_raw)

    price = _decimal_or_none(payload.get("salePrice"))
    list_price = _decimal_or_none(payload.get("regularPrice"))
    if price is None and list_price is not None:
        # If the product isn't on sale, salePrice is often absent; use
        # regularPrice as the effective price and leave list_price None.
        price = list_price
        list_price = None

    rating = _float_or_none(payload.get("customerReviewAverage"))
    review_count = _int_or_none(payload.get("customerReviewCount"))

    image_url = (
        payload.get("largeFrontImage")
        or payload.get("image")
        or payload.get("thumbnailImage")
        or None
    )

    specs = _parse_details(payload.get("details") or [])
    category = _leaf_category(payload.get("categoryPath") or [])

    in_stock = _derive_in_stock(payload)
    availability_text = _availability_text(payload)

    features = [
        f.get("feature", "")
        for f in payload.get("features") or []
        if isinstance(f, dict) and f.get("feature")
    ]
    config_summary = " / ".join(features[:3]) if features else None

    return [
        ProductSnapshot(
            source=SOURCE,
            source_id=sku,
            variant_key=None,
            anchor_id=attribution.anchor_id,
            url=url,
            title=name,
            brand=payload.get("manufacturer") or None,
            model=payload.get("modelNumber") or None,
            category=category,
            config_summary=config_summary,
            price=price,
            list_price=list_price,
            currency="USD",
            in_stock=in_stock,
            availability_text=availability_text,
            rating=rating,
            review_count=review_count,
            image_url=image_url,
            specs=specs,
            raw={
                "spec_source": "developer_api_details",
                "sku": sku,
                "on_sale": bool(payload.get("onSale")),
                "orderable": payload.get("orderable"),
            },
        )
    ]


# ---------------------------------------------------------------------------
# URL → SKU
# ---------------------------------------------------------------------------


def _extract_sku(url: str) -> str:
    """Return the numeric SKU from a BestBuy product URL.

    Accepts both the path-based form (``.../<SKU>.p``) and the query
    form (``?skuId=<SKU>``). Raises :class:`ValueError` if neither is
    present.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host and "bestbuy.com" not in host:
        raise ValueError(
            f"bestbuy_api: URL host {host!r} is not bestbuy.com; "
            f"pass a bestbuy.com product URL"
        )

    m = _SKU_PATH_RE.search(parsed.path + "/")
    if m is not None:
        return m.group(1)

    query = parse_qs(parsed.query)
    sku_values = query.get("skuId") or []
    if sku_values and sku_values[0].isdigit():
        return sku_values[0]

    raise ValueError(
        f"bestbuy_api: URL {url!r} does not carry a SKU in /<SKU>.p "
        f"or ?skuId=<SKU> form"
    )


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _fetch_product(sku: str, *, api_key: str, timeout: float) -> str:
    """Call the ``/v1/products/<SKU>.json`` endpoint and return the body."""
    endpoint = f"{API_BASE}/{sku}.json"
    headers = {
        "Accept": "application/json",
        "User-Agent": "scrapers-lib/0.4 (+bestbuy_api)",
    }
    r = httpx.get(
        endpoint,
        params={"apiKey": api_key},
        headers=headers,
        follow_redirects=True,
        timeout=timeout,
    )
    if r.status_code == 403:
        raise RuntimeError(
            f"bestbuy_api: HTTP 403 on {endpoint}; {API_KEY_ENV} likely invalid"
        )
    if r.status_code == 404:
        raise ValueError(
            f"bestbuy_api: HTTP 404 on {endpoint}; SKU {sku!r} not found"
        )
    r.raise_for_status()
    return r.text


# ---------------------------------------------------------------------------
# Parsers (pure)
# ---------------------------------------------------------------------------


def _parse_details(details: list[dict[str, Any]]) -> dict[str, str]:
    """``[{"name": "Processor", "value": "..."}, ...]`` → ``{name: value}``."""
    out: dict[str, str] = {}
    for item in details:
        if not isinstance(item, dict):
            continue
        name = normalize_spec_value(str(item.get("name") or ""))
        value = normalize_spec_value(str(item.get("value") or ""))
        if name and value and name not in out:
            out[name] = value
    return out


def _leaf_category(category_path: list[dict[str, Any]]) -> str | None:
    """Last non-empty ``name`` in a BestBuy ``categoryPath`` breadcrumb."""
    for entry in reversed(category_path):
        if isinstance(entry, dict):
            name = entry.get("name")
            if name:
                return str(name)
    return None


def _derive_in_stock(payload: dict[str, Any]) -> bool | None:
    """True if the API reports the SKU orderable / online-available."""
    orderable = payload.get("orderable")
    if isinstance(orderable, str):
        if orderable.lower() == "available":
            return True
        if orderable.lower() in {"soldout", "backorder"}:
            return False

    online = payload.get("onlineAvailability")
    if isinstance(online, bool):
        return online
    in_store = payload.get("inStoreAvailability")
    if isinstance(in_store, bool):
        return in_store
    return None


def _availability_text(payload: dict[str, Any]) -> str | None:
    """Human-readable availability string from whichever fields the API provided."""
    online = payload.get("onlineAvailabilityText")
    if online:
        return str(online)
    in_store = payload.get("inStoreAvailabilityText")
    if in_store:
        return str(in_store)
    orderable = payload.get("orderable")
    if orderable:
        return str(orderable)
    return None


def _decimal_or_none(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def _float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int_or_none(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
