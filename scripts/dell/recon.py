"""Dell reconnaissance — scroll + network-trace probe.

Fetches a known Alienware product and the first non-Alienware laptop on the
Dell laptops category page, each with stealth + homepage warming. Scrolls
each page to the bottom in increments so any IntersectionObserver-backed
sections have a chance to hydrate. Captures pre-scroll HTML, post-scroll
HTML, and an XHR/fetch URL trace.

Output (under ``tests/tier2/fixtures/dell/``):
- ``<label>_before_scroll.html``
- ``<label>_after_scroll.html``
- ``<label>_xhr_urls.txt``

Run from the repo root::

    .venv/Scripts/python.exe scripts/dell/recon.py

See ``docs/ADDING_A_SOURCE.md`` for the methodology this script implements.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "tier2" / "fixtures" / "dell"
PROFILES = REPO / ".profiles"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
HOME = "https://www.dell.com/en-us/"
AURORA = (
    "https://www.dell.com/en-us/shop/dell-laptops/alienware-16x-aurora-gaming-laptop/"
    "spd/alienware-aurora-ac16251-gaming-laptop"
)
CATEGORY = "https://www.dell.com/en-us/shop/dell-laptops"


def make_context(p):
    return p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILES / "www.dell.com"),
        headless=True,
        user_agent=UA,
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ],
    )


def probe(ctx, url: str, label: str) -> dict:
    """Navigate, capture pre-scroll HTML, scroll to bottom in steps, capture post-scroll HTML."""
    xhr: list[tuple[str, int, str]] = []
    page = ctx.new_page()

    def _on_response(r):
        rt = r.request.resource_type
        if rt in ("xhr", "fetch", "document"):
            try:
                xhr.append((rt, r.status, r.url))
            except Exception:
                pass

    page.on("response", _on_response)

    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    time.sleep(3)
    pre_html = page.content()
    pre_xhr_n = len(xhr)

    # Scroll in increments so IntersectionObservers fire section by section.
    last_h = 0
    for _ in range(30):  # up to 30 scroll steps
        h = page.evaluate("document.body.scrollHeight")
        if h == last_h:
            # Scrolling did not grow the page; stop.
            break
        last_h = h
        y = 0
        step = 700
        while y < h:
            page.evaluate(f"window.scrollTo(0, {y})")
            time.sleep(0.25)
            y += step
        time.sleep(1.5)  # let IOs / XHRs settle after reaching bottom

    time.sleep(3)
    post_html = page.content()

    FIX.mkdir(parents=True, exist_ok=True)
    (FIX / f"{label}_before_scroll.html").write_text(pre_html, encoding="utf-8")
    (FIX / f"{label}_after_scroll.html").write_text(post_html, encoding="utf-8")
    (FIX / f"{label}_xhr_urls.txt").write_text(
        "\n".join(f"{t:8s} {s:3d} {u}" for t, s, u in xhr),
        encoding="utf-8",
    )
    page.close()

    return {
        "url": url,
        "pre_chars": len(pre_html),
        "post_chars": len(post_html),
        "pre_xhr_n": pre_xhr_n,
        "post_xhr_n": len(xhr),
    }


def find_second_product(ctx) -> str | None:
    """Open the Dell laptops category page; return the first non-Aurora SPD URL."""
    page = ctx.new_page()
    try:
        page.goto(CATEGORY, wait_until="domcontentloaded", timeout=60_000)
        time.sleep(4)
        hrefs = page.eval_on_selector_all(
            "a[href*='/spd/']", "els => els.map(e => e.getAttribute('href'))"
        )
        for h in hrefs or []:
            if not h or "alienware-aurora-ac16251" in h:
                continue
            if h.startswith("/"):
                h = "https://www.dell.com" + h
            return h
        return None
    finally:
        page.close()


def analyze_html(html: str) -> dict:
    """Lightweight post-hoc inspection of a saved HTML blob."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    visible = soup.get_text(" ", strip=True)

    # Inspect the tech-specs anchor and its surrounding section
    ts = soup.find(id="tech-specs-anchor")
    ts_section = None
    ts_li_count = 0
    ts_text_len = 0
    ts_tables = 0
    ts_dls = 0
    if ts:
        # Walk up to the nearest sectioning ancestor
        section = ts
        for _ in range(10):
            if section.parent is None:
                break
            section = section.parent
            if section.name in ("section", "article") or "tech-spec" in " ".join(
                section.get("class") or []
            ).lower():
                break
        ts_section = section
        ts_li_count = len(section.find_all("li"))
        ts_tables = len(section.find_all("table"))
        ts_dls = len(section.find_all("dl"))
        ts_text_len = len(section.get_text(" ", strip=True))

    return {
        "total_chars": len(html),
        "visible_chars": len(visible),
        "tech_specs_anchor_found": ts is not None,
        "tech_specs_section_li": ts_li_count,
        "tech_specs_section_tables": ts_tables,
        "tech_specs_section_dls": ts_dls,
        "tech_specs_section_text_chars": ts_text_len,
        "data_oc_distinct": len(set(re.findall(r'data-oc="([^"]+)"', html))),
    }


def interesting_xhrs(path: Path) -> list[str]:
    hits = []
    for line in path.read_text(encoding="utf-8").splitlines():
        low = line.lower()
        if any(
            kw in low
            for kw in ("/spec", "tech-spec", "/config", "/product", "cto", "anav", "pns/")
        ):
            hits.append(line)
    return hits[:30]


def main() -> int:
    with Stealth().use_sync(sync_playwright()) as p:
        ctx = make_context(p)
        try:
            # Warm
            page = ctx.new_page()
            page.goto(HOME, wait_until="domcontentloaded", timeout=60_000)
            time.sleep(2)
            page.close()

            # Probe Aurora
            print("[probe] Aurora 16X (Alienware gaming)")
            aurora = probe(ctx, AURORA, "aurora")
            print(f"  {aurora}")

            # Find a second product from a different product line
            print("[probe] finding a second Dell product...")
            second_url = find_second_product(ctx)
            print(f"  second URL: {second_url}")
            if second_url:
                # Extract a label slug from the URL
                m = re.search(r"/spd/([^/?#]+)", second_url)
                label = (m.group(1) if m else "product2")[:40]
                second = probe(ctx, second_url, label)
                print(f"  {second}")
            else:
                label = None
                second = None
        finally:
            ctx.close()

    # Post-hoc analysis
    print("\n=== analysis ===")
    for lbl in ["aurora_before_scroll", "aurora_after_scroll"]:
        path = FIX / f"{lbl}.html"
        if path.exists():
            print(f"\n[{lbl}]")
            info = analyze_html(path.read_text(encoding="utf-8"))
            for k, v in info.items():
                print(f"  {k}: {v}")

    if label:
        for suffix in ("before_scroll", "after_scroll"):
            path = FIX / f"{label}_{suffix}.html"
            if path.exists():
                print(f"\n[{label}_{suffix}]")
                info = analyze_html(path.read_text(encoding="utf-8"))
                for k, v in info.items():
                    print(f"  {k}: {v}")

    # XHR highlights
    print("\n=== interesting XHRs (Aurora) ===")
    for line in interesting_xhrs(FIX / "aurora_xhr_urls.txt"):
        print(f"  {line}")

    if label:
        print(f"\n=== interesting XHRs ({label}) ===")
        for line in interesting_xhrs(FIX / f"{label}_xhr_urls.txt"):
            print(f"  {line}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
