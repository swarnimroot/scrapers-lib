"""HP shop PDP recon — Wave 2e step 1: ``curl_cffi`` + Chrome + HTTP/1.1.

Plain ``httpx`` already returns the HP PDP successfully and the existing
fetcher in ``scrapers_lib/tier2/hp.py`` parses 12 config-picker
categories from the in-page state JSON. The gap is the **Tech Specs**
section (Dimensions / I/O Ports / Weight / Audio / Sensors / Power supply
/ Warranty), which today's response does not contain — those values are
client-side hydrated.

This probe escalates the HTTP path from plain ``httpx`` to ``curl_cffi``
with Chrome impersonation forced onto HTTP/1.1 (the primitive Wave 2c
established for BestBuy's Akamai gate, see
``scrapers_lib/tier3/bestbuy.py::_fetch_pdp``). Goal: discover whether
a "real-browser-shaped" HTTP request unlocks **more** HTML than plain
``httpx`` got — either the Tech Specs section inline, or scaffolding /
hints that point to the hydration XHR.

Three outcomes the verdict maps to (see ``docs/TASKS.md`` § Wave 2e):

(a) Tech Specs section present in the initial HTML → Path #1 alone is
    sufficient; rewrite ``tier2/hp.py`` around a ``_fetch_pdp``-style
    curl_cffi session.
(b) HTTP gate cleared but Tech Specs absent → identify the hydration
    endpoint (look for ``fetch(`` / ``/api/`` / ``data-fetch-url``
    hints in the response) and replicate via the same session in a
    follow-up probe.
(c) Path #1 fails to clear the gate (block markers / non-200 / response
    smaller than the existing httpx baseline) → pivot to Path #2
    (HP QuickSpecs PDF bridge, ``h20195.www2.hp.com``).

Output:

- ``tests/tier2/fixtures/hp/omen_16_a58a5av_1_curlcffi.html`` — raw
  response body. Sits next to the existing httpx fixture
  (``omen_16_a58a5av_1.html``) so the delta is easy to inspect.

Run from the repo root::

    .venv/Scripts/python.exe scripts/hp/probe_hp_pdp_curlcffi.py
"""

from __future__ import annotations

import re
import sys
import time
import traceback
from pathlib import Path

from scrapers_lib.tier2.base import parse_inline_json, parse_product_jsonld

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "tier2" / "fixtures" / "hp"

URL = "https://www.hp.com/us-en/shop/pdp/omen-16-inch-gaming-laptop-pc-a58a5av-1"
LABEL = "omen_16_a58a5av_1"
HOME_URL = "https://www.hp.com/"
BASELINE_FIXTURE = FIX / f"{LABEL}.html"

# Same Akamai-class block markers the BestBuy probe checks, plus HP-shop-
# specific edge-cache and Imperva fallbacks.
BLOCK_MARKERS = [
    ("access denied", re.compile(r"<title>[^<]*access denied", re.I)),
    ("pardon interrupt", re.compile(r"pardon our interruption", re.I)),
    ("akamai edge", re.compile(r"errors\.edgesuite", re.I)),
    ("akamai reference", re.compile(r"reference\s*#[0-9a-f.]+", re.I)),
    ("cf challenge", re.compile(r"cf-chl-|cf-browser-verification", re.I)),
    ("checking browser", re.compile(r"checking your browser", re.I)),
    ("imperva", re.compile(r"imperva|incapsula", re.I)),
]

# Tech-Specs section markers. None of these are unambiguous on their own
# (the words appear in nav / footer / unrelated copy), so the verdict
# uses a count threshold, not single-marker presence.
TECH_SPEC_MARKERS = [
    ("Tech Specs heading", re.compile(r"\bTech\s+Specs\b", re.I)),
    ("Technical Specifications", re.compile(r"\bTechnical\s+Specifications?\b", re.I)),
    ("Dimensions", re.compile(r"\bDimensions\b\s*\(?\s*W", re.I)),  # 'Dimensions (W x D x H)' is HP's house style
    ("I/O Ports", re.compile(r"\bI/O\s+Ports?\b|\bExternal\s+I/O", re.I)),
    ("Weight (lb/kg)", re.compile(r"\bWeight\b[^<]{0,40}(lb|kg|pounds?|kilogram)", re.I)),
    ("Power supply (W)", re.compile(r"\bPower\s+supply\b[^<]{0,80}\bW(att)?s?\b", re.I)),
    ("Audio", re.compile(r"\bAudio\b\s*<", re.I)),  # standalone label, not the word in marketing copy
    ("Sensors", re.compile(r"\bSensors?\b\s*<", re.I)),
    ("Security hardware", re.compile(r"\bSecurity\s+(hardware|features?)\b", re.I)),
    ("Warranty (year)", re.compile(r"\bWarranty\b[^<]{0,80}\byear", re.I)),
]

