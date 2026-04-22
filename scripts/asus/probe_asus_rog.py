"""ASUS ROG spec-page reconnaissance.

``shop.asus.com`` is DataDome-protected — a plain-httpx GET returns a
768-byte 403 carrying a JS captcha challenge (same professional anti-bot
service Amazon and others use). That surface is not viable without paid
bypass services.

**`rog.asus.com/laptops/<line>/<model>/spec/` is 200 OK on plain httpx**
with ~1 MB of SSR'd HTML containing 20+ `<h2>`-headed spec sections:
Operating System, Processor, Graphics, Neural Processor, Display,
Memory, Storage, Expansion Slots, I/O Ports, Keyboard and Touchpad,
Camera, Audio, Network and Communication, Battery, Power Supply,
AURA SYNC, Device Lighting, Weight, Dimensions (W x D x H), Security,
Microsoft Office, Xbox Game Pass, Included in the Box. Each `<h2>` has
class ``ProductSpec__productSpecItemTitle__<hash>`` (CSS module), its
next-sibling `<div>` holds per-SKU-variant rows tagged
``ProductSpec__rowItem__<hash>``. No prices (marketing surface).

This probe:

1. Confirms DataDome negative result on shop.asus.com.
2. Fetches both committed ROG fixtures (Strix G16 2025 + Zephyrus G16 2026).
3. Prints spec-section header outline for each so a maintainer can
   quickly verify the h2-based pattern still holds after a redesign.

Output (under ``tests/tier2/fixtures/asus/``):

- ``rog_strix_g16_2025_spec.html`` — primary fixture.
- ``rog_zephyrus_g16_2026_spec.html`` — generality fixture.

Run from the repo root::

    .venv/Scripts/python.exe scripts/asus/probe_asus_rog.py

See ``docs/ADDING_A_SOURCE.md`` §5 for the decision tree this probe walks.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "tier2" / "fixtures" / "asus"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

SHOP_URL = "https://shop.asus.com/us/90nr0lb1-m000n0-rog-strix-g16-2025.html"

PROBES = [
    (
        "https://rog.asus.com/laptops/rog-strix/rog-strix-g16-2025/spec/",
        "rog_strix_g16_2025_spec",
    ),
    (
        "https://rog.asus.com/laptops/rog-zephyrus/rog-zephyrus-g16-2026/spec/",
        "rog_zephyrus_g16_2026_spec",
    ),
]


def get(url: str) -> httpx.Response:
    return httpx.get(
        url,
        headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
        timeout=30.0,
    )


def analyze(html: str) -> None:
    print(f"  size: {len(html):,} chars")
    m = re.search(r"<title>([^<]+)</title>", html)
    print(f"  title: {m.group(1).strip() if m else '(none)'}")
    h2s = re.findall(
        r'<h2[^>]*class="[^"]*ProductSpec__productSpecItemTitle__[^"]*"[^>]*>'
        r"([^<]{1,120})</h2>",
        html,
    )
    print(f"  spec h2 headings: {len(h2s)}")
    for t in h2s[:24]:
        print(f"    - {t.strip()}")


def main() -> int:
    FIX.mkdir(parents=True, exist_ok=True)

    print(f"[GET shop.asus.com] {SHOP_URL}")
    try:
        r = get(SHOP_URL)
        print(f"  status: {r.status_code} length: {len(r.content)}")
        if b"captcha-delivery.com" in r.content or r.status_code == 403:
            print("  -> DataDome gate detected (expected). shop.asus.com is OFF-LIMITS.")
    except httpx.HTTPError as e:
        print(f"  ERROR: {type(e).__name__}: {e}")

    for url, label in PROBES:
        print(f"\n[GET rog.asus.com] {url}")
        try:
            r = get(url)
        except httpx.HTTPError as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            continue
        print(f"  status: {r.status_code}")
        if r.status_code != 200:
            print("  -> unexpected non-200; ROG pattern may have broken")
            continue
        out = FIX / f"{label}.html"
        out.write_text(r.text, encoding="utf-8")
        print(f"  saved fixture: {out.relative_to(REPO)}")
        analyze(r.text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
