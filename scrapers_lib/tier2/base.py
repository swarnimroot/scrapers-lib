"""Shared spec-extraction helpers for Tier 2 manufacturer fetchers.

Pure-Python parsers plus a thin Playwright wrapper. Each extractor targets a
pattern common across manufacturer sites:

- :func:`parse_product_jsonld` — schema.org ``Product`` JSON-LD.
- :func:`parse_inline_json` — ``<script id="__NEXT_DATA__">`` tags and
  ``window.X = {...};`` assignments.
- :func:`parse_spec_table` — ``<table>`` / ``<dl>`` key-value tables.
- :func:`normalize_spec_value` — whitespace and nbsp cleanup.

Site-specific fetchers (``tier2/dell.py`` etc.) compose these; anything
truly site-specific stays in the fetcher module.

BeautifulSoup is imported lazily inside the parse functions so
``import scrapers_lib`` stays cheap for Tier 1-only consumers. Playwright
is imported lazily by :func:`fetch_rendered_html`.

See ``docs/ARCHITECTURE.md`` §12.2 for how Tier 2 sources slot in.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def _get_soup(html: str) -> Any:
    """Return a BeautifulSoup tree parsed with the stdlib ``html.parser``.

    Lazy import keeps ``import scrapers_lib`` cheap for consumers that never
    touch Tier 2.
    """
    from bs4 import BeautifulSoup  # noqa: I001

    return BeautifulSoup(html, "html.parser")


# ---------------------------------------------------------------------------
# JSON-LD
# ---------------------------------------------------------------------------


def parse_product_jsonld(html: str) -> list[dict[str, Any]]:
    """Extract schema.org ``Product`` objects from JSON-LD script tags.

    Handles three shapes:

    - Single object: ``{"@type": "Product", ...}``
    - Array: ``[{"@type": "Product", ...}, ...]``
    - Graph wrapper: ``{"@graph": [{"@type": "Product", ...}, ...]}``

    Also accepts ``@type`` expressed as a list (e.g. ``["Product",
    "IndividualProduct"]``). Malformed JSON blocks are logged at debug level
    and skipped. Returns an empty list when no ``Product`` objects are found.
    """
    soup = _get_soup(html)
    products: list[dict[str, Any]] = []

    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        payload = tag.string or tag.get_text() or ""
        if not payload.strip():
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            logger.debug("json-ld block skipped (malformed): %s", e)
            continue
        products.extend(_extract_products_from_jsonld(data))

    return products


def _extract_products_from_jsonld(data: Any) -> list[dict[str, Any]]:
    """Walk a JSON-LD value, returning every embedded ``@type: Product`` dict."""
    out: list[dict[str, Any]] = []
    if isinstance(data, list):
        for item in data:
            out.extend(_extract_products_from_jsonld(item))
    elif isinstance(data, dict):
        t = data.get("@type")
        if t == "Product" or (isinstance(t, list) and "Product" in t):
            out.append(data)
        if "@graph" in data:
            out.extend(_extract_products_from_jsonld(data["@graph"]))
    return out


# ---------------------------------------------------------------------------
# Inline JSON (Next.js script tags and window.X assignments)
# ---------------------------------------------------------------------------


def parse_inline_json(
    html: str,
    *,
    script_id: str | None = None,
    window_var: str | None = None,
) -> dict[str, Any] | None:
    """Extract an inline JSON blob from ``html``.

    Exactly one of ``script_id`` or ``window_var`` must be provided:

    - ``script_id`` — content of ``<script id="{script_id}" type="application/json">``.
      The canonical Next.js pattern (``"__NEXT_DATA__"``).
    - ``window_var`` — right-hand side of ``window.{var} = {...};`` or
      ``var {var} = {...};``. Uses balanced-brace walking to handle nested
      structures and braces inside strings.

    Returns ``None`` if the target is not found or parsing fails.
    """
    if (script_id is None) == (window_var is None):
        raise ValueError("provide exactly one of script_id or window_var")

    if script_id is not None:
        return _parse_inline_json_script(html, script_id)
    assert window_var is not None
    return _parse_inline_json_window(html, window_var)


def _parse_inline_json_script(html: str, script_id: str) -> dict[str, Any] | None:
    soup = _get_soup(html)
    tag = soup.find("script", attrs={"id": script_id})
    if tag is None:
        return None
    payload = tag.string or tag.get_text() or ""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        logger.debug("inline json script %r malformed: %s", script_id, e)
        return None
    return data if isinstance(data, dict) else None


_WINDOW_ASSIGN_RE = re.compile(
    r"(?:window\.|var\s+|let\s+|const\s+)?([A-Za-z_$][\w$]*)\s*=\s*(\{)",
)


def _parse_inline_json_window(html: str, var_name: str) -> dict[str, Any] | None:
    for m in _WINDOW_ASSIGN_RE.finditer(html):
        if m.group(1) != var_name:
            continue
        start = m.start(2)
        end = _find_balanced_brace_end(html, start)
        if end is None:
            continue
        try:
            data = json.loads(html[start : end + 1])
        except json.JSONDecodeError as e:
            logger.debug("window.%s payload malformed: %s", var_name, e)
            return None
        return data if isinstance(data, dict) else None
    return None


def _find_balanced_brace_end(text: str, start: int) -> int | None:
    """Index of the ``}`` matching the ``{`` at ``start``, or ``None``.

    String-aware: ignores braces inside JSON strings and handles backslash
    escapes.
    """
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i
    return None


# ---------------------------------------------------------------------------
# Spec tables
# ---------------------------------------------------------------------------


def parse_spec_table(
    html_or_soup: Any,
    *,
    container_selector: str | None = None,
) -> dict[str, str]:
    """Extract key-value pairs from a spec table in ``html_or_soup``.

    Recognizes two patterns:

    - ``<table>`` rows — first ``<th>`` or ``<td>`` is the key, last ``<td>``
      is the value.
    - ``<dl>`` lists — paired ``<dt>`` / ``<dd>`` siblings.

    If ``container_selector`` is given, only content inside the first match
    of that CSS selector is considered (useful when a page has many
    unrelated tables). Values are run through :func:`normalize_spec_value`;
    rows with an empty key or value are skipped. On duplicate keys the first
    occurrence wins; later duplicates are logged at debug level.

    Accepts a raw HTML string or an already-parsed BeautifulSoup object.
    """
    if isinstance(html_or_soup, str):
        soup = _get_soup(html_or_soup)
    else:
        soup = html_or_soup

    if container_selector is not None:
        root = soup.select_one(container_selector)
        if root is None:
            return {}
    else:
        root = soup

    specs: dict[str, str] = {}

    for tr in root.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        key = normalize_spec_value(cells[0].get_text())
        value = normalize_spec_value(cells[-1].get_text())
        _record_spec(specs, key, value)

    for dl in root.find_all("dl"):
        for dt in dl.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if dd is None:
                continue
            key = normalize_spec_value(dt.get_text())
            value = normalize_spec_value(dd.get_text())
            _record_spec(specs, key, value)

    return specs


def _record_spec(specs: dict[str, str], key: str, value: str) -> None:
    if not key or not value:
        return
    if key in specs:
        logger.debug("spec table: duplicate key %r, keeping first value", key)
        return
    specs[key] = value


# ---------------------------------------------------------------------------
# Value normalization
# ---------------------------------------------------------------------------


_WS_RE = re.compile(r"\s+")


def normalize_spec_value(s: str) -> str:
    """Collapse whitespace (including nbsp) and strip leading/trailing space."""
    if not s:
        return ""
    s = s.replace(" ", " ")
    return _WS_RE.sub(" ", s).strip()


# ---------------------------------------------------------------------------
# Rendered HTML fetch (Playwright wrapper)
# ---------------------------------------------------------------------------


def fetch_rendered_html(
    url: str,
    *,
    profiles_dir: str | Path,
    domain: str | None = None,
    wait_selector: str | None = None,
    wait_until: str = "networkidle",
    timeout_ms: int = 30_000,
) -> str:
    """Navigate to ``url`` in a stealth persistent context and return the HTML.

    Wraps :func:`scrapers_lib.core.playwright_base.stealth_context`. When
    ``wait_selector`` is given, waits for that CSS selector after
    navigation — useful for sites whose analytics traffic keeps
    ``networkidle`` from firing. ``domain`` selects the persistent
    profile directory; defaults to the URL's hostname.

    Raises whatever Playwright raises on navigation or selector timeout.
    """
    from scrapers_lib.core.playwright_base import stealth_context  # noqa: I001

    effective_domain = domain or urlparse(url).hostname or "_default"

    with stealth_context(
        profiles_dir=profiles_dir,
        domain=effective_domain,
    ) as page:
        page.goto(url, wait_until=wait_until, timeout=timeout_ms)
        if wait_selector is not None:
            page.wait_for_selector(wait_selector, timeout=timeout_ms)
        return page.content()


# ---------------------------------------------------------------------------
# Warmed curl_cffi session (Akamai / CDN HTTP/2 RST-stream bypass)
# ---------------------------------------------------------------------------

# Implementation graduated to ``scrapers_lib.core.curl_session`` in v1.4.0
# (the helper is now reused by the Tier 1 article fetcher in addition to
# the Tier 2 / Tier 3 callers it served at v1.3.1). Re-exported here so
# existing ``from scrapers_lib.tier2.base import warmed_curl_session``
# imports keep working unchanged.
from scrapers_lib.core.curl_session import warmed_curl_session  # noqa: F401,E402
