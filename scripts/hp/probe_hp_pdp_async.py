"""HP shop PDP recon — Wave 2e step 1b: replicate the ``/async`` hydration call.

The step-1 probe (``probe_hp_pdp_curlcffi.py``) found that curl_cffi
returns the same content as plain httpx for the HP PDP — the HTTP
layer was never the gate. The Tech Specs section is genuinely client-
side hydrated. Inspecting the saved fixture surfaced one prefetch link::

    <link rel="prefetch"
          href="/us-en/shop/app/api/web/graphql/page/pdp%2F<slug>/async">

That's HP's PDP hydration endpoint. The path is fully derivable from
the input PDP URL — slug is `<basename of PDP URL>`, URL-encoded as
``%2F``.

This probe:

1. Fetches the PDP via curl_cffi + Chrome + HTTP/1.1 + homepage warming
   (so we share the Akamai cookies / session the browser would have).
2. Derives the ``/async`` URL from the PDP URL.
3. GETs the ``/async`` endpoint via the same session, expecting JSON.
4. Inspects the response for Tech Specs section content (Dimensions /
   I/O Ports / Weight / Power supply / Audio / Sensors / Warranty).

Three possible outcomes:

(b1) Async endpoint returns JSON with Tech Specs content → Path #1
     becomes "two-request curl_cffi: initial PDP + async hydration",
     which is still strictly better than Path #2 (no PDF dep, no
     fuzzy SKU→docID bridge).
(b2) Async endpoint requires browser-only headers / token / referer
     we can't synthesize → fall back to Path #2 (QuickSpecs PDF).
(b3) Async endpoint returns 200 but no Tech Specs (some other tab's
     content) → keep digging or accept Path #2.

Run from the repo root::

    .venv/Scripts/python.exe scripts/hp/probe_hp_pdp_async.py
"""

from __future__ import annotations

import json
import re
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import quote, urlparse

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "tier2" / "fixtures" / "hp"

URL = "https://www.hp.com/us-en/shop/pdp/omen-16-inch-gaming-laptop-pc-a58a5av-1"
LABEL = "omen_16_a58a5av_1"
HOME_URL = "https://www.hp.com/"

TECH_SPEC_NEEDLES = [
    "Dimension",
    "I/O",
    "Weight",
    "Power supply",
    "Audio",
    "Sensors",
    "Security",
    "Warranty",
    "Tech Specs",
    "Technical specifications",
    "Battery",
    "Wireless",
    "Webcam",
    "Camera",
    "Pointing device",
]


def derive_async_url(pdp_url: str) -> str:
    parsed = urlparse(pdp_url)
    # PDP path is `/us-en/shop/pdp/<slug>` — extract slug, URL-encode the
    # leading `pdp/` separator as %2F per the prefetch link's shape.
    m = re.match(r"^(/[a-z]{2}-[a-z]{2}/shop)/pdp/([A-Za-z0-9_-]+)/?$", parsed.path)
    if not m:
        raise ValueError(f"PDP path shape unexpected: {parsed.path!r}")
    region_shop = m.group(1)
    slug = m.group(2)
    return f"{parsed.scheme}://{parsed.netloc}{region_shop}/app/api/web/graphql/page/{quote('pdp/' + slug, safe='')}/async"


def main() -> int:
    from curl_cffi import CurlHttpVersion, requests  # noqa: I001

    async_url = derive_async_url(URL)
    print(f"[derive] async URL: {async_url}")

    FIX.mkdir(parents=True, exist_ok=True)

    with requests.Session(
        impersonate="chrome",
        http_version=CurlHttpVersion.V1_1,
    ) as s:
        # Warm — same as PDP probe.
        try:
            print(f"[warm] {HOME_URL}")
            s.get(HOME_URL, timeout=30)
            time.sleep(1)
        except Exception as exc:
            print(f"[warm] WARNING: {type(exc).__name__}: {exc}")

        # Fetch the PDP first so the session has the same cookie state a
        # real browser would when the prefetch fires.
        try:
            print(f"[GET PDP] {URL}")
            r_pdp = s.get(URL, timeout=30)
            print(f"  status: {r_pdp.status_code}, {len(r_pdp.content):,} bytes")
        except Exception as exc:
            print(f"[GET PDP] ERROR: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            return 3

        # Now fire the prefetch URL with browser-shaped headers.
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": URL,
            "X-Requested-With": "XMLHttpRequest",
        }
        try:
            print(f"[GET ASYNC] {async_url}")
            r = s.get(async_url, headers=headers, timeout=30)
        except Exception as exc:
            print(f"[GET ASYNC] ERROR: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            return 3

        print(f"  status: {r.status_code}")
        print(f"  content-type: {r.headers.get('content-type', '(unset)')}")
        print(f"  size: {len(r.content):,} bytes")

        body = r.text
        out_html = FIX / f"{LABEL}_async.json"
        out_html.write_text(body, encoding="utf-8")
        print(f"  saved: {out_html.relative_to(REPO)}")

        if r.status_code != 200:
            head = body[:500]
            print(f"  --- first 500 chars ---\n{head}\n  -----------------------")
            return 2

        # Try parsing as JSON; if it works, dump structural overview.
        try:
            obj = json.loads(body)
            print("\n[JSON parse: OK]")
            if isinstance(obj, dict):
                print(f"  top-level keys: {sorted(obj.keys())}")
            elif isinstance(obj, list):
                print(f"  top-level: list of {len(obj)} items")
                if obj and isinstance(obj[0], dict):
                    print(f"  item[0] keys: {sorted(obj[0].keys())}")
        except json.JSONDecodeError as exc:
            print(f"\n[JSON parse: FAILED — {exc}]")
            print("  body looks like:")
            print(f"  {body[:300]}")
            return 1

        print("\n=== tech-spec needle counts in async body ===")
        flat = body if isinstance(obj, str) else json.dumps(obj)
        scores: dict[str, int] = {}
        for n in TECH_SPEC_NEEDLES:
            cnt = flat.count(n)
            scores[n] = cnt
            print(f"  {n!r}: {cnt}")

        present_distinct = sum(1 for v in scores.values() if v > 0)
        print(f"\nDistinct tech-spec needles present: {present_distinct}/{len(TECH_SPEC_NEEDLES)}")

        if present_distinct >= 5:
            print("\n=== verdict ===")
            print(
                "OUTCOME (b1) — async endpoint carries Tech Specs section content. "
                "Path #1 (revised) is viable: rewrite tier2/hp.py to make TWO "
                "curl_cffi requests per fetch — the existing PDP for the config "
                "picker, then the /async endpoint for Tech Specs — and merge "
                "into the per-tile ProductSnapshot.specs dict. No new deps; "
                "borrows the session pattern from tier3/bestbuy.py."
            )
            return 0

        print("\n=== verdict ===")
        print(
            "OUTCOME (b2/b3) — async endpoint reachable but does NOT obviously "
            "carry the Tech Specs section. Either headers are insufficient or "
            "this endpoint serves a different tab. Inspect the saved JSON "
            "manually before deciding next step."
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
