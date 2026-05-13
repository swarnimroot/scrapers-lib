"""Dell product fetcher.

Dell's product pages SSR three pre-built configuration tiles (per
``[data-oc]`` SKU) and embed a ``data-url`` pointing at Dell's own
``csbapi/unifiedpd/techspecs`` endpoint — the same URL Dell's frontend
hits when the user clicks "Tech Specs." We open one stealth browser
session against ``www.dell.com``, fetch the product page, then call each
tile's techspecs endpoint through the browser's cookie jar (Akamai blocks
direct HTTP). Each endpoint returns a small HTML fragment with ~20 fully
labeled spec rows.

The shape was verified on two unrelated product lines (Alienware Aurora
16X gaming + Dell XPS 16 consumer) before this module was written; the
fetcher reads ``data-url`` values off the page rather than hand-constructing
URLs, so country/segment changes or future API revisions do not require
code changes here.

One :class:`ProductSnapshot` per tile. If a techspecs call fails, that
tile falls back to the six-bullet summary in the product page itself so
the snapshot still ships with best-effort specs — partial success is a
first-class outcome (see ``docs/ARCHITECTURE.md`` §10).
"""

from __future__ import annotations

import logging
import re
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from scrapers_lib.core.attribution import attribute_url
from scrapers_lib.core.playwright_base import stealth_context
from scrapers_lib.core.registry import register
from scrapers_lib.core.schemas import Anchor, ComponentOption, ProductSnapshot
from scrapers_lib.core.scheduler import BlockedError
from scrapers_lib.tier2.base import normalize_spec_value, parse_product_jsonld

logger = logging.getLogger(__name__)

SOURCE = "dell"
HOME_URL = "https://www.dell.com/en-us/"
API_BASE = "https://www.dell.com"
TECHSPECS_PATH_PREFIX = "/csbapi/unifiedpd/techspecs/"

_BLOCK_MARKERS = (
    "<title>access denied",
    "errors.edgesuite",
    "pardon our interruption",
)

_CARD_CLASS_TOKENS = ("offer-card", "card-deck-item")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@register(SOURCE)
def fetch_dell_product(
    url: str,
    anchors: list[Anchor] | None = None,
    *,
    profiles_dir: str | Path = "./.profiles",
    warm: bool = True,
    include_options: bool = False,
    **_: Any,
) -> list[ProductSnapshot]:
    """Fetch a Dell product page; return one :class:`ProductSnapshot` per tile.

    When ``warm`` is true (default), the Dell homepage is loaded first so
    Akamai cookies settle in the persistent profile before the target URL
    is requested. Each tile's ``csbapi/unifiedpd/techspecs`` endpoint is
    called through the same browser context so its cookies ride along.

    When ``include_options`` is true, the fetcher additionally navigates to
    the ``cty/pdp`` configurator page (constructed from the spd-slug + the
    first tile's order code) through the same stealth session and parses
    the hardware-module option menu (Processor / Graphics / Memory /
    Storage / Display / Keyboard / Battery / AC Adapter / OS / OS Language
    Pack). The same options dict is attached to every emitted snapshot —
    the menu is product-line-level, not tile-level. Default ``False`` keeps
    the historical single-navigation behavior.

    Attribution uses the URL-map gate: one of ``anchors`` must have
    ``source_urls["dell"] == url``. Raises :class:`ValueError` otherwise.

    Raises :class:`BlockedError` if the product page appears to be an
    Akamai challenge despite stealth + warming.
    """
    product_html, techspecs_by_oc, configurator_html = _fetch_dell_session(
        url, profiles_dir, warm=warm, include_options=include_options
    )

    if _looks_blocked(product_html):
        raise BlockedError(f"dell: product page appears blocked at {url}")

    configurator_options: dict[str, list[ComponentOption]] | None = None
    if configurator_html is not None:
        try:
            configurator_options = parse_dell_configurator_options(configurator_html)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("dell: configurator parse failed: %s", e)
        if not configurator_options:
            configurator_options = None

    return parse_dell_product_page(
        product_html,
        url,
        anchors=anchors,
        techspecs_html_by_oc=techspecs_by_oc,
        configurator_options=configurator_options,
    )


