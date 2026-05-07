"""ASUS www.asus.com (non-ROG) product spec page fetcher.

ASUS publishes consumer + non-ROG gaming spec sheets at
``www.asus.com/<region>/laptops/for-{home,gaming}/<line>/<model>/techspec/``,
covering the Zenbook, Vivobook, and TUF Gaming lines. ROG's marketing
spec pages live at ``rog.asus.com`` and stay with
:mod:`scrapers_lib.tier2.asus`; this module is the sibling for the
``www`` surface.

Unlike ROG, the rendered DOM only renders 1-2 SKU columns at a time
(client-side paginated via ``TechSpec__pagination__*``) — the visible
HTML omits SKU values that fall outside the current page. The full
multi-SKU union lives in a Nuxt SSR state object hidden inside a
``window.__NUXT__=(function(...){...}(...))`` IIFE.

Spec extraction:

1. Locate the IIFE via ``(?:window\\.)?__NUXT__\\s*=\\s*\\(function\\(``.
2. Paren-balance to find the matching close paren (string-state-aware
   walk; regex alone can't balance ~200 KB of nested calls).
3. Evaluate via ``py_mini_racer`` (in-process V8) and stringify back
   to JSON.
4. Read ``state.PDPage.PDTechSpecM2.SpecList`` — list of
   ``{Title, Content}``. ``Content`` is HTML with ``<br>`` / ``<BR>`` /
   ``</br>`` (sic) separators; we strip remaining tags, HTML-decode,
   then dedupe in first-occurrence order.

Anti-bot: open. Plain ``httpx`` reaches the page without DataDome
(unlike ``shop.asus.com``) and without the curl_cffi+HTTP/1.1 dance
HP/BestBuy require. ASUS rotates the Nuxt minified-class hashes
(``TechSpec__*``) on every build, but the JS state-key contract
(``state.PDPage.PDTechSpecM2``) is stable — we extract from the JSON
state, not the rendered DOM.

Granularity is per-model-family (one :class:`ProductSnapshot` per URL).
Multi-SKU option alternatives are embedded inside the spec value as
newline-joined rows, deduplicated in first-occurrence order, matching
the ROG sibling's value shape.

This module is **not directly registered**. ``scrapers_lib.tier2.asus``
host-dispatches ``www.asus.com`` URLs here while keeping
``rog.asus.com`` on its in-module parser; both share ``SOURCE = "asus"``
so a single :class:`Anchor` with ``source_urls={"asus": <url>}`` works
against either surface.
"""

from __future__ import annotations

import html as html_module
import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from scrapers_lib.core.attribution import attribute_url
from scrapers_lib.core.schemas import Anchor, ProductSnapshot
from scrapers_lib.tier2.asus import _jsonld_shared
from scrapers_lib.tier2.base import normalize_spec_value, parse_product_jsonld

logger = logging.getLogger(__name__)

SOURCE = "asus"

# www.asus.com path shape: [/<region>]/laptops/for-{home,gaming}/<line>/<model>/techspec[/]
# Region prefix is asus.com's locale (us, uk, me-en, sa-en, ...).
_PRODUCT_PATH_RE = re.compile(
    r"^(?:/[a-z]{2,3}(?:-[a-z]{2,4})?)?"
    r"/laptops/for-(?:home|gaming)/[a-z0-9-]+/[a-z0-9-]+/techspec/?$"
)

# Nuxt IIFE locator. window. prefix is sometimes elided in Nuxt builds.
_NUXT_ANCHOR_RE = re.compile(r"(?:window\.)?__NUXT__\s*=\s*\(function\(")

# Content cell separators across the three product families:
#   Zenbook / TUF: <br>, <br/>, <br />
#   Vivobook:      </br> (sic — invalid HTML but appears verbatim in state)
_BR_SPLIT_RE = re.compile(r"</?br\s*/?>", re.IGNORECASE)

# Strip residual inline tags (<sup>, <sub>, <span>, ...) from a Content cell
# after br-splitting. Cells contain no nested structures we care about, so a
# blunt tag-stripper is safe and avoids a BeautifulSoup round-trip per cell.
_TAG_STRIP_RE = re.compile(r"<[^>]+>")

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

