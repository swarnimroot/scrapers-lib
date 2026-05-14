"""HP shop PDP shape reconnaissance — three observed URL variants.

Current `fetch_hp_product` parses pdpCTOConfiguration.configurations[]
out of the `<div id="data">` blob. Three URL shapes seen in the wild:

  A) AV-code (works today):
     /us-en/shop/pdp/omen-16-inch-gaming-laptop-pc-a58a5av-1
  B) SKU-final (AttributeError ~ hp.py:179 today):
     /us-en/shop/pdp/omen-gaming-laptop-16-ap0097nr
  C) 17.3" AV-code outlier (RuntimeError "no pdpCTOConfiguration.configurations"):
     /us-en/shop/pdp/omen-173-inch-gaming-laptop-pc-a7jp9av-1

For each: fetch via `warmed_curl_session()` (HP needs Chrome
impersonation), persist HTML under tests/tier2/fixtures/hp/, then
walk:
  - HTTP status / size
  - `<div id="data">` JSON presence + slugInfo.components key inventory
  - pdpCTOConfiguration / pdpStaticConfiguration / pdpStockConfiguration
    / pdpDetails / pdpTechSpecs presence + shapes
  - JSON-LD Product
  - inline JSON islands (<script type="application/json">)
  - static spec surfaces (<table>, <dl>, data-* spec hints, "Specifications" headers)

Read-only — no modifications to tier2/hp.py.

Run::
    .venv/Scripts/python.exe scripts/hp/recon_pdp_shapes.py
"""

from __future__ import annotations

import json
import re
import sys
import traceback
from pathlib import Path

from scrapers_lib.core.curl_session import warmed_curl_session
from scrapers_lib.tier2.base import parse_product_jsonld

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "tier2" / "fixtures" / "hp"

HOME_URL = "https://www.hp.com/us-en/"

URLS: list[tuple[str, str]] = [
    (
        "av_a58a5av1",
        "https://www.hp.com/us-en/shop/pdp/omen-16-inch-gaming-laptop-pc-a58a5av-1",
    ),
    (
        "nr_ap0097nr",
        "https://www.hp.com/us-en/shop/pdp/omen-gaming-laptop-16-ap0097nr",
    ),
    (
        "av_a7jp9av1_173",
        "https://www.hp.com/us-en/shop/pdp/omen-173-inch-gaming-laptop-pc-a7jp9av-1",
    ),
]

_STATE_PATTERN = re.compile(
    r'<div\s+id="data"\s+style="display:none"\s*>\s*<!--\s*(\{.*?\})\s*-->\s*</div>',
    re.DOTALL,
)

