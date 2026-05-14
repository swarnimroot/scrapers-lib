"""HP shop PDP product fetcher.

HP serves laptop product data in **three** observed PDP shapes on
``/us-en/shop/pdp/<slug>`` URLs. The slug shape is a strong but
imperfect hint — the parser dispatches on ``slugInfo.templateKey`` +
the presence of CTO / STO data blocks rather than on slug patterns.

1. **AV-code customizer (CTO — Configure-To-Order)**, slugs typically
   ending ``…av-1`` (e.g. ``a8vy4av-1``, ``a4nq6av-1``,
   ``c52b1av-1``, ``94g92av-1``). ``product_class = "CTO"``. The PDP
   HTML carries ``slugInfo.components.pdpCTOConfiguration.configurations``
   — a 2-3 element array of pre-built "HP Recommended Configuration"
   tiles. Each tile has a ``fullSpecs.technical_specifications`` array
   with per-row "Included in Current Configuration" and "Alternate
   Options" subheadings (~12 config-picker categories). One snapshot
   per tile is emitted. Verified on OMEN Max 16t-ah000 (Intel/gaming)
   and Pavilion 16z-ag000 (AMD/consumer, redirects to OmniBook 5).

2. **SKU-final preconfigured (STO — Stock)**, slugs typically ending
   ``…nr`` (e.g. ``ap0097nr``, ``ah0097nr``, ``fa2047nr``).
   ``product_class = "STO"``. The PDP HTML carries
   ``pdpCTOConfiguration: None`` and instead populates
   ``slugInfo.components.productInitial`` (sku, brand, name, rating,
   numReviews, mfpartnumber, family, keyPoints), ``productInitialPrice``
   (regularPrice, salePrice, images), and ``pdpImages``. JSON-LD
   ``Product`` is also present on STO PDPs (absent on CTO). The async
   ``pdpTechSpecs`` endpoint returns 28+ Tech Specs categories in the
   same row shape as the CTO config-picker array, so it serves as the
   spec source. One snapshot per URL is emitted. Verified on OMEN
   Gaming Laptop 16-ap0097nr (Wave 2i, 2026-05-13).

3. **Delisted / homepage-redirect.** Discontinued slugs (observed:
   17.3" OMEN ``a7jp9av-1``) silently redirect to the shop homepage at
   the CMS layer — final response URL is ``/us-en/shop``,
   ``templateKey = "home"``, ``components`` carries home-page surfaces
   only (no ``productInitial``, no ``pdpCTOConfiguration``). The parser
   raises :class:`HPProductNotFoundError` — a typed
   :class:`RuntimeError` subclass — so callers can skip dead slugs
   cleanly with ``except HPProductNotFoundError``.

**Tech Specs hydration endpoint.** Both CTO and STO PDPs share a
slug-keyed GraphQL hydration endpoint:

    /us-en/shop/app/api/web/graphql/page/pdp%2F<slug>/async

Reachable via the same warmed curl_cffi + Chrome + HTTP/1.1 session
that fetched the PDP, with ``Referer: <PDP URL>`` +
``X-Requested-With: XMLHttpRequest`` + ``Accept: application/json``
headers. The response carries ``data.page.pageComponents.pdpTechSpecs.
technical_specifications`` — same per-row shape as the CTO config-
picker array (``{name, tooltip, value:[{value, subheading}]}``), so the
same flattening helper consumes both. On CTO PDPs the async array is
**merged into each tile** (async base, per-tile overlay). On STO PDPs
the async array IS the primary spec source for the single snapshot.

The async fetch is best-effort; on any failure (slug derivation,
network, non-200, JSON parse, missing envelope) the fetcher logs at
INFO and continues — STO snapshots simply ship with an empty ``specs``
dict and CTO snapshots fall back to config-picker-only data (~12
categories, matching v1.1 behavior).

The PDP itself does not require Chrome impersonation — plain httpx
returned identical bytes during recon — but we share one warmed
curl_cffi session across both calls because the async endpoint
requires the same session that fetched the PDP (a fresh session
returns an empty envelope).
"""

from __future__ import annotations

import html as html_module
import json
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote, urlparse

from scrapers_lib.core.attribution import attribute_url
from scrapers_lib.core.registry import register
from scrapers_lib.core.schemas import Anchor, ProductSnapshot
from scrapers_lib.tier2.base import (
    normalize_spec_value,
    parse_product_jsonld,
    warmed_curl_session,
)

logger = logging.getLogger(__name__)

SOURCE = "hp"

HOME_URL = "https://www.hp.com/"

