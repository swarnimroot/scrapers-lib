"""MSI laptop product fetcher.

MSI publishes laptop spec data from two surfaces on ``us.msi.com``
(regional subdomain — ``www.msi.com`` redirects):

1. **Specification page** ``/Laptop/<ModelSlug>/Specification`` — every
   product line carries this. It is a single SSR'd ``<table>`` with
   column-per-SKU layout: ``thead`` row 0 holds plain SKU names
   (e.g. ``Raider 16 Max HX B2WH-004US``), and ``tbody`` rows have a
   ``<th>`` spec key (CPU, OS, Display, Chipset, Discrete Graphics, ...
   ~27-31 categories per family) plus one ``<td>`` per SKU column.
   We emit one :class:`ProductSnapshot` per SKU column, with
   ``variant_key`` set to the variant SKU code parsed from the column
   header (e.g. ``B2WH-004US``). This is the comprehensive surface and
   the default route for any bare ``/Laptop/<slug>`` URL.
2. **Main product page** ``/Laptop/<ModelSlug>`` — newer AI/Stealth
   product lines embed a schema.org ``ItemList`` JSON-LD block carrying
   ~11 short spec items (Processor, OS, Graphics Card, Display, Battery,
   Audio System, Webcam, Dimensions, AI Features, etc.). One snapshot
   per URL with the highlight spec set. Gaming lines (Raider, Crosshair,
   Vector) ship a Product JSON-LD block but no ``ItemList``. The main
   page is now used only as a graceful fallback when ``/Specification``
   is unreachable (4xx, empty table, or parse failure).

Surface routing in :func:`fetch_msi_product`:

- Explicit ``/Specification`` URL → spec-table path (no change).
- Bare ``/Laptop/<slug>`` URL → fetch ``/Specification`` first
  (universal, comprehensive ~27-field surface). On HTTP error or empty
  parse, fall back to the main page's JSON-LD ``ItemList`` highlight
  summary. This flip ensures premium AI/Stealth SKUs return the full
  per-SKU spec sheet rather than the shorter highlight set when the
  comprehensive surface is reachable.

**Anti-bot.** ``us.msi.com`` is gated by Akamai at the HTTP layer.
Plain ``httpx`` returns 403; trailing-slash toggling does not help. The
fix is the same Wave 2c/2e bypass already used by ``tier3/bestbuy`` and
``tier2/hp``: a ``curl_cffi.requests.Session`` with Chrome impersonation
forced onto HTTP/1.1 plus a homepage warm-up. One warmed session is
reused across every request the fetcher makes (warm → main → spec) so
Akamai cookies ride along.

The full MSI spec table preserves field labels exactly as MSI emits
them — "CPU" stays "CPU", "Discrete Graphics" stays "Discrete
Graphics", "Dimension (WXDXH)" stays "Dimension (WXDXH)". No cross-
manufacturer normalization here; that is a consumer concern.
"""

from __future__ import annotations

import html as html_module
import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

from scrapers_lib.core.attribution import attribute_url
from scrapers_lib.core.registry import register
from scrapers_lib.core.schemas import Anchor, ProductSnapshot
from scrapers_lib.tier2.base import normalize_spec_value, parse_product_jsonld

logger = logging.getLogger(__name__)

SOURCE = "msi"

HOME_URL = "https://us.msi.com/"

# Path shape: /Laptop/<ModelSlug> or /Laptop/<ModelSlug>/Specification.
_LAPTOP_PATH_RE = re.compile(
    r"^/Laptop/(?P<slug>[A-Za-z0-9_-]+)(?:/(?P<surface>Specification))?/?$"
)

# Variant-SKU code at the tail of an MSI product name. Examples:
#   "Raider 16 Max HX B2WH-004US"  -> "B2WH-004US"
#   "Crosshair 16 HX E14WFK-036US" -> "E14WFK-036US"
#   "Stealth 16 AI+ B3WI-039US Copilot+ PC" -> "B3WI-039US"
# The pattern is "<alnum>-NNNUS" at any word position.
_VARIANT_CODE_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+US)\b")