_CONFIG_SUMMARY_HINTS = ("Graphics", "Memory", "Storage", "Display")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_asus_www_product(
    url: str,
    anchors: list[Anchor] | None = None,
    *,
    timeout: float = 30.0,
    **_: Any,
) -> list[ProductSnapshot]:
    """Fetch a ``www.asus.com`` ``/techspec/`` page; return ``[ProductSnapshot]``.

    Raises :class:`ValueError` on unrecognized URL shape or when no
    anchor in ``anchors`` has ``source_urls["asus"] == url``.
    Raises :class:`RuntimeError` if the Nuxt IIFE can't be located,
    py_mini_racer can't evaluate it, or the resulting state is missing
    its spec list (structural contract break).
    """
    body = _fetch_techspec_page(url, timeout=timeout)
    return parse_asus_www_product_page(body, url, anchors=anchors)


def parse_asus_www_product_page(
    html: str,
    url: str,
    *,
    anchors: list[Anchor] | None = None,
) -> list[ProductSnapshot]:
    """Pure parse: ``www.asus.com`` techspec HTML → one :class:`ProductSnapshot`.

    Walks the Nuxt state's ``PDPage.PDTechSpecM2.SpecList`` and emits each
    ``Title`` as a key in ``specs``, with ``Content`` flattened to a
    newline-joined unique-in-order sequence of per-SKU values.
    """
    attribution = attribute_url(url, SOURCE, anchors or [])
    if attribution is None:
        raise ValueError(
            f"no Anchor has source_urls[{SOURCE!r}] == {url!r}; "
            f"provide one that matches the fetched URL exactly"
        )

    iife = _extract_nuxt_iife(html)
    state = _eval_nuxt(iife)

    specs = _extract_specs(state)
    if not specs:
        raise RuntimeError(
            f"asus_www: state.PDPage.PDTechSpecM2.SpecList yielded no specs at "
            f"{url}; page structure may have changed"
        )

    products_ld = parse_product_jsonld(html)
    shared = _jsonld_shared(products_ld[0] if products_ld else {})

    source_id = _source_id_from_url(url)
    title = (
        shared.get("name")
        or _title_from_state(state)
        or source_id.replace("-", " ")
    ).strip()

    return [
        ProductSnapshot(
            source=SOURCE,
            source_id=source_id,
            variant_key=None,
            anchor_id=attribution.anchor_id,
            url=url,
            title=title,
            # Match the ROG sibling: pin to parent brand for cross-vendor
            # grouping; preserve JSON-LD's claim under raw.
            brand="ASUS",
            config_summary=_config_summary(specs),
            price=shared.get("price_low"),
            list_price=shared.get("price_high") or shared.get("price_low"),
            currency=shared.get("currency") or "USD",
            image_url=shared.get("image"),
            specs=specs,
            raw={
                "spec_source": "www_asus_pd_techspec_m2",
                "product_slug": source_id,
                "jsonld_brand": shared.get("brand"),
            },
        )
    ]


# ---------------------------------------------------------------------------
# URL handling
# ---------------------------------------------------------------------------