_STATE_PATTERN = re.compile(
    r'<div\s+id="data"\s+style="display:none"\s*>\s*<!--\s*(\{.*?\})\s*-->\s*</div>',
    re.DOTALL,
)

_BR_SPLIT = re.compile(r"<br\s*/?>", re.I)

# Capture (1) /us-en/shop region prefix and (2) PDP slug. The regex stays
# strict-US-EN to preserve the historical error-message contract.
_PDP_PATH_RE = re.compile(r"^(/us-en/shop)/pdp/([A-Za-z0-9_-]+)/?$")

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
# Exceptions
# ---------------------------------------------------------------------------


class HPProductNotFoundError(RuntimeError):
    """Raised when an HP shop PDP slug is delisted / redirected.

    HP silently rewrites discontinued PDP slugs to the shop homepage at
    the CMS layer — the HTTP response is 200, but ``slugInfo.templateKey``
    becomes ``"home"`` and the product surfaces (``productInitial``,
    ``pdpCTOConfiguration``) disappear. Catch this exception to skip
    dead slugs without aborting a batch — it is a typed
    :class:`RuntimeError` subclass, so existing ``except RuntimeError``
    handlers still catch it but new handlers can opt in to the more
    precise type.

    Introduced in Wave 2i (v1.6.0).
    """


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@register(SOURCE)
def fetch_hp_product(
    url: str,
    anchors: list[Anchor] | None = None,
    *,
    timeout: float = 30.0,
    warm: bool = True,
    impersonate: str = "chrome",
    **_: Any,
) -> list[ProductSnapshot]:
    """Fetch an HP shop PDP; return one :class:`ProductSnapshot` per tile.

    The input ``url`` must be an HP shop PDP of the form
    ``https://www.hp.com/us-en/shop/pdp/<product-slug>``. Two HTTP
    calls are made on the same warmed curl_cffi + Chrome + HTTP/1.1
    session: the PDP HTML for the config-picker tiles, and the sibling
    ``/async`` GraphQL endpoint for the product-wide Tech Specs section.
    The async fetch is best-effort — on failure (non-200, JSON parse
    error, missing envelope) the fetcher logs and continues with
    config-picker-only data, mirroring the v1.1 12-category behavior.

    Attribution uses the URL-map gate: one of ``anchors`` must have
    ``source_urls["hp"] == url``. Raises :class:`ValueError` otherwise.

    Returns one snapshot per configuration tile exposed in HP's own
    "Recommended Configurations" picker (typically 3). Per-tile
    ``source_id`` and ``variant_key`` are the ``configCatentryId`` HP
    assigns each pre-built SKU — analogous to Dell's ``data-oc``.
    """
    html, async_techspecs = _fetch_pdp_with_techspecs(
        url, timeout=timeout, warm=warm, impersonate=impersonate
    )
    return parse_hp_product_page(
        html, url, anchors=anchors, async_techspecs=async_techspecs
    )