# Config-summary axes shared with the other tier2 fetchers.
_CONFIG_SUMMARY_HINTS_TABLE = ("Discrete Graphics", "Memory", "Storage", "Display")
_CONFIG_SUMMARY_HINTS_ITEMLIST = ("Graphics Card", "Memory", "Storage", "Display")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@register(SOURCE)
def fetch_msi_product(
    url: str,
    anchors: list[Anchor] | None = None,
    *,
    timeout: float = 30.0,
    warm: bool = True,
    impersonate: str = "chrome",
    **_: Any,
) -> list[ProductSnapshot]:
    """Fetch an MSI laptop page; return one or more :class:`ProductSnapshot`.

    The input ``url`` must be of the form
    ``https://us.msi.com/Laptop/<ModelSlug>`` (main page) or
    ``.../Laptop/<ModelSlug>/Specification`` (full spec table).

    Surface selection:

    - ``/Specification`` URL → spec-table path (one snapshot per SKU
      column). Direct route, no fallback.
    - Bare ``/Laptop/<slug>`` URL → fetch ``/Specification`` first
      (universal, comprehensive ~27-field surface). On HTTP error,
      missing table, or empty parse, fall back to the main page's
      JSON-LD ``ItemList`` highlight summary. Both surfaces share the
      same warmed Akamai-bypass session.

    Anti-bot bypass: requests share one warmed
    ``curl_cffi.Session(impersonate="chrome",
    http_version=CurlHttpVersion.V1_1)`` so Akamai cookies established
    by the homepage GET ride along into every product request.

    Attribution uses the URL-map gate: one of ``anchors`` must have
    ``source_urls["msi"] == url``. Raises :class:`ValueError` otherwise.
    """
    slug, surface = _parse_url(url)

    if surface == "Specification":
        spec_html = _fetch_msi_html(
            _spec_url_for_slug(url, slug),
            timeout=timeout,
            warm=warm,
            impersonate=impersonate,
        )
        return parse_msi_specification_page(spec_html, url, anchors=anchors)

    # Bare /Laptop/<slug>: prefer the comprehensive Specification surface,
    # fall back to the main page's ItemList highlight summary if it is
    # unreachable or unparseable.
    spec_url = _spec_url_for_slug(url, slug)
    try:
        spec_html = _fetch_msi_html(
            spec_url,
            timeout=timeout,
            warm=warm,
            impersonate=impersonate,
        )
    except Exception as e:
        logger.info(
            "msi: /Specification fetch failed (%s); falling back to main page",
            e,
        )
    else:
        try:
            snaps = parse_msi_specification_page(spec_html, url, anchors=anchors)
        except RuntimeError as e:
            logger.info(
                "msi: /Specification parse failed (%s); falling back to main page",
                e,
            )
        else:
            if snaps:
                return snaps

    main_html = _fetch_msi_html(
        _main_url_for_slug(url, slug),
        timeout=timeout,
        warm=warm,
        impersonate=impersonate,
    )
    return parse_msi_main_page(main_html, url, anchors=anchors)


def parse_msi_main_page(
    html: str,
    url: str,
    *,
    anchors: list[Anchor] | None = None,
) -> list[ProductSnapshot]:
    """Pure parse: main-page HTML → at most one :class:`ProductSnapshot`.

    Looks for a schema.org ``ItemList`` JSON-LD block. When found,
    flattens its ``itemListElement`` array into ``specs`` (one entry per
    ``ListItem``, key=``name``, value=``description``) and returns a
    single-element list. When no ``ItemList`` is present (gaming lines),
    returns an empty list — the caller is expected to fall through to
    :func:`parse_msi_specification_page`.

    Raises :class:`ValueError` on missing attribution.
    """
    attribution = attribute_url(url, SOURCE, anchors or [])
    if attribution is None:
        raise ValueError(
            f"no Anchor has source_urls[{SOURCE!r}] == {url!r}; "
            f"provide one that matches the fetched URL exactly"
        )

    item_list = _extract_itemlist(html)
    if item_list is None:
        return []

    specs = _flatten_itemlist(item_list)
    if not specs:
        return []

    products_ld = parse_product_jsonld(html)
    shared = _jsonld_shared(products_ld[0] if products_ld else {})

    slug, _surface = _parse_url(url)
    title = (shared.get("name") or slug.replace("-", " ")).strip()

    return [
        ProductSnapshot(
            source=SOURCE,
            source_id=slug,
            variant_key=None,
            anchor_id=attribution.anchor_id,
            url=url,
            title=title,
            brand=shared.get("brand") or "MSI",
            config_summary=_config_summary(specs, _CONFIG_SUMMARY_HINTS_ITEMLIST),
            image_url=shared.get("image"),
            specs=specs,
            raw={
                "spec_source": "jsonld_itemlist",
                "product_slug": slug,
                "itemlist_count": len(specs),
            },
        )
    ]