def parse_dell_product_page(
    html: str,
    url: str,
    *,
    anchors: list[Anchor] | None = None,
    techspecs_html_by_oc: dict[str, str] | None = None,
    configurator_options: dict[str, list[ComponentOption]] | None = None,
) -> list[ProductSnapshot]:
    """Pure parse: product page HTML + optional per-OC techspecs responses → snapshots.

    Spec source priority per tile:
    1. ``techspecs_html_by_oc[oc]`` — rich, ~20 categories.
    2. In-page bullet list — 6 short summary values.

    Shared JSON-LD fields (brand, rating, review count, hero image) are
    pulled once and applied to every emitted snapshot. When
    ``configurator_options`` is provided (typically by ``fetch_dell_product``
    with ``include_options=True``), the same options dict is attached to
    every emitted snapshot — the option menu is product-line-level.
    """
    techspecs = techspecs_html_by_oc or {}

    attribution = attribute_url(url, SOURCE, anchors or [])
    if attribution is None:
        raise ValueError(
            f"no Anchor has source_urls[{SOURCE!r}] == {url!r}; "
            f"provide one that matches the fetched URL exactly"
        )
    anchor_id = attribution.anchor_id

    products = parse_product_jsonld(html)
    shared = _jsonld_shared(products[0] if products else {})

    from bs4 import BeautifulSoup  # noqa: I001

    soup = BeautifulSoup(html, "html.parser")
    tiles = _extract_tiles(soup)
    if not tiles:
        raise RuntimeError(
            f"dell: no configuration tiles found on {url}; "
            f"page structure may have changed"
        )

    snapshots: list[ProductSnapshot] = []
    for tile in tiles:
        oc = tile["oc"]
        api_html = techspecs.get(oc)
        if api_html:
            specs = _parse_techspecs_html(api_html)
            spec_source = "techspecs_api"
        else:
            specs = tile["bullet_specs"]
            spec_source = "tile_bullets"
            logger.warning(
                "dell: tile %s has no techspecs response; falling back to tile bullets",
                oc,
            )

        snapshots.append(
            ProductSnapshot(
                source=SOURCE,
                source_id=oc,
                variant_key=oc,
                anchor_id=anchor_id,
                url=url,
                title=shared.get("name") or tile.get("card_title") or f"Dell {oc}",
                brand=shared.get("brand"),
                config_summary=_config_summary(tile["bullet_specs"]),
                price=tile["price"],
                list_price=tile["list_price"],
                currency="USD",
                rating=shared.get("rating"),
                review_count=shared.get("review_count"),
                image_url=shared.get("image"),
                specs=specs,
                options=configurator_options,
                raw={"spec_source": spec_source},
            )
        )

    return snapshots


# ---------------------------------------------------------------------------
# Session fetch (I/O)
# ---------------------------------------------------------------------------


def _fetch_dell_session(
    url: str,
    profiles_dir: str | Path,
    *,
    warm: bool,
    include_options: bool = False,
) -> tuple[str, dict[str, str], str | None]:
    """Navigate to the product page; call each tile's techspecs endpoint.

    Uses one stealth browser context for everything so Akamai cookies
    acquired during warming and the main fetch apply to the API calls.
    When ``include_options`` is true, also navigates to the ``cty/pdp``
    configurator page within the same context and returns its HTML.
    """
    techspecs: dict[str, str] = {}
    configurator_html: str | None = None

    with stealth_context(profiles_dir=profiles_dir, domain="www.dell.com") as page:
        if warm:
            page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
            time.sleep(3)

        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        time.sleep(4)
        product_html = page.content()

        endpoints = _extract_techspecs_endpoints(product_html)
        logger.info(
            "dell: %s → %d tiles, %d techspecs endpoints",
            url,
            len({p.rsplit("/", 1)[-1] for p in endpoints.values()}),
            len(endpoints),
        )

        ctx = page.context
        for oc, path in endpoints.items():
            api_url = API_BASE + path
            try:
                r = ctx.request.get(
                    api_url,
                    headers={
                        "Accept": "application/json, text/html, */*",
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": url,
                    },
                )
                if r.status == 200:
                    techspecs[oc] = r.text()
                else:
                    logger.warning(
                        "dell: techspecs for %s returned %d", oc, r.status
                    )
            except Exception as e:  # pragma: no cover - network edge cases
                logger.warning("dell: techspecs fetch failed for %s: %s", oc, e)

        if include_options:
            first_oc = next(iter(endpoints), None)
            cto_url = _construct_cto_url(url, first_oc) if first_oc else None
            if cto_url is None:
                logger.warning(
                    "dell: include_options=True but could not derive a cty/pdp URL "
                    "from %s (no tile OC available)",
                    url,
                )
            else:
                try:
                    page.goto(cto_url, wait_until="domcontentloaded", timeout=60_000)
                    time.sleep(4)
                    configurator_html = page.content()
                except Exception as e:  # pragma: no cover - network edge cases
                    logger.warning(
                        "dell: configurator fetch failed for %s: %s", cto_url, e
                    )

    return product_html, techspecs, configurator_html