def parse_hp_product_page(
    html: str,
    url: str,
    *,
    anchors: list[Anchor] | None = None,
    async_techspecs: dict[str, Any] | None = None,
) -> list[ProductSnapshot]:
    """Pure parse: shop PDP HTML → list of :class:`ProductSnapshot`.

    Dispatches on the page's data shape (see the module docstring):

    - **CTO** (config picker present): one snapshot per tile, specs
      merged from per-tile ``fullSpecs`` over the async product-wide
      array. Matches historical v1.5 behavior verbatim.
    - **STO** (``productInitial`` populated, ``pdpCTOConfiguration``
      ``None`` or empty): one snapshot for the SKU; specs come from the
      async ``pdpTechSpecs`` array. New in v1.6.0.
    - **Homepage redirect** (``templateKey != "pdp"``): raises
      :class:`HPProductNotFoundError`. New in v1.6.0.

    ``async_techspecs`` is the parsed ``data.page.pageComponents.
    pdpTechSpecs`` sub-tree returned by HP's ``/async`` hydration
    endpoint. When provided, its ``technical_specifications`` array is
    flattened with the same helper as the config-picker array. Pass
    ``None`` (default) to skip — CTO snapshots fall back to config-
    picker-only specs (v1.1 behavior); STO snapshots ship with an
    empty ``specs`` dict.

    Raises :class:`ValueError` on missing attribution. Raises
    :class:`HPProductNotFoundError` when the slug is delisted /
    redirected. Raises :class:`RuntimeError` when the state-JSON blob
    is missing or the page carries neither CTO nor STO data — those
    are structural contract breaks (likely a site redesign) and should
    surface loudly rather than silently emit an empty list.
    """
    attribution = attribute_url(url, SOURCE, anchors or [])
    if attribution is None:
        raise ValueError(
            f"no Anchor has source_urls[{SOURCE!r}] == {url!r}; "
            f"provide one that matches the fetched URL exactly"
        )

    state = _extract_state_json(html)
    slug_info = state.get("slugInfo") or {}

    template_key = slug_info.get("templateKey")
    if template_key != "pdp":
        # HP silently redirects discontinued PDP slugs to the shop
        # homepage; the response is 200 but the page no longer carries
        # a product. Raise the typed exception so consumers can skip.
        raise HPProductNotFoundError(
            f"hp: slug appears delisted or redirected "
            f"(templateKey={template_key!r}) at {url}"
        )

    components = slug_info.get("components") or {}
    # Defensive `or {}` — STO PDPs set pdpCTOConfiguration to None
    # (not missing), so the bare `.get(..., {})` default does not fire.
    cto = components.get("pdpCTOConfiguration") or {}
    configs = cto.get("configurations") or []

    products_ld = parse_product_jsonld(html)
    # HP's JSON-LD sometimes carries a stale product name from a template
    # (observed: Pavilion PDP JSON-LD named a completely different OmniBook
    # product). Prefer tile-level / productInitial name for title; use
    # JSON-LD only for brand / rating / image fallback, all of which have
    # less template rot.
    shared = _jsonld_shared(products_ld[0] if products_ld else {})
    async_specs = _extract_async_specs(async_techspecs)

    if configs:
        return _parse_cto_tiles(
            configs=configs,
            shared=shared,
            async_specs=async_specs,
            anchor_id=attribution.anchor_id,
            url=url,
        )

    product_initial = components.get("productInitial") or {}
    if product_initial:
        return [
            _parse_sto_snapshot(
                components=components,
                shared=shared,
                async_specs=async_specs,
                anchor_id=attribution.anchor_id,
                url=url,
            )
        ]

    raise RuntimeError(
        f"hp: page has neither pdpCTOConfiguration.configurations nor "
        f"productInitial at {url}; page structure may have changed"
    )