# State-blob slots used by `tier2/hp.py` and also seen in shop bundles.
HP_STATE_VARS = (
    "__INITIAL_STATE__",
    "__PRELOADED_STATE__",
    "__APOLLO_STATE__",
    "__NEXT_DATA__",
    "dataLayer",
    "digitalData",
)

# XHR / hydration hints. The shop bundle is huge so raw counts are noisy,
# but any HP-domain `/api/` URL or per-category `dataUrl`/`fetchUrl`
# attribute is a strong signal for outcome (b).
XHR_HINTS = [
    ("/api/ paths in body", re.compile(r"https?://[^\s\"']*hp\.com/[^\s\"']*?/api/[^\s\"']+", re.I)),
    ("'fetch(' calls", re.compile(r"\bfetch\s*\(\s*['\"`]", re.I)),
    ("'XMLHttpRequest'", re.compile(r"\bXMLHttpRequest\b", re.I)),
    ("'data-fetch-url'", re.compile(r"\bdata-fetch-url\s*=", re.I)),
    ("'data-spec-endpoint'", re.compile(r"\bdata-spec-endpoint\s*=", re.I)),
    ("'specsUrl'/'techSpecsUrl' keys", re.compile(r'"(?:specs?Url|tech[A-Z][a-zA-Z]*Url)"\s*:', re.I)),
]


def hits(html: str, markers: list[tuple[str, re.Pattern[str]]]) -> dict[str, int]:
    return {name: len(pat.findall(html)) for name, pat in markers}


def state_blob_keys(html: str) -> dict[str, list[str] | None]:
    """For each HP-known state slot: list its top-level keys, or None if absent."""
    out: dict[str, list[str] | None] = {}
    for var in HP_STATE_VARS:
        if var == "__NEXT_DATA__":
            blob = parse_inline_json(html, script_id="__NEXT_DATA__")
        else:
            blob = parse_inline_json(html, window_var=var)
        out[var] = sorted(blob.keys()) if isinstance(blob, dict) else None
    # The HP-specific `<div id="data"><!-- {JSON} --></div>` slot — the
    # one `tier2/hp.py` actually parses today.
    state_pat = re.compile(
        r'<div\s+id="data"\s+style="display:none"\s*>\s*<!--\s*(\{.*?\})\s*-->\s*</div>',
        re.DOTALL,
    )
    m = state_pat.search(html)
    if m:
        try:
            import json
            data = json.loads(m.group(1))
            out['<div id="data"> (HP shop state)'] = sorted(data.keys()) if isinstance(data, dict) else None
        except Exception as exc:
            out['<div id="data"> (HP shop state)'] = [f"<parse error: {exc}>"]
    else:
        out['<div id="data"> (HP shop state)'] = None
    return out


def report_section(name: str, payload: dict) -> None:
    print(f"\n[{name}]")
    for k, v in payload.items():
        print(f"  {k}: {v}")


def analyze(html: str, label: str) -> dict:
    """Return a dict of measurements; also print them."""
    print(f"\n==================  {label}  ==================")
    print(f"size: {len(html):,} chars")

    title_match = re.search(r"<title>([^<]+)</title>", html)
    print(f"<title>: {title_match.group(1).strip() if title_match else '(none)'}")

    block_hits = [n for n, p in BLOCK_MARKERS if p.search(html)]
    print(f"block markers: {block_hits or 'none'}")

    products = parse_product_jsonld(html)
    print(f"json-ld Product objects: {len(products)}")

    techspec_hits = hits(html, TECH_SPEC_MARKERS)
    report_section("tech-spec section markers", techspec_hits)

    xhr_hits = hits(html, XHR_HINTS)
    report_section("xhr / hydration hints", xhr_hits)

    state = state_blob_keys(html)
    print("\n[state blob top-level keys]")
    for var, keys in state.items():
        if keys is None:
            print(f"  {var}: absent")
        else:
            preview = keys[:25]
            more = "" if len(keys) <= 25 else f"  ... (+{len(keys) - 25} more)"
            print(f"  {var}: {len(keys)} keys -> {preview}{more}")

    return {
        "size": len(html),
        "blocks": block_hits,
        "title": title_match.group(1).strip() if title_match else None,
        "techspec_hits": techspec_hits,
        "xhr_hits": xhr_hits,
        "state": state,
    }