# ---------------------------------------------------------------------------
# Parsers (pure)
# ---------------------------------------------------------------------------


def _looks_blocked(html: str) -> bool:
    low = html.lower()
    return any(m in low for m in _BLOCK_MARKERS)


_CTO_REWRITE_RE = re.compile(r"^(.*)/shop/[^?#]*?/spd/([^/?#]+)(?:[/?#]|$)")


def _construct_cto_url(shop_url: str, oc: str) -> str | None:
    """Build a ``cty/pdp`` configurator URL from a shop-landing URL + an OC.

    Replaces ``/shop/<category-path>/spd/<spd_slug>`` with
    ``/shop/cty/pdp/spd/<spd_slug>/<oc>``, preserving scheme, host, and
    locale prefix (e.g. ``/en-us``). Returns ``None`` if ``shop_url`` is
    not a recognizable shop-landing URL or ``oc`` is empty.
    """
    if not oc:
        return None
    m = _CTO_REWRITE_RE.match(shop_url)
    if not m:
        return None
    prefix, spd_slug = m.group(1), m.group(2)
    return f"{prefix}/shop/cty/pdp/spd/{spd_slug}/{oc}"


def parse_dell_configurator_options(
    html: str,
) -> dict[str, list[ComponentOption]]:
    """Parse a Dell ``cty/pdp`` configurator page → ``{module: [options]}``.

    Walks every ``div.accordion-box.single-column-accordion`` (one per
    hardware module — Processor, Graphics, Memory, Storage, Display,
    Keyboard, Primary Battery, AC Adapter, Operating System, OS Language
    Pack) and reads each option card's visible label,
    ``data-option-id``, and ``data-status``.

    Module order in the returned dict mirrors the on-page order; option
    order within each module preserves the in-DOM order. Returns an empty
    dict for pages that carry no recognizable configurator modules.

    Software / accessories modules lower on the page (Microsoft 365,
    antivirus, etc.) use a different ``<input type="radio">`` DOM and are
    intentionally not surfaced here.
    """
    from bs4 import BeautifulSoup  # noqa: I001

    soup = BeautifulSoup(html, "html.parser")
    options: dict[str, list[ComponentOption]] = {}

    for box in soup.select("div.accordion-box.single-column-accordion"):
        title_el = box.select_one(".module-title")
        if title_el is None:
            continue
        module_name = normalize_spec_value(title_el.get_text(" ", strip=True))
        if not module_name:
            continue

        module_opts: list[ComponentOption] = []
        seen_ids: set[str] = set()
        for opt in box.select("div.option.detailed-option"):
            label = normalize_spec_value(opt.get_text(" ", strip=True))
            option_id = (opt.get("data-option-id") or "").strip()
            status = (opt.get("data-status") or "").strip()
            if not (label and option_id and status):
                continue
            if option_id in seen_ids:
                continue
            seen_ids.add(option_id)
            module_opts.append(
                ComponentOption(label=label, status=status, option_id=option_id)
            )

        if module_opts and module_name not in options:
            options[module_name] = module_opts

    return options


def _extract_techspecs_endpoints(html: str) -> dict[str, str]:
    """Return ``{oc: path}`` for every ``data-url`` pointing at ``/csbapi/.../techspecs/``.

    Reads the URLs Dell puts on the page directly; does not hand-construct
    them. Trailing-segment SKU is the join key to tile data.
    """
    endpoints: dict[str, str] = {}
    pattern = re.compile(
        rf'data-url=["\']({re.escape(TECHSPECS_PATH_PREFIX)}[^"\']+)["\']'
    )
    for m in pattern.finditer(html):
        path = m.group(1)
        oc = path.rsplit("/", 1)[-1]
        if oc and oc not in endpoints:
            endpoints[oc] = path
    return endpoints


def _jsonld_shared(p: dict[str, Any]) -> dict[str, Any]:
    """Pull the fields we echo into every emitted snapshot from the JSON-LD Product."""
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


