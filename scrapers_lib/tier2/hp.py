"""HP shop PDP product fetcher.

HP embeds its full shop-page state as a JSON-encoded HTML comment inside
a hidden ``<div id="data" style="display:none"><!-- {JSON} --></div>``
block at the bottom of every PDP. That state contains, under
``slugInfo.components.pdpCTOConfiguration.configurations``, one tile per
pre-built "HP Recommended Configuration" (typically 3) with a
``fullSpecs.technical_specifications`` array of configurable-option
categories. Each category carries a ``Current Configuration`` value plus
``Alternate Options`` the customer can pick.

The fetcher extracts the state JSON with one regex, flattens each tile's
technical_specifications into a ``ProductSnapshot.specs`` dict (current
value first, alternatives on subsequent lines — same serialization
discipline as the Lenovo fetcher), and emits one snapshot per tile.

Plain httpx is sufficient for the PDP itself — HP does not bot-gate plain
HTTP clients. Playwright is a different story: HP fingerprints
headless and stealth-Chromium alike and rejects ``/shop/pdp/`` navigation
with ``ERR_HTTP2_PROTOCOL_ERROR`` even with session warming. Fortunately
we do not need Playwright — the plain-HTTP response already carries the
state blob.

**Coverage caveat.** The ``technical_specifications`` array describes
**configurable options** (CPU/GPU, memory, storage, display, colour,
keyboard, OS, wireless, battery, software) — not the full datasheet.
Additional categories that appear in HP's "Tech Specs" UI section
(Dimensions, Weight, Ports, Power supply, Audio, Sensors, Warranty) are
hydrated client-side and are NOT in the initial httpx response. Full
coverage via HP's QuickSpecs PDFs at ``h20195.www2.hp.com`` is feasible
in a future wave (see ``docs/ADDING_A_SOURCE.md`` §4 HP row for notes)
but requires a separate Commercial Doc ID → PDP SKU lookup.

Verified on two unrelated products — Omen Max 16t-ah000 (gaming, Intel)
and Pavilion 16z-ag000 (consumer, AMD) — which return identical JSON
structural shape with only minor per-product variation in category names
(e.g. Pavilion merges Processor/Graphics/Memory into one category,
Omen splits them). The parser walks categories by array position and
never hard-codes category names.
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
from scrapers_lib.tier2.base import normalize_spec_value, parse_product_jsonld

logger = logging.getLogger(__name__)

SOURCE = "hp"

_STATE_PATTERN = re.compile(
    r'<div\s+id="data"\s+style="display:none"\s*>\s*<!--\s*(\{.*?\})\s*-->\s*</div>',
    re.DOTALL,
)

_BR_SPLIT = re.compile(r"<br\s*/?>", re.I)

_PDP_PATH_RE = re.compile(r"^/us-en/shop/pdp/[A-Za-z0-9_-]+/?$")

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

# Categories we use to assemble a short config_summary — these are the
# Demo-2 max-spec-comparison axes. Names vary per HP product family, so
# we match substrings rather than exact strings.
_CONFIG_SUMMARY_KEY_HINTS = (
    "processor",  # matches "Processor and graphics" / "Processor, graphics & memory"
    "memory",
    "storage",
    "display",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@register(SOURCE)
def fetch_hp_product(
    url: str,
    anchors: list[Anchor] | None = None,
    *,
    timeout: float = 30.0,
    **_: Any,
) -> list[ProductSnapshot]:
    """Fetch an HP shop PDP; return one :class:`ProductSnapshot` per tile.

    The input ``url`` must be an HP shop PDP of the form
    ``https://www.hp.com/us-en/shop/pdp/<product-slug>`` (with or without
    trailing query / fragment). Attribution uses the URL-map gate: one
    of ``anchors`` must have ``source_urls["hp"] == url``. Raises
    :class:`ValueError` otherwise.

    Returns one snapshot per configuration tile exposed in HP's own
    "Recommended Configurations" picker (typically 3). Per-tile
    ``source_id`` and ``variant_key`` are the ``configCatentryId`` HP
    assigns each pre-built SKU — analogous to Dell's ``data-oc``.
    """
    body = _fetch_pdp(url, timeout=timeout)
    return parse_hp_product_page(body, url, anchors=anchors)


def parse_hp_product_page(
    html: str,
    url: str,
    *,
    anchors: list[Anchor] | None = None,
) -> list[ProductSnapshot]:
    """Pure parse: shop PDP HTML → one :class:`ProductSnapshot` per tile.

    Raises :class:`ValueError` on missing attribution. Raises
    :class:`RuntimeError` when the state-JSON blob or
    ``pdpCTOConfiguration.configurations`` is missing — those are
    structural contract breaks (likely a site redesign) and should
    surface loudly rather than silently emit an empty list.
    """
    attribution = attribute_url(url, SOURCE, anchors or [])
    if attribution is None:
        raise ValueError(
            f"no Anchor has source_urls[{SOURCE!r}] == {url!r}; "
            f"provide one that matches the fetched URL exactly"
        )

    state = _extract_state_json(html)
    configs = (
        state.get("slugInfo", {})
        .get("components", {})
        .get("pdpCTOConfiguration", {})
        .get("configurations")
        or []
    )
    if not configs:
        raise RuntimeError(
            f"hp: no pdpCTOConfiguration.configurations at {url}; "
            f"page structure may have changed"
        )

    products_ld = parse_product_jsonld(html)
    # HP's JSON-LD sometimes carries a stale product name from a template
    # (observed: Pavilion PDP JSON-LD named a completely different OmniBook
    # product). Prefer tile-level name for title; use JSON-LD only for
    # brand / rating / image fallback, all of which have less template rot.
    shared = _jsonld_shared(products_ld[0] if products_ld else {})

    snapshots: list[ProductSnapshot] = []
    for tile in configs:
        source_id = str(tile.get("configCatentryId") or "").strip()
        if not source_id:
            logger.warning(
                "hp: tile at %s missing configCatentryId; skipping", url
            )
            continue

        specs = _flatten_technical_specs(
            tile.get("fullSpecs", {}).get("technical_specifications") or []
        )

        snapshots.append(
            ProductSnapshot(
                source=SOURCE,
                source_id=source_id,
                variant_key=source_id,
                anchor_id=attribution.anchor_id,
                url=url,
                title=_pick_title(tile, shared, url),
                brand=shared.get("brand") or "HP",
                config_summary=_config_summary(specs),
                price=_price_from_tile(tile, "salePrice")
                or _price_from_tile(tile, "regularPrice"),
                list_price=_price_from_tile(tile, "regularPrice"),
                currency="USD",
                rating=shared.get("rating"),
                review_count=shared.get("review_count"),
                image_url=(tile.get("image") or shared.get("image")) or None,
                specs=specs,
                raw={
                    "spec_source": "pdpCTOConfiguration",
                    "config_catentry_id": source_id,
                    "config_name": tile.get("configName") or None,
                },
            )
        )

    if not snapshots:
        raise RuntimeError(
            f"hp: pdpCTOConfiguration.configurations had {len(configs)} entries "
            f"but none carried a configCatentryId at {url}"
        )
    return snapshots


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _fetch_pdp(url: str, *, timeout: float) -> str:
    """Fetch a shop PDP URL and return its HTML body."""
    _validate_pdp_url(url)
    headers = {
        "User-Agent": _DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    r = httpx.get(url, headers=headers, follow_redirects=True, timeout=timeout)
    r.raise_for_status()
    return r.text


def _validate_pdp_url(url: str) -> None:
    """Reject URLs that are not recognizable HP shop PDPs.

    HP has many surfaces (support docs, QuickSpecs, marketing landing pages)
    that this fetcher does not parse. Fail fast with a clear message when a
    caller passes one of those instead.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host and "hp.com" not in host:
        raise ValueError(
            f"hp: URL host {host!r} is not hp.com; "
            f"pass a www.hp.com/us-en/shop/pdp/... URL"
        )
    if not _PDP_PATH_RE.match(parsed.path):
        raise ValueError(
            f"hp: URL path {parsed.path!r} is not /us-en/shop/pdp/<slug>"
        )


