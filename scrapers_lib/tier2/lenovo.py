"""Lenovo PSREF product fetcher.

Lenovo's Product Specifications Reference site (``psref.lenovo.com``) is a
React SPA wrapping a legacy server-rendered site, and neither surface carries
useful spec content in its initial HTML. Both the SPA bundle and the legacy
page hydrate themselves from the same JSON API. The per-model endpoint
``/api/product/Compare/LoadSpecData`` returns the full structured spec sheet
— 8 top-level categories, 25+ subcategories, nested down to per-SKU
attribute-value rows for each configurable option.

The fetcher extracts the ``ProductKey`` from the input URL, calls the
endpoint over plain HTTPS (no stealth, no persistent session, no Playwright
— PSREF has no bot gating), and flattens the nested SpecData tree into one
:class:`ProductSnapshot` per URL.

Granularity is per-model-family: PSREF publishes one page per model line
(e.g. ``Legion_Pro_7_16AFR10H``) and represents configurable options as
alternatives inside each Feature. This is coarser than Dell's per-tile
snapshots but matches how Lenovo itself partitions its catalog. Multi-option
Features (e.g. two CPU alternatives, three GPU alternatives) are serialized
into the spec value as one alternative per line.

Verified on two unrelated products — Legion Pro 7 16AFR10H (AMD, gaming)
and LOQ 15IRX10 (Intel, entry-level) — which returned identical JSON
structural shape.
"""

from __future__ import annotations

import html
import json
import logging
import re
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from scrapers_lib.core.attribution import attribute_url
from scrapers_lib.core.registry import register
from scrapers_lib.core.schemas import Anchor, ProductSnapshot
from scrapers_lib.tier2.base import normalize_spec_value

logger = logging.getLogger(__name__)

SOURCE = "lenovo"
API_BASE = "https://psref.lenovo.com"
LOADSPECDATA_PATH = "/api/product/Compare/LoadSpecData"

# Matches both /l/Product/<Line>/<Key> (React SPA) and /Product/<Line>/<Key>
# (legacy) forms, with or without trailing query / fragment.
_PRODUCT_PATH_RE = re.compile(r"^(?:/l)?/Product/[^/]+/([^/]+)$")

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@register(SOURCE)
def fetch_lenovo_product(
    url: str,
    anchors: list[Anchor] | None = None,
    *,
    timeout: float = 30.0,
    **_: Any,
) -> list[ProductSnapshot]:
    """Fetch a Lenovo PSREF product page; return one :class:`ProductSnapshot`.

    The input ``url`` may be either form PSREF serves: the React-SPA URL
    (``psref.lenovo.com/l/Product/<Line>/<Key>``) or the legacy URL
    (``psref.lenovo.com/Product/<Line>/<Key>``), with or without the
    ``?tab=spec`` query. The ``ProductKey`` (last path segment) is used
    to call the ``LoadSpecData`` JSON endpoint.

    Attribution uses the URL-map gate: one of ``anchors`` must have
    ``source_urls["lenovo"] == url`` (exact string match). Raises
    :class:`ValueError` otherwise.

    Returns a list with exactly one snapshot on success. The list shape
    matches the registry contract shared with per-SKU fetchers (Dell).
    """
    product_key = _extract_product_key(url)
    body = _fetch_loadspecdata(product_key, timeout=timeout)
    return parse_lenovo_product_page(body, url, anchors=anchors)