def parse_msi_specification_page(
    html: str,
    url: str,
    *,
    anchors: list[Anchor] | None = None,
) -> list[ProductSnapshot]:
    """Pure parse: ``/Specification`` HTML → one snapshot per SKU column.

    The page carries a single ``<table>`` whose ``thead`` row 0 lists
    SKU column headers (e.g. ``Raider 16 Max HX B2WH-004US``) and whose
    ``tbody`` rows pair a ``<th>`` spec key with one ``<td>`` value per
    SKU column. We emit one :class:`ProductSnapshot` per SKU column,
    with ``source_id`` set to the full column header text and
    ``variant_key`` set to the trailing SKU code (``B2WH-004US`` etc.).

    Raises :class:`ValueError` on missing attribution. Raises
    :class:`RuntimeError` when no recognizable spec table is found —
    that is a structural contract break (likely an MSI redesign) and
    should surface loudly rather than silently emit an empty list.
    """
    attribution = attribute_url(url, SOURCE, anchors or [])
    if attribution is None:
        raise ValueError(
            f"no Anchor has source_urls[{SOURCE!r}] == {url!r}; "
            f"provide one that matches the fetched URL exactly"
        )

    from bs4 import BeautifulSoup  # noqa: I001

    soup = BeautifulSoup(html, "html.parser")
    table = _find_spec_table(soup)
    if table is None:
        raise RuntimeError(
            f"msi: no recognizable spec <table> on {url}; "
            f"page structure may have changed"
        )

    headers = _extract_variant_headers(table)
    if not headers:
        raise RuntimeError(
            f"msi: spec table at {url} has no SKU column headers"
        )

    rows = _extract_spec_rows(table, n_variants=len(headers))
    if not rows:
        raise RuntimeError(
            f"msi: spec table at {url} has no <tbody> spec rows"
        )

    products_ld = parse_product_jsonld(html)
    shared = _jsonld_shared(products_ld[0] if products_ld else {})
    slug, _surface = _parse_url(url)

    snapshots: list[ProductSnapshot] = []
    for col_idx, header_text in enumerate(headers):
        per_specs: dict[str, str] = {}
        for key, values in rows:
            value = values[col_idx] if col_idx < len(values) else ""
            if key and value:
                per_specs.setdefault(key, value)
        if not per_specs:
            continue

        variant_code = _extract_variant_code(header_text)
        snapshots.append(
            ProductSnapshot(
                source=SOURCE,
                source_id=header_text or f"{slug}#{col_idx}",
                variant_key=variant_code,
                anchor_id=attribution.anchor_id,
                url=url,
                title=header_text or shared.get("name") or slug.replace("-", " "),
                brand=shared.get("brand") or "MSI",
                config_summary=_config_summary(
                    per_specs, _CONFIG_SUMMARY_HINTS_TABLE
                ),
                image_url=shared.get("image"),
                specs=per_specs,
                raw={
                    "spec_source": "specification_table",
                    "product_slug": slug,
                    "variant_header": header_text,
                    "variant_index": col_idx,
                    "variant_count": len(headers),
                },
            )
        )

    if not snapshots:
        raise RuntimeError(
            f"msi: spec table at {url} parsed into zero snapshots"
        )
    return snapshots


# ---------------------------------------------------------------------------
# URL handling
# ---------------------------------------------------------------------------


def _parse_url(url: str) -> tuple[str, str | None]:
    """Return ``(slug, surface)`` for an MSI laptop URL.

    ``surface`` is ``"Specification"`` for ``/Specification`` URLs,
    ``None`` for bare ``/Laptop/<slug>`` URLs.

    Raises :class:`ValueError` on host mismatch or path shape mismatch
    so the fetcher fails fast rather than burning a network round-trip
    on an obvious user error.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host and "msi.com" not in host:
        raise ValueError(
            f"msi: URL host {host!r} is not an msi.com domain; "
            f"pass a us.msi.com/Laptop/<slug> URL"
        )
    if host and not host.startswith("us."):
        # MSI's regional subdomains exist (de.msi.com etc.); for now we
        # only support us.msi.com because the recon was done there.
        # Soft warning so a regional URL doesn't fail silently.
        logger.info("msi: non-US host %r — fetcher tested only on us.msi.com", host)
    m = _LAPTOP_PATH_RE.match(parsed.path)
    if not m:
        raise ValueError(
            f"msi: URL path {parsed.path!r} is not /Laptop/<slug>[/Specification]"
        )
    return m.group("slug"), m.group("surface")


def _main_url_for_slug(url: str, slug: str) -> str:
    """Strip ``/Specification`` and any trailing slash to get the main-page URL."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/Laptop/{slug}"