def _source_id_from_url(url: str) -> str:
    """Model slug from ``[/<region>]/laptops/for-X/<line>/<model>/techspec/``."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host and "asus.com" not in host:
        raise ValueError(
            f"asus_www: URL host {host!r} is not an asus.com domain"
        )
    path = parsed.path.rstrip("/")
    if not _PRODUCT_PATH_RE.match(path):
        raise ValueError(
            f"asus_www: URL path {path!r} does not match "
            "/laptops/for-{home,gaming}/<line>/<model>/techspec"
        )
    parts = path.split("/")
    # Trailing element is "techspec"; the model slug is the segment before.
    return parts[-2]


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _fetch_techspec_page(url: str, *, timeout: float) -> str:
    """GET the techspec page; return body text."""
    _source_id_from_url(url)  # validate up front; don't waste network on typos
    headers = {
        "User-Agent": _DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    r = httpx.get(url, headers=headers, follow_redirects=True, timeout=timeout)
    r.raise_for_status()
    return r.text


# ---------------------------------------------------------------------------
# Nuxt IIFE extraction + evaluation
# ---------------------------------------------------------------------------


def _extract_nuxt_iife(html: str) -> str:
    """Locate ``__NUXT__=(function(...){...}(...))``; return a JS statement.

    Output is ``var __NUXT__ = (function(...){...}(...));`` — ready to feed
    ``MiniRacer().eval()``. Uses a string-state-aware paren-balancing walk
    because the IIFE source (~200 KB) is too varied for regex-only
    extraction.
    """
    m = _NUXT_ANCHOR_RE.search(html)
    if not m:
        raise RuntimeError(
            "asus_www: __NUXT__=(function(...) anchor not found; "
            "page may not be a Nuxt SSR build"
        )
    eq_idx = html.index("=", m.start())
    i = eq_idx + 1
    while i < len(html) and html[i].isspace():
        i += 1
    if i >= len(html) or html[i] != "(":
        raise RuntimeError(
            f"asus_www: unexpected char after __NUXT__= at offset {i}"
        )
    start = i
    depth = 0
    j = start
    in_str: str | None = None
    while j < len(html):
        c = html[j]
        if in_str is not None:
            if c == "\\":
                j += 2
                continue
            if c == in_str:
                in_str = None
            j += 1
            continue
        if c in ('"', "'"):
            in_str = c
            j += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                end = j + 1
                return "var __NUXT__ = " + html[start:end] + ";"
        j += 1
    raise RuntimeError("asus_www: unbalanced parens in __NUXT__ IIFE")


def _eval_nuxt(js_statement: str) -> dict[str, Any]:
    """Evaluate the Nuxt IIFE in py_mini_racer; return parsed state dict."""
    # Lazy import: keeps `import scrapers_lib` cheap for consumers that
    # never touch ASUS www. Also defers V8 startup cost to first use.
    from py_mini_racer import MiniRacer

    ctx = MiniRacer()
    try:
        ctx.eval(js_statement)
        dumped = ctx.eval("JSON.stringify(__NUXT__)")
    except Exception as e:
        raise RuntimeError(
            f"asus_www: py_mini_racer eval of __NUXT__ IIFE failed: "
            f"{type(e).__name__}: {e}"
        ) from e
    return json.loads(dumped)


# ---------------------------------------------------------------------------
# Spec extraction (pure)
# ---------------------------------------------------------------------------


def _extract_specs(state: dict[str, Any]) -> dict[str, str]:
    """Walk Nuxt state → ``{Title: deduped \\n-joined Content rows}``."""
    pd_page = (state.get("state") or {}).get("PDPage") or {}
    techspec_m2 = pd_page.get("PDTechSpecM2") or {}
    spec_list = techspec_m2.get("SpecList") or []

    out: dict[str, str] = {}
    for entry in spec_list:
        if not isinstance(entry, dict):
            continue
        title = normalize_spec_value(html_module.unescape(entry.get("Title") or ""))
        if not title:
            continue
        content = entry.get("Content") or ""
        rows = _split_content_rows(content)
        if rows and title not in out:
            out[title] = "\n".join(rows)
    return out


def _split_content_rows(content: str) -> list[str]:
    """Split an HTML ``Content`` cell into deduped per-SKU rows.

    Handles the three observed separators (``<br>``, ``<br/>``, ``</br>``
    [sic, Vivobook]). After splitting, residual inline tags (``<sup>``,
    ``<sub>``, ``<span>``) are stripped, HTML entities decoded, whitespace
    collapsed. Empty rows + duplicate rows (first-occurrence order
    preserved) are dropped.
    """
    raw_parts = _BR_SPLIT_RE.split(content)
    seen: set[str] = set()
    rows: list[str] = []
    for part in raw_parts:
        clean = _TAG_STRIP_RE.sub("", part)
        text = normalize_spec_value(html_module.unescape(clean))
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
    return rows


def _title_from_state(state: dict[str, Any]) -> str | None:
    """Pull a marketing title from ``state.PDPage.PDFirstScreen`` if present."""
    pd_page = (state.get("state") or {}).get("PDPage") or {}
    first = pd_page.get("PDFirstScreen") or {}
    name = first.get("Name") or first.get("ProductName")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _config_summary(specs: dict[str, str]) -> str | None:
    """``GPU / RAM / Storage / Display`` summary from each spec's first row.

    First-line-of-each-spec is a slightly different surface than the ROG
    parser's "first variant", but on this surface it conveys the same
    intent — the union value's first item is the lead SKU's value.
    """
    parts: list[str] = []
    seen: set[str] = set()
    for hint in _CONFIG_SUMMARY_HINTS:
        for key, val in specs.items():
            if hint in key and key not in seen:
                first = val.split("\n", 1)[0].strip()
                if first:
                    parts.append(first[:120])
                    seen.add(key)
                    break
    return " / ".join(parts) if parts else None