# ---------------------------------------------------------------------------
# State-JSON extraction (pure)
# ---------------------------------------------------------------------------


def _extract_state_json(html: str) -> dict[str, Any]:
    """Return the parsed JSON carried by ``<div id="data"><!-- {JSON} --></div>``.

    Raises :class:`RuntimeError` on pattern / parse failure — the blob is
    the primary data source, and its absence means HP changed its SSR.
    """
    m = _STATE_PATTERN.search(html)
    if m is None:
        raise RuntimeError(
            "hp: no <div id='data'><!-- {JSON} --></div> block found; "
            "page structure may have changed"
        )
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"hp: state JSON failed to parse: {e}"
        ) from e


# ---------------------------------------------------------------------------
# Spec flattening (pure)
# ---------------------------------------------------------------------------


def _flatten_technical_specs(
    technical_specs: list[dict[str, Any]],
) -> dict[str, str]:
    """Flatten HP's per-tile ``technical_specifications`` into spec dict.

    Each category has a ``name`` and a list of ``value`` entries, each
    keyed by ``subheading`` — typically ``"Included in Current
    Configuration"`` and ``"Alternate Options"``. The rendered value
    strings may contain ``<br />`` separators between multiple options
    and HTML entities (``&trade;``, ``&reg;``, ``&amp;``).

    Output: ``{category_name: "current\\nalt1\\nalt2\\n..."}``. The first
    line is always the current configuration's value so consumers picking
    the default get it with ``value.split("\\n", 1)[0]``; remaining lines
    are alternative options for max-spec comparison.
    """
    out: dict[str, str] = {}
    for cat in technical_specs:
        name = (cat.get("name") or "").strip()
        if not name:
            continue

        current_parts: list[str] = []
        alt_parts: list[str] = []
        for v in cat.get("value") or []:
            raw = v.get("value") or ""
            if not raw:
                continue
            subheading = (v.get("subheading") or "").strip().lower()
            fragments = [
                normalize_spec_value(html_module.unescape(p))
                for p in _BR_SPLIT.split(raw)
                if p.strip()
            ]
            fragments = [f for f in fragments if f]
            if not fragments:
                continue
            if "current" in subheading:
                current_parts.extend(fragments)
            else:
                # "Alternate Options" or any other subheading we don't recognize
                # — treat as alternatives rather than dropping.
                alt_parts.extend(fragments)

        ordered = current_parts + alt_parts
        if ordered and name not in out:
            out[name] = "\n".join(ordered)
    return out