def fetch_curlcffi(url: str, *, timeout: float = 30.0) -> str:
    from curl_cffi import CurlHttpVersion, requests  # noqa: I001

    with requests.Session(
        impersonate="chrome",
        http_version=CurlHttpVersion.V1_1,
    ) as s:
        # Warm against the apex; mirrors `tier3/bestbuy.py::_fetch_pdp`.
        try:
            s.get(HOME_URL, timeout=timeout)
            time.sleep(1)
        except Exception as exc:  # warming is best-effort
            print(f"[warm] WARNING: {type(exc).__name__}: {exc}")

        r = s.get(url, timeout=timeout)
        print(f"[GET] {url}")
        print(f"  status: {r.status_code}")
        print(f"  final URL: {r.url}")
        print(f"  content-type: {r.headers.get('content-type', '(unset)')}")
        r.raise_for_status()
        return r.text


def verdict(curlcffi: dict, baseline: dict | None) -> tuple[int, str]:
    """Return (exit_code, verdict_string) — 0 (a), 1 (b), 2 (c)."""
    if curlcffi["blocks"]:
        return 2, (
            f"OUTCOME (c) — curl_cffi response carries block markers "
            f"({curlcffi['blocks']}). HP's gate is NOT in the same class "
            f"as BestBuy's. Pivot to Path #2 (QuickSpecs PDF bridge)."
        )

    techspec_score = sum(1 for v in curlcffi["techspec_hits"].values() if v > 0)
    xhr_score = sum(1 for v in curlcffi["xhr_hits"].values() if v > 0)

    if baseline is not None:
        baseline_techspec_score = sum(1 for v in baseline["techspec_hits"].values() if v > 0)
        delta_size = curlcffi["size"] - baseline["size"]
        delta_techspec = techspec_score - baseline_techspec_score
    else:
        baseline_techspec_score = None
        delta_size = None
        delta_techspec = None

    # >=4 distinct tech-spec section markers is a strong signal that the
    # whole section is rendered inline — Dimensions+I/O+Weight+Warranty
    # (or any 4 of the 10) is unambiguous.
    if techspec_score >= 4:
        suffix = ""
        if delta_techspec is not None and delta_techspec > 0:
            suffix = (
                f" curl_cffi delta vs httpx baseline: +{delta_techspec} "
                f"tech-spec markers, {delta_size:+,} bytes."
            )
        return 0, (
            f"OUTCOME (a) — Tech Specs section present in initial HTML "
            f"({techspec_score}/10 markers).{suffix} Proceed with Path #1: "
            f"rewrite tier2/hp.py to use a curl_cffi `_fetch_pdp` session "
            f"(borrow from scrapers_lib/tier3/bestbuy.py)."
        )

    if baseline is not None and curlcffi["size"] <= baseline["size"] + 1024 and delta_techspec == 0:
        return 2, (
            f"OUTCOME (c) — curl_cffi response is the same size as the "
            f"plain-httpx baseline ({delta_size:+,} bytes) and shows no "
            f"new tech-spec markers. The HTTP layer was never the gate; "
            f"swapping clients delivers no new content. Pivot to Path #2 "
            f"(QuickSpecs PDF bridge)."
        )

    # Got past the gate (no block markers), got more bytes than baseline,
    # but Tech Specs section not inline → hydration endpoint exists.
    return 1, (
        f"OUTCOME (b) — gate cleared (no block markers, status 200) but "
        f"Tech Specs section is absent or partial "
        f"({techspec_score}/10 markers; baseline was "
        f"{baseline_techspec_score}/10). XHR hints found: {xhr_score}. "
        f"Next step: write a follow-up probe that grep's the saved fixture "
        f"for hydration endpoints and replicates the call via the same "
        f"curl_cffi session."
    )


def main() -> int:
    FIX.mkdir(parents=True, exist_ok=True)

    # Baseline from existing httpx fixture (if present) so the verdict
    # can quote a delta rather than just absolute counts.
    baseline_data = None
    if BASELINE_FIXTURE.exists():
        baseline_html = BASELINE_FIXTURE.read_text(encoding="utf-8")
        baseline_data = analyze(baseline_html, f"BASELINE httpx ({BASELINE_FIXTURE.name})")
    else:
        print(f"[baseline] no existing httpx fixture at {BASELINE_FIXTURE}; "
              f"verdict will use absolute scores only")

    print("\n--------------- curl_cffi fetch ---------------")
    try:
        html = fetch_curlcffi(URL)
    except Exception as exc:
        print(f"ERROR during curl_cffi fetch: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 3

    out = FIX / f"{LABEL}_curlcffi.html"
    out.write_text(html, encoding="utf-8")
    print(f"saved: {out.relative_to(REPO)}")

    curlcffi_data = analyze(html, f"curl_cffi response ({out.name})")

    code, msg = verdict(curlcffi_data, baseline_data)
    print("\n=== verdict ===")
    print(msg)
    return code


if __name__ == "__main__":
    sys.exit(main())