def _extract_tiles(soup: Any) -> list[dict[str, Any]]:
    """One dict per distinct ``data-oc`` carried by an offer-card ancestor."""
    seen: set[str] = set()
    tiles: list[dict[str, Any]] = []
    for oc_el in soup.select("[data-oc]"):
        oc = (oc_el.get("data-oc") or "").strip()
        if not oc or oc in seen:
            continue
        card = _walk_to_card_ancestor(oc_el)
        if card is None:
            continue

        price, list_price = _extract_prices(card)
        bullet_specs = _parse_tile_bullets(card)
        title_el = card.select_one("h2, h3, h4")

        tiles.append(
            {
                "oc": oc,
                "price": price,
                "list_price": list_price,
                "bullet_specs": bullet_specs,
                "card_title": (
                    title_el.get_text(" ", strip=True) if title_el else None
                ),
            }
        )
        seen.add(oc)
    return tiles


def _walk_to_card_ancestor(el: Any) -> Any | None:
    """Walk up from an element until we find a container classed as an offer card."""
    cur = el
    for _ in range(15):
        if cur.parent is None:
            return None
        cur = cur.parent
        if not hasattr(cur, "get"):
            continue
        cls = cur.get("class") or []
        if any(any(tok in c for tok in _CARD_CLASS_TOKENS) for c in cls):
            return cur
    return None


_PRICE_RE = re.compile(r"(?:New\s+)?Dell Price\s*\$([0-9,]+\.\d{2})", re.I)
_LIST_PRICE_RE = re.compile(r"Estimated Value\s*\$([0-9,]+\.\d{2})", re.I)


def _extract_prices(card: Any) -> tuple[Decimal | None, Decimal | None]:
    """Parse ``Dell Price $X`` and ``Estimated Value $Y`` from the card text."""
    price_block = card.select_one(".card-price")
    text = (
        price_block.get_text(" ", strip=True)
        if price_block is not None
        else card.get_text(" ", strip=True)
    )
    return _first_decimal(_PRICE_RE, text), _first_decimal(_LIST_PRICE_RE, text)


def _first_decimal(pat: re.Pattern[str], text: str) -> Decimal | None:
    m = pat.search(text)
    if m is None:
        return None
    try:
        return Decimal(m.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def _parse_tile_bullets(card: Any) -> dict[str, str]:
    """Read the 6 spec bullets under a tile; drop the Tech Specs button row."""
    specs: dict[str, str] = {}
    for li in card.find_all("li"):
        text = li.get_text(" | ", strip=True)
        if not text:
            continue
        if text.lower() == "tech specs":
            continue
        if " | " not in text:
            continue
        label, _, value = text.partition(" | ")
        label = normalize_spec_value(label)
        value = normalize_spec_value(value.replace(" | ", ", "))
        if label and value and label not in specs:
            specs[label] = value
    return specs


_INLINE_WS_RE = re.compile(r"[ \t\r\f\v ]+")


def _normalize_multiline(s: str) -> str:
    """Collapse intra-line whitespace (including nbsp), preserve line breaks."""
    if not s:
        return ""
    lines = [_INLINE_WS_RE.sub(" ", line).strip() for line in s.split("\n")]
    return "\n".join(line for line in lines if line)


def _parse_techspecs_html(html: str) -> dict[str, str]:
    """One techspecs API response → ``{label: value}`` dict.

    Each ``<li>`` has a bold label (``.h5``) and one or more ``<p>`` value
    elements. When multiple ``<p>`` are present (e.g. Operating System
    has a "recommendation" preamble), we keep the last one — that is the
    actual value Dell renders.
    """
    from bs4 import BeautifulSoup  # noqa: I001

    soup = BeautifulSoup(html, "html.parser")
    specs: dict[str, str] = {}

    for li in soup.select("ul.specs > li, .specs > li"):
        label_el = li.select_one(".h5, h5")
        if label_el is None:
            continue
        for span in label_el.select("span"):
            span.decompose()
        label = normalize_spec_value(label_el.get_text(" ", strip=True))
        if not label:
            continue

        ps = li.find_all("p")
        if ps:
            value = ps[-1].get_text("\n", strip=True)
        else:
            label_text = label_el.get_text(" ", strip=True)
            value = li.get_text("\n", strip=True).replace(label_text, "", 1)

        value = _normalize_multiline(value)
        if value and label not in specs:
            specs[label] = value

    return specs


def _config_summary(bullet_specs: dict[str, str]) -> str | None:
    """Short human-readable config summary: GPU / RAM / Storage / Display."""
    parts = [
        bullet_specs[k]
        for k in ("Graphics Card", "Memory", "Storage", "Display")
        if k in bullet_specs
    ]
    return " / ".join(parts) if parts else None