def _spec_url_for_slug(url: str, slug: str) -> str:
    """Append ``/Specification`` to get the per-SKU spec-table URL."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/Laptop/{slug}/Specification"


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _fetch_msi_html(
    url: str,
    *,
    timeout: float,
    warm: bool,
    impersonate: str,
) -> str:
    """Fetch ``url`` through a warmed ``curl_cffi`` + Chrome + HTTP/1.1 session.

    MSI's Akamai gate drops plain httpx at the HTTP/2 frame layer
    (same shape BestBuy and HP fight). HTTP/1.1 + Chrome impersonation
    + a homepage warm-up to seat cookies clears the gate cleanly.

    ``curl_cffi`` is imported lazily so ``import scrapers_lib`` stays
    cheap for consumers that never touch Tier 2.
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
                logger.debug("msi: warm failed: %s", e)

        r = s.get(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": HOME_URL,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        return r.text


# ---------------------------------------------------------------------------
# JSON-LD ItemList extraction (pure)
# ---------------------------------------------------------------------------


def _extract_itemlist(html: str) -> dict[str, Any] | None:
    """Return the first schema.org ``ItemList`` JSON-LD object in ``html``.

    Returns ``None`` when no ``ItemList`` block is present (gaming lines)
    or every block fails to parse. Malformed blocks are logged at debug
    level and skipped — not all MSI pages embed an ``ItemList``, and
    the absence is meaningful (drives the spec-table fall-through).
    """
    from bs4 import BeautifulSoup  # noqa: I001

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        payload = tag.string or tag.get_text() or ""
        if not payload.strip():
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            logger.debug("msi: ld+json block skipped (malformed): %s", e)
            continue
        found = _find_itemlist_in(data)
        if found is not None:
            return found
    return None


def _find_itemlist_in(data: Any) -> dict[str, Any] | None:
    """Walk a JSON-LD value, returning the first ``@type: ItemList`` dict."""
    if isinstance(data, list):
        for item in data:
            r = _find_itemlist_in(item)
            if r is not None:
                return r
    elif isinstance(data, dict):
        t = data.get("@type")
        if t == "ItemList" or (isinstance(t, list) and "ItemList" in t):
            return data
        if "@graph" in data:
            r = _find_itemlist_in(data["@graph"])
            if r is not None:
                return r
    return None


def _flatten_itemlist(item_list: dict[str, Any]) -> dict[str, str]:
    """Flatten ``ItemList.itemListElement`` into a ``{name: description}`` dict.

    Preserves first-occurrence order. Drops entries that are missing
    either field. HTML entities are decoded; whitespace is collapsed via
    :func:`normalize_spec_value`.
    """
    out: dict[str, str] = {}
    elements = item_list.get("itemListElement") or []
    if not isinstance(elements, list):
        return out
    for el in elements:
        if not isinstance(el, dict):
            continue
        name = normalize_spec_value(html_module.unescape(str(el.get("name") or "")))
        desc = normalize_spec_value(
            html_module.unescape(str(el.get("description") or ""))
        )
        if not name or not desc:
            continue
        if name not in out:
            out[name] = desc
    return out


# ---------------------------------------------------------------------------
# Spec-table extraction (pure)
# ---------------------------------------------------------------------------


def _find_spec_table(soup: Any) -> Any | None:
    """Return the first ``<table>`` that looks like an MSI spec sheet.

    MSI's spec table carries class ``table-configurations`` (or
    ``table-configurations-noicons``) consistently across product
    families. We accept either; if neither is present, fall back to the
    first ``<table>`` on the page — a defensive last resort against
    class-name churn.
    """
    for cls in ("table-configurations", "table-configurations-noicons"):
        table = soup.find("table", attrs={"class": lambda c: c and cls in c})
        if table is not None:
            return table
    return soup.find("table")


def _extract_variant_headers(table: Any) -> list[str]:
    """Return the per-SKU column header texts from the spec table.

    The first row of ``<thead>`` lists SKU column headers in plain
    ``<td>`` cells; column 0 is a label cell (``"Show the Differences"``
    or empty) and is dropped. Each remaining cell's text is one variant
    SKU header. Empty cells are kept (preserves column alignment with
    spec rows) but are unlikely in practice.
    """
    thead = table.find("thead")
    if thead is None:
        return []
    rows = thead.find_all("tr")
    if not rows:
        return []
    cells = rows[0].find_all(["th", "td"])
    if len(cells) < 2:
        return []
    headers = [_clean_cell_text(c) for c in cells[1:]]
    # Filter trailing empty cells — MSI sometimes pads the row.
    while headers and not headers[-1]:
        headers.pop()
    return headers


def _extract_spec_rows(
    table: Any, *, n_variants: int
) -> list[tuple[str, list[str]]]:
    """Walk ``<tbody>`` rows; return ``[(spec_key, [val_per_sku, ...]), ...]``.

    Each row is expected to start with a ``<th>`` carrying the spec key
    followed by one ``<td>`` per SKU column. Rows whose first cell is
    not a ``<th>`` (defensive: MSI occasionally inserts a non-spec
    promotional row) or whose first cell is empty are skipped.

    The per-SKU value list is right-padded with empty strings to
    ``n_variants`` so callers can index by column safely. Cells are
    text-normalized via :func:`_clean_cell_text`.
    """
    tbody = table.find("tbody")
    if tbody is None:
        return []
    out: list[tuple[str, list[str]]] = []
    for tr in tbody.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        if cells[0].name != "th":
            # Promotional / divider row — skip rather than treating its
            # first <td> as a spec key.
            continue
        key = _clean_cell_text(cells[0])
        if not key:
            continue
        values = [_clean_cell_text(c) for c in cells[1:]]
        # Pad to expected width so col_idx access is always safe.
        if len(values) < n_variants:
            values = values + [""] * (n_variants - len(values))
        out.append((key, values))
    return out


def _clean_cell_text(el: Any) -> str:
    """Extract and normalize one cell's visible text.

    HTML entities decoded; ``<br>`` separators preserved as spaces (the
    table value pipeline keeps everything on a single line so a
    multi-line ``"24 cores ... 24 threads"`` row stays readable).
    Trailing/leading whitespace stripped.
    """
    raw = el.get_text(" ", strip=True)
    return normalize_spec_value(html_module.unescape(raw))


# ---------------------------------------------------------------------------
# Variant-code extraction (pure)
# ---------------------------------------------------------------------------


def _extract_variant_code(header_text: str) -> str | None:
    """Pull the trailing SKU code (e.g. ``B2WH-004US``) from a column header.

    Returns ``None`` when the pattern does not match. Used as
    ``variant_key`` so consumers can group / dedupe by SKU without
    holding the full header string.
    """
    m = _VARIANT_CODE_RE.search(header_text)
    if m is None:
        return None
    return m.group(1)


# ---------------------------------------------------------------------------
# Enrichment helpers (pure)
# ---------------------------------------------------------------------------


def _jsonld_shared(p: dict[str, Any]) -> dict[str, Any]:
    """Pull name / brand / image from a JSON-LD ``Product`` object.

    MSI's ``Product`` JSON-LD typically lacks ``brand`` and ``offers``
    fields; we coerce missing brand to ``None`` and let callers fall
    back to ``"MSI"`` at snapshot construction time.
    """
    out: dict[str, Any] = {"name": p.get("name")}

    brand = p.get("brand")
    if isinstance(brand, dict):
        out["brand"] = brand.get("name")
    elif isinstance(brand, str):
        out["brand"] = brand

    image = p.get("image")
    if isinstance(image, str) and image:
        out["image"] = image
    elif isinstance(image, list) and image and isinstance(image[0], str):
        out["image"] = image[0]

    return out


def _config_summary(
    specs: dict[str, str], hints: tuple[str, ...]
) -> str | None:
    """Short ``GPU / RAM / Storage / Display`` summary from a spec dict.

    ``hints`` are substring keys to look for, in order. The spec-table
    surface uses ``"Discrete Graphics"``; the JSON-LD surface uses
    ``"Graphics Card"``. Substring (not exact) matching keeps the helper
    resilient to small label changes between product lines.
    """
    parts: list[str] = []
    seen: set[str] = set()
    for hint in hints:
        for key, val in specs.items():
            if hint.lower() in key.lower() and key not in seen:
                first_line = val.split("\n", 1)[0].strip()
                if first_line:
                    parts.append(first_line[:120])
                    seen.add(key)
                    break
    return " / ".join(parts) if parts else None