def _parse_cto_tiles(
    *,
    configs: list[dict[str, Any]],
    shared: dict[str, Any],
    async_specs: dict[str, str],
    anchor_id: str,
    url: str,
) -> list[ProductSnapshot]:
    """Emit one snapshot per CTO configuration tile."""
    snapshots: list[ProductSnapshot] = []
    for tile in configs:
        source_id = str(tile.get("configCatentryId") or "").strip()
        if not source_id:
            logger.warning(
                "hp: tile at %s missing configCatentryId; skipping", url
            )
            continue

        tile_specs = _flatten_technical_specs(
            tile.get("fullSpecs", {}).get("technical_specifications") or []
        )
        # Per-tile values win on overlap (they reflect the SKU's actual
        # configuration); async fills product-wide gaps.
        merged_specs = {**async_specs, **tile_specs}

        snapshots.append(
            ProductSnapshot(
                source=SOURCE,
                source_id=source_id,
                variant_key=source_id,
                anchor_id=anchor_id,
                url=url,
                title=_pick_title(tile, shared, url),
                brand=shared.get("brand") or "HP",
                config_summary=_config_summary(merged_specs),
                price=_price_from_tile(tile, "salePrice")
                or _price_from_tile(tile, "regularPrice"),
                list_price=_price_from_tile(tile, "regularPrice"),
                currency="USD",
                rating=shared.get("rating"),
                review_count=shared.get("review_count"),
                image_url=(tile.get("image") or shared.get("image")) or None,
                specs=merged_specs,
                raw={
                    "spec_source": (
                        "pdpCTOConfiguration+pdpTechSpecs"
                        if async_specs
                        else "pdpCTOConfiguration"
                    ),
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


def _parse_sto_snapshot(
    *,
    components: dict[str, Any],
    shared: dict[str, Any],
    async_specs: dict[str, str],
    anchor_id: str,
    url: str,
) -> ProductSnapshot:
    """Build a single :class:`ProductSnapshot` for a STO (stock) PDP.

    Data sources, in priority order:

    - ``productInitial`` — sku, brand, name, family, rating, numReviews
    - ``productInitialPrice`` — salePrice, regularPrice
    - ``pdpImages.fullImages`` — first non-video image (clean URLs;
      ``productInitialPrice.images`` carries HTML-escaped ``&amp;`` so
      we avoid it)
    - async ``pdpTechSpecs`` — the only spec source for STO (no per-tile
      ``fullSpecs`` exists; the page is a single fixed SKU)
    - JSON-LD ``Product`` — fallback for brand / rating / image

    Raises :class:`RuntimeError` when ``productInitial.sku`` is missing
    (it's HP's stable identifier for STO SKUs — analog of
    ``configCatentryId`` for CTO tiles).
    """
    product_initial = components.get("productInitial") or {}
    prices = components.get("productInitialPrice") or {}
    pdp_images = components.get("pdpImages") or {}

    sku = str(product_initial.get("sku") or "").strip()
    if not sku:
        raise RuntimeError(
            f"hp: STO PDP at {url} has no productInitial.sku; "
            f"cannot derive source_id"
        )

    name = product_initial.get("name") or shared.get("name") or ""
    title = name.strip() if isinstance(name, str) and name.strip() else (
        _pick_title({}, shared, url)
    )

    brand = product_initial.get("brand") or shared.get("brand") or "HP"
    brand_str = brand.strip() if isinstance(brand, str) else None

    sale = _price_from_tile(prices, "salePrice")
    regular = _price_from_tile(prices, "regularPrice")
    price = sale or regular
    # Only surface list_price when it differs from price (i.e. on sale);
    # otherwise leave None to match Tier 1 BestBuy-API convention.
    list_price = regular if (sale and regular and sale != regular) else None

    return ProductSnapshot(
        source=SOURCE,
        source_id=sku,
        variant_key=sku,
        anchor_id=anchor_id,
        url=url,
        title=title,
        brand=brand_str or "HP",
        category=str(product_initial.get("topCategory") or "") or None,
        config_summary=_config_summary(async_specs),
        price=price,
        list_price=list_price,
        currency="USD",
        rating=_rating_from_product_initial(product_initial, shared),
        review_count=_review_count_from_product_initial(product_initial, shared),
        image_url=_first_pdp_image_url(pdp_images, shared),
        specs=async_specs,
        raw={
            "spec_source": (
                "productInitial+pdpTechSpecs" if async_specs else "productInitial"
            ),
            "mfpartnumber": product_initial.get("mfpartnumber") or None,
            "family": product_initial.get("family") or None,
            "product_class": product_initial.get("product_class") or None,
        },
    )


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _fetch_pdp_with_techspecs(
    url: str,
    *,
    timeout: float,
    warm: bool,
    impersonate: str,
) -> tuple[str, dict[str, Any] | None]:
    """Warm against HP's homepage, fetch the PDP, then fetch the /async sibling.

    Both requests share one warmed curl_cffi + Chrome + HTTP/1.1 session
    so cookies established by the warm + PDP carry into the async call.
    HP's hydration endpoint requires the same session that fetched the
    PDP — a fresh session returns an empty envelope.

    Returns ``(html, async_techspecs)``. ``async_techspecs`` is the
    parsed ``pdpTechSpecs`` sub-tree from the async response, or
    ``None`` if the async fetch failed for any reason. The PDP itself
    is not best-effort — a non-200 PDP raises.

    ``curl_cffi`` is imported lazily so ``import scrapers_lib`` stays
    cheap for consumers who do not touch Tier 2.
    """
    _validate_pdp_url(url)

    with warmed_curl_session(
        HOME_URL, impersonate=impersonate, warm=warm
    ) as s:
        r = s.get(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=timeout,
        )
        r.raise_for_status()
        html = r.text

        async_techspecs = _fetch_async_techspecs(s, url, timeout=timeout)

    return html, async_techspecs


def _fetch_async_techspecs(
    session: Any,
    pdp_url: str,
    *,
    timeout: float,
) -> dict[str, Any] | None:
    """Best-effort fetch of the PDP's sibling ``/async`` hydration endpoint.

    Returns the parsed ``data.page.pageComponents.pdpTechSpecs`` sub-tree
    or ``None`` on any failure (slug derivation, network, non-200, JSON
    parse, missing envelope). Failures are logged at INFO level and the
    caller continues with config-picker-only data.
    """
    try:
        async_url = _derive_async_url(pdp_url)
    except ValueError as e:
        logger.info("hp: async URL derivation failed: %s", e)
        return None

    try:
        r = session.get(
            async_url,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": pdp_url,
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=timeout,
        )
    except Exception as e:
        logger.info("hp: async fetch errored for %s: %s", pdp_url, e)
        return None

    if r.status_code != 200:
        logger.info(
            "hp: async endpoint returned %d for %s", r.status_code, pdp_url
        )
        return None

    try:
        data = json.loads(r.text)
    except json.JSONDecodeError as e:
        logger.info("hp: async response not JSON for %s: %s", pdp_url, e)
        return None

    try:
        techspecs = data["data"]["page"]["pageComponents"]["pdpTechSpecs"]
    except (KeyError, TypeError):
        logger.info(
            "hp: async response missing pdpTechSpecs envelope for %s", pdp_url
        )
        return None

    if not isinstance(techspecs, dict):
        logger.info(
            "hp: pdpTechSpecs is not a dict (%s) for %s",
            type(techspecs).__name__,
            pdp_url,
        )
        return None
    return techspecs


def _derive_async_url(pdp_url: str) -> str:
    """Return the slug-keyed ``/async`` hydration URL sibling to the PDP.

    The async URL sits at the same region/locale prefix as the PDP, with
    ``/pdp/<slug>`` swapped to
    ``/app/api/web/graphql/page/pdp%2F<slug>/async``.
    """
    parsed = urlparse(pdp_url)
    m = _PDP_PATH_RE.match(parsed.path)
    if not m:
        raise ValueError(f"hp: PDP path shape unexpected: {parsed.path!r}")
    region_shop = m.group(1)  # /us-en/shop
    slug = m.group(2)
    return (
        f"{parsed.scheme}://{parsed.netloc}{region_shop}"
        f"/app/api/web/graphql/page/{quote('pdp/' + slug, safe='')}/async"
    )


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
    """Flatten HP's ``technical_specifications`` array into a spec dict.

    Each category has a ``name`` and a list of ``value`` entries, each
    keyed by ``subheading`` — typically ``"Included in Current
    Configuration"`` and ``"Alternate Options"``. The inner ``value``
    field is a string in the config-picker shape (with ``<br />``
    separators between multiple options and HTML entities) and either
    a string or a list of strings in the async shape — list-valued
    entries are joined with ``<br/>`` so the same split-and-normalize
    pipeline handles both.

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
            raw_value = v.get("value")
            if isinstance(raw_value, list):
                # Async shape: list of strings → join into the same
                # <br/>-separated string the config-picker shape uses.
                raw = "<br/>".join(str(item) for item in raw_value if item)
            elif raw_value is None:
                raw = ""
            else:
                raw = str(raw_value)
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


def _extract_async_specs(
    async_techspecs: dict[str, Any] | None,
) -> dict[str, str]:
    """Flatten the async ``pdpTechSpecs.technical_specifications`` array.

    The async array uses the same per-row shape as the config-picker
    array (``{name, tooltip, value: [{value, subheading}]}``), so the
    same flattening helper consumes both. Returns an empty dict when
    ``async_techspecs`` is ``None`` or missing the
    ``technical_specifications`` key.
    """
    if not async_techspecs:
        return {}
    array = async_techspecs.get("technical_specifications") or []
    if not isinstance(array, list):
        return {}
    return _flatten_technical_specs(array)


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


def _rating_from_product_initial(
    product_initial: dict[str, Any], shared: dict[str, Any]
) -> float | None:
    """Coerce ``productInitial.rating`` to float, falling back to JSON-LD."""
    raw = product_initial.get("rating")
    if raw is not None and raw != "":
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    fallback = shared.get("rating")
    if isinstance(fallback, (int, float)):
        return float(fallback)
    return None


def _review_count_from_product_initial(
    product_initial: dict[str, Any], shared: dict[str, Any]
) -> int | None:
    """Coerce ``productInitial.numReviews`` to int, falling back to JSON-LD."""
    raw = product_initial.get("numReviews")
    if raw is not None and raw != "":
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    fallback = shared.get("review_count")
    if isinstance(fallback, int):
        return fallback
    return None


# Recognized video extensions on HP's CDN URLs. STO PDPs include the
# first marketing video alongside the product imagery; we want a still
# image for ``image_url``, not the .mp4.
_VIDEO_EXTS = (".mp4", ".webm", ".mov")


def _first_pdp_image_url(
    pdp_images: dict[str, Any], shared: dict[str, Any]
) -> str | None:
    """Pick a still-image URL from ``pdpImages.fullImages``.

    ``pdpImages.fullImages`` carries clean ``&``-separated URLs (the
    sibling ``productInitialPrice.images`` field has HTML-escaped
    ``&amp;`` strings and is avoided). The list interleaves stills with
    a marketing ``.mp4``; the first non-video URL wins. Falls back to
    JSON-LD ``image`` when ``fullImages`` is empty or all-video.
    """
    full = pdp_images.get("fullImages")
    if isinstance(full, list):
        for entry in full:
            if not isinstance(entry, dict):
                continue
            url = entry.get("url")
            if not isinstance(url, str) or not url:
                continue
            ext = url.rsplit("?", 1)[0].rsplit(".", 1)[-1].lower()
            if f".{ext}" in _VIDEO_EXTS:
                continue
            return url
    fallback = shared.get("image")
    return fallback if isinstance(fallback, str) and fallback else None


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