# `<script type="application/json" ...>{...}</script>` islands.
_JSON_ISLAND_RE = re.compile(
    r'<script[^>]+type="application/(?:ld\+)?json"[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)

_TABLE_OPEN_RE = re.compile(r"<table\b", re.IGNORECASE)
_DL_OPEN_RE = re.compile(r"<dl\b", re.IGNORECASE)
_TR_OPEN_RE = re.compile(r"<tr\b", re.IGNORECASE)


def _summarize_shape(obj: object, depth: int = 0, max_depth: int = 2) -> object:
    """Compact recursive shape preview: dict→{keys: types}, list→[len, sample]."""
    if depth > max_depth:
        if isinstance(obj, dict):
            return f"<dict {len(obj)} keys>"
        if isinstance(obj, list):
            return f"<list {len(obj)} items>"
        return type(obj).__name__
    if isinstance(obj, dict):
        out = {}
        for k, v in list(obj.items())[:25]:
            out[k] = _summarize_shape(v, depth + 1, max_depth)
        if len(obj) > 25:
            out["...trunc..."] = f"+{len(obj) - 25} more"
        return out
    if isinstance(obj, list):
        if not obj:
            return "[]"
        sample = _summarize_shape(obj[0], depth + 1, max_depth)
        return f"[list of {len(obj)}; sample={sample}]"
    if isinstance(obj, str):
        if len(obj) > 80:
            return f"<str {len(obj)} chars: {obj[:60]!r}...>"
        return f"<str {obj!r}>"
    return type(obj).__name__


def _extract_state_json(html: str) -> dict | None:
    m = _STATE_PATTERN.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _walk_components(state: dict) -> dict:
    return (
        (state or {})
        .get("slugInfo", {})
        .get("components", {})
        or {}
    )


def _describe_jsonld(html: str) -> list[dict]:
    products = parse_product_jsonld(html)
    rows: list[dict] = []
    for p in products:
        offers = p.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        agg = p.get("aggregateRating") or {}
        brand = p.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        image = p.get("image")
        if isinstance(image, list):
            image = image[0] if image else None
        rows.append(
            {
                "name": (p.get("name") or "")[:120],
                "brand": brand,
                "image": (image or "") if isinstance(image, str) else None,
                "offer_price": offers.get("price") if isinstance(offers, dict) else None,
                "offer_currency": offers.get("priceCurrency")
                if isinstance(offers, dict)
                else None,
                "rating_value": agg.get("ratingValue") if isinstance(agg, dict) else None,
                "review_count": agg.get("reviewCount") if isinstance(agg, dict) else None,
            }
        )
    return rows


def _scan_json_islands(html: str) -> list[dict]:
    """Find <script type="application/json">{...}</script> blocks.

    Excludes JSON-LD (which parse_product_jsonld already walks); reports
    size + top-level keys so we can spot framework-state alternatives.
    """
    out: list[dict] = []
    for m in _JSON_ISLAND_RE.finditer(html):
        body = m.group(1).strip()
        size = len(body)
        # Skip JSON-LD bodies (covered separately).
        if '"@context"' in body[:200] and "schema.org" in body[:400]:
            continue
        # Try to peek at top-level keys.
        keys: list[str] | str
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                keys = sorted(parsed.keys())[:20]
            elif isinstance(parsed, list):
                keys = f"<list len={len(parsed)}>"
            else:
                keys = f"<{type(parsed).__name__}>"
        except Exception as exc:
            keys = f"<parse error: {type(exc).__name__}>"
        # script tag attributes for context
        tag_start = max(0, m.start() - 200)
        tag_excerpt = html[tag_start:m.start()].rsplit("<script", 1)[-1][:200]
        out.append({"size": size, "top_keys": keys, "tag_attrs": tag_excerpt})
    return out


def _scan_static_spec_surfaces(html: str) -> dict:
    """Count and sample obvious static spec containers."""
    table_count = len(_TABLE_OPEN_RE.findall(html))
    dl_count = len(_DL_OPEN_RE.findall(html))
    tr_count = len(_TR_OPEN_RE.findall(html))

    # Data-* attrs hinting at spec content
    data_attrs = re.findall(
        r'(data-[a-z][a-z0-9-]*(?:spec|feature|product|sku|catentry)[a-z0-9-]*)="',
        html,
        re.IGNORECASE,
    )
    distinct_data_attrs = sorted(set(a.lower() for a in data_attrs))

    # Headings around "Specifications" / "Features" / "What's in the box"
    heading_keywords = [
        "Specifications",
        "Tech Specs",
        "Technical specifications",
        "Features",
        "What's in the box",
        "What's Included",
        "Overview",
    ]
    heading_hits: dict[str, int] = {}
    for kw in heading_keywords:
        pat = re.compile(
            rf"<h[1-4][^>]*>\s*{re.escape(kw)}\s*</h[1-4]>",
            re.IGNORECASE,
        )
        heading_hits[kw] = len(pat.findall(html))

    # Spec card / class hints
    class_hints = {
        "pdpTechSpecs": html.count("pdpTechSpecs"),
        "detailed-specs": html.count("detailed-specs"),
        "tech-specs": html.count("tech-specs"),
        "spec-card": html.count("spec-card"),
        "product-overview": html.count("product-overview"),
        "feature-card": html.count("feature-card"),
        "feature-grid": html.count("feature-grid"),
        "key-features": html.count("key-features"),
    }

    # Look for inline "name:value" spec rows by HP's house style — they
    # sometimes appear as <li><strong>Label</strong>value</li> on simpler
    # PDPs.
    li_strong = re.findall(
        r"<li[^>]*>\s*<strong[^>]*>([^<]{1,60})</strong>([^<]{1,160})</li>",
        html,
    )

    return {
        "table_count": table_count,
        "dl_count": dl_count,
        "tr_count": tr_count,
        "distinct_data_attrs": distinct_data_attrs[:30],
        "data_attr_total": len(data_attrs),
        "heading_hits": heading_hits,
        "class_hints": class_hints,
        "li_strong_pair_count": len(li_strong),
        "li_strong_sample": li_strong[:5],
    }


def _component_inventory(components: dict) -> dict:
    """Top-level inventory of slugInfo.components: name → shape preview."""
    inv: dict = {}
    for k, v in components.items():
        if isinstance(v, dict):
            inv[k] = {"_type": "dict", "_keys": sorted(v.keys())}
        elif isinstance(v, list):
            inv[k] = {"_type": "list", "_len": len(v)}
        else:
            inv[k] = {"_type": type(v).__name__}
    return inv


def _drill_cto(components: dict) -> dict:
    cto = components.get("pdpCTOConfiguration")
    if not isinstance(cto, dict):
        return {"present": False, "raw_type": type(cto).__name__ if cto is not None else "missing"}
    configs = cto.get("configurations")
    return {
        "present": True,
        "top_keys": sorted(cto.keys()),
        "configurations_type": type(configs).__name__,
        "configurations_len": (
            len(configs) if isinstance(configs, (list, dict)) else None
        ),
        "configurations_is_truthy": bool(configs),
        "configurations_preview": _summarize_shape(configs, max_depth=2)
        if configs
        else None,
    }


def _drill_sibling(components: dict, key: str) -> dict | None:
    val = components.get(key)
    if val is None:
        return None
    if isinstance(val, dict):
        return {
            "_type": "dict",
            "top_keys": sorted(val.keys()),
            "shape": _summarize_shape(val, max_depth=2),
        }
    return {"_type": type(val).__name__, "value_preview": str(val)[:200]}


def probe(label: str, url: str, session) -> dict:
    """Fetch one URL, persist HTML, return analysis dict."""
    print(f"\n========== {label} ==========\nGET {url}")
    report: dict = {"label": label, "url": url}

    try:
        r = session.get(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=30.0,
        )
    except Exception as exc:
        print(f"  ERROR during GET: {type(exc).__name__}: {exc}")
        report["error"] = f"{type(exc).__name__}: {exc}"
        return report

    status = r.status_code
    print(f"  status: {status}")
    print(f"  final URL: {r.url}")
    print(f"  content-type: {r.headers.get('content-type', '(unset)')}")

    html = r.text or ""
    print(f"  size: {len(html):,} chars")

    # Save fixture regardless of status code.
    out = FIX / f"recon_{label}.html"
    try:
        out.write_text(html, encoding="utf-8")
        print(f"  saved: {out.relative_to(REPO)}")
    except Exception as exc:
        print(f"  WARN: could not save fixture: {exc}")

    report["status"] = status
    report["final_url"] = str(r.url)
    report["size"] = len(html)
    report["title"] = (
        re.search(r"<title>([^<]+)</title>", html).group(1).strip()
        if re.search(r"<title>([^<]+)</title>", html)
        else None
    )

    # 1. div#data state blob
    state = _extract_state_json(html)
    report["has_div_data"] = state is not None
    if state is None:
        print("  div#data: ABSENT")
        report["components_inventory"] = None
        report["pdpCTOConfiguration"] = None
    else:
        print("  div#data: present")
        components = _walk_components(state)
        inv = _component_inventory(components)
        report["components_inventory"] = inv
        print(f"  slugInfo.components keys ({len(inv)}): {sorted(inv.keys())}")

        report["pdpCTOConfiguration"] = _drill_cto(components)

        # Drill candidate sibling surfaces by name.
        siblings = {}
        for sib in (
            "pdpStaticConfiguration",
            "pdpStockConfiguration",
            "pdpDetails",
            "pdpTechSpecs",
            "pdpProductInfo",
            "pdpProductDetails",
            "pdpHeader",
            "pdpGallery",
            "pdpPricing",
            "pdpRatingsReviews",
            "pdpKeyFeatures",
            "pdpFeatures",
            "pdpOverview",
            "pdpAdditionalInfo",
            "pdpInTheBox",
            "pdpWhatsInTheBox",
        ):
            sib_report = _drill_sibling(components, sib)
            if sib_report is not None:
                siblings[sib] = sib_report
        report["siblings"] = siblings
        if siblings:
            print(f"  recognized siblings present: {sorted(siblings.keys())}")

    # 2. JSON-LD
    ld_rows = _describe_jsonld(html)
    report["jsonld_products"] = ld_rows
    print(f"  JSON-LD Product objects: {len(ld_rows)}")
    for i, row in enumerate(ld_rows):
        print(f"    [{i}] {row}")

    # 3. Inline JSON islands
    islands = _scan_json_islands(html)
    report["json_islands"] = islands
    print(f"  inline <script type=application/json> islands: {len(islands)}")
    for i, isl in enumerate(islands[:6]):
        print(
            f"    [{i}] size={isl['size']:,} keys={isl['top_keys']!r} "
            f"tag_attrs={isl['tag_attrs'][-80:]!r}"
        )

    # 4. Static spec surfaces
    static = _scan_static_spec_surfaces(html)
    report["static_surfaces"] = static
    print("  static spec surfaces:")
    print(f"    <table>: {static['table_count']}  <dl>: {static['dl_count']}  <tr>: {static['tr_count']}")
    print(f"    heading hits: {static['heading_hits']}")
    print(f"    class hints: {static['class_hints']}")
    print(f"    distinct spec-ish data-* attrs ({static['data_attr_total']} total):")
    for a in static["distinct_data_attrs"][:15]:
        print(f"      {a}")
    print(f"    <li><strong>label</strong>value</li> pairs: {static['li_strong_pair_count']}")
    for kv in static["li_strong_sample"]:
        print(f"      {kv[0].strip()!r} -> {kv[1].strip()[:80]!r}")

    return report


def write_summary(reports: list[dict]) -> None:
    """Compact cross-URL summary printed at the end."""
    print("\n\n=================  CROSS-URL SUMMARY  =================")
    for r in reports:
        label = r["label"]
        size = r.get("size")
        status = r.get("status")
        has_data = r.get("has_div_data")
        cto = r.get("pdpCTOConfiguration") or {}
        cto_summary = (
            f"present={cto.get('present')} "
            f"configurations_type={cto.get('configurations_type')} "
            f"len={cto.get('configurations_len')}"
            if cto
            else "n/a"
        )
        sib_keys = sorted((r.get("siblings") or {}).keys())
        ld_n = len(r.get("jsonld_products") or [])
        islands_n = len(r.get("json_islands") or [])
        print(
            f"\n[{label}] status={status} size={size:,} div#data={has_data}\n"
            f"   CTO -> {cto_summary}\n"
            f"   siblings -> {sib_keys}\n"
            f"   jsonld Products={ld_n}  inline json islands={islands_n}"
        )


def main() -> int:
    FIX.mkdir(parents=True, exist_ok=True)
    reports: list[dict] = []

    try:
        with warmed_curl_session(
            HOME_URL, impersonate="chrome", warm=True
        ) as s:
            for label, url in URLS:
                try:
                    reports.append(probe(label, url, s))
                except Exception as exc:
                    print(f"  EXCEPTION while probing {label}: {exc}")
                    traceback.print_exc()
                    reports.append({"label": label, "url": url, "error": str(exc)})
    except Exception as exc:
        print(f"FATAL: could not open warmed session: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 2

    write_summary(reports)

    # Persist machine-readable summary alongside the HTML fixtures.
    summary_path = FIX / "recon_pdp_shapes_summary.json"
    try:
        summary_path.write_text(
            json.dumps(reports, indent=2, default=str), encoding="utf-8"
        )
        print(f"\nsummary written: {summary_path.relative_to(REPO)}")
    except Exception as exc:
        print(f"WARN: could not write summary json: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