# ---------------------------------------------------------------------------
# Enrichment helpers (pure)
# ---------------------------------------------------------------------------


def _pick_title(
    tile: dict[str, Any], shared: dict[str, Any], url: str
) -> str:
    """Pick a non-empty title for the snapshot, preferring the tile's own name."""
    for candidate in (tile.get("name"), shared.get("name")):
        if candidate and isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    # URL-slug fallback. ``/us-en/shop/pdp/<slug>`` → slug → human-ish title.
    slug = urlparse(url).path.rstrip("/").split("/")[-1] or "HP Product"
    return slug.replace("-", " ").strip() or "HP Product"


def _price_from_tile(tile: dict[str, Any], key: str) -> Decimal | None:
    """Safely coerce a tile price field (``regularPrice``/``salePrice``) to Decimal."""
    raw = tile.get(key)
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _jsonld_shared(p: dict[str, Any]) -> dict[str, Any]:
    """Pull brand / rating / image fallbacks from a JSON-LD ``Product`` object.

    The title-like ``name`` field is often stale on HP pages (template
    reuse observed on Pavilion PDPs naming a different OmniBook product),
    so we surface it here but callers should prefer tile-level ``name``.
    """
    out: dict[str, Any] = {"name": p.get("name")}

    brand = p.get("brand")
    if isinstance(brand, dict):
        out["brand"] = brand.get("name")
    elif isinstance(brand, str):
        out["brand"] = brand

    rating = p.get("aggregateRating")
    if isinstance(rating, dict):
        try:
            out["rating"] = float(rating.get("ratingValue"))
        except (TypeError, ValueError):
            pass
        try:
            out["review_count"] = int(rating.get("reviewCount"))
        except (TypeError, ValueError):
            pass

    image = p.get("image")
    if isinstance(image, str):
        out["image"] = image
    elif isinstance(image, list) and image and isinstance(image[0], str):
        out["image"] = image[0]

    return out


def _config_summary(specs: dict[str, str]) -> str | None:
    """Short ``GPU / RAM / Storage / Display`` summary from the tile's current values.

    HP's category names vary across product lines (gaming vs consumer
    vs business), so this matches on substring keywords rather than
    exact names. Values are multi-line (current on line 0); we take
    the first line only.
    """
    parts: list[str] = []
    seen: set[str] = set()
    for hint in _CONFIG_SUMMARY_KEY_HINTS:
        for key, val in specs.items():
            if hint in key.lower() and key not in seen:
                first_line = val.split("\n", 1)[0].strip()
                if first_line:
                    parts.append(first_line)
                    seen.add(key)
                    break
    return " / ".join(parts) if parts else None