def parse_lenovo_product_page(
    response_body: str | bytes,
    url: str,
    *,
    anchors: list[Anchor] | None = None,
) -> list[ProductSnapshot]:
    """Pure parse: ``LoadSpecData`` JSON body → one :class:`ProductSnapshot`.

    Raises :class:`ValueError` on missing attribution or on a payload that
    does not carry a populated ``GeneralSpecData[0]``. Partial success on
    empty ``SpecData`` — a snapshot is still emitted with an empty spec
    dict and a warning is logged (see ``docs/ARCHITECTURE.md`` §10).
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
        outer = json.loads(response_body)
    except json.JSONDecodeError as e:
        raise ValueError(f"lenovo: response body is not valid JSON: {e}") from e

    code = outer.get("code")
    if code != 1:
        raise ValueError(
            f"lenovo: LoadSpecData response code={code!r} (expected 1); "
            f"product key likely unrecognized or endpoint contract changed"
        )

    outer_data = outer.get("data") or {}
    gsd_list = outer_data.get("GeneralSpecData") or []
    if not gsd_list:
        raise ValueError(
            "lenovo: GeneralSpecData empty; product key likely not found"
        )

    general = gsd_list[0]
    product_name = general.get("ProductName") or ""
    product_id = general.get("ProductID") or ""
    classification = outer_data.get("Classification") or None

    # The real spec tree lives inside a JSON-encoded string field.
    spec_json_str = general.get("GeneralSpecJson") or ""
    try:
        spec_json = json.loads(spec_json_str) if spec_json_str else {}
    except json.JSONDecodeError as e:
        logger.warning("lenovo: GeneralSpecJson did not re-parse: %s", e)
        spec_json = {}

    spec_data = spec_json.get("data", {}).get("SpecData") or []
    if not spec_data:
        logger.warning(
            "lenovo: SpecData empty for %s (product_name=%r); emitting snapshot with no specs",
            url,
            product_name,
        )

    specs = _flatten_spec_data(spec_data)

    product_key = _extract_product_key(url)

    # Title must be non-empty per ProductSnapshot validator. Fall back to a
    # ProductKey-derived placeholder if PSREF somehow returned an empty name.
    title = product_name.strip() or product_key.replace("_", " ")

    return [
        ProductSnapshot(
            source=SOURCE,
            source_id=product_key,
            variant_key=None,
            anchor_id=attribution.anchor_id,
            url=url,
            title=title,
            brand="Lenovo",
            category=classification,
            specs=specs,
            raw={
                "spec_source": "loadspecdata",
                "product_key": product_key,
                "product_id": product_id,
                "classification": classification,
            },
        )
    ]


# ---------------------------------------------------------------------------
# URL → ProductKey
# ---------------------------------------------------------------------------


def _extract_product_key(url: str) -> str:
    """Return the PSREF ProductKey (last path segment) from a product URL.

    Accepts both ``/l/Product/<Line>/<Key>`` and ``/Product/<Line>/<Key>``.
    Raises :class:`ValueError` on unrecognized hostnames or path shapes.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host and "psref.lenovo.com" not in host:
        raise ValueError(
            f"lenovo: URL host {host!r} is not psref.lenovo.com; "
            f"pass a PSREF product URL"
        )
    path = parsed.path.rstrip("/")
    m = _PRODUCT_PATH_RE.match(path)
    if m is None:
        raise ValueError(
            f"lenovo: URL path {path!r} does not match "
            f"/(l/)?Product/<Line>/<ProductKey>"
        )
    return unquote(m.group(1))


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _fetch_loadspecdata(product_key: str, *, timeout: float) -> str:
    """Call ``LoadSpecData`` for ``product_key`` and return the response body."""
    params = {"ProductKey": product_key}
    headers = {
        "User-Agent": _DEFAULT_USER_AGENT,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }
    r = httpx.get(
        API_BASE + LOADSPECDATA_PATH,
        params=params,
        headers=headers,
        follow_redirects=True,
        timeout=timeout,
    )
    r.raise_for_status()
    return r.text


# ---------------------------------------------------------------------------
# Spec-tree flattening (pure)
# ---------------------------------------------------------------------------


def _flatten_spec_data(spec_data: list[dict[str, Any]]) -> dict[str, str]:
    """Flatten PSREF's nested SpecData tree into ``{"<L1> > <L2> > <FName>": value}``.

    - Each ``L1`` block (Performance, Design, Connectivity, ...) has a list
      of ``L2`` subcategories.
    - Each ``L2`` has a list of ``Features``; each Feature has an ``FName``.
    - A Feature's value lives under ``FVs[*].FVGs[*].FVGItem[*]`` —
      ``FVs`` enumerates alternative option rows (e.g. two CPU SKUs),
      ``FVGs`` nests rows within one alternative (typically length 1),
      ``FVGItem`` is the list of ``{Att, AttV}`` pairs in that row.
    - A single item with ``Att == "DefaultDescription"`` is prose-style
      and is emitted as ``AttV`` alone (no ``DefaultDescription: ...`` wrapper).
    - Otherwise the row is serialized as ``"<Att>: <AttV>; <Att>: <AttV>"``.
    - Multiple alternatives are joined with ``"\\n"`` so consumers can
      split and parse each option independently.
    - All ``AttV`` values are HTML-entity-decoded (e.g. ``&trade;`` → ``™``)
      and whitespace-normalized.
    """
    out: dict[str, str] = {}
    for l1_block in spec_data:
        l1_name = (l1_block.get("L1") or "").strip()
        for l2_block in l1_block.get("L2") or []:
            l2_name = (l2_block.get("L2") or "").strip()
            for feature in l2_block.get("Features") or []:
                f_name = (feature.get("FName") or "").strip()
                if not (l1_name and l2_name and f_name):
                    continue
                value = _serialize_feature(feature)
                if not value:
                    continue
                key = f"{l1_name} > {l2_name} > {f_name}"
                if key not in out:
                    out[key] = value
    return out


def _serialize_feature(feature: dict[str, Any]) -> str:
    """One Feature → newline-joined alternative strings."""
    alternatives: list[str] = []
    for fv in feature.get("FVs") or []:
        for fvg in fv.get("FVGs") or []:
            items = fvg.get("FVGItem") or []
            rendered = _serialize_fvgitem(items)
            if rendered:
                alternatives.append(rendered)
    return "\n".join(alternatives)


def _serialize_fvgitem(items: list[dict[str, Any]]) -> str:
    """One FVGItem list → a single spec-row string.

    ``[{"Att": "DefaultDescription", "AttV": "..."}]`` is unwrapped to the
    bare value. Other shapes are rendered as ``"Att: AttV; Att: AttV"``.
    """
    cleaned: list[tuple[str, str]] = []
    for item in items:
        att = normalize_spec_value(html.unescape(item.get("Att") or ""))
        val = normalize_spec_value(html.unescape(item.get("AttV") or ""))
        if val:
            cleaned.append((att, val))
    if not cleaned:
        return ""
    if len(cleaned) == 1 and cleaned[0][0] == "DefaultDescription":
        return cleaned[0][1]
    return "; ".join(
        v if not a or a == "DefaultDescription" else f"{a}: {v}"
        for a, v in cleaned
    )
