"""Dell CTO configurator (`cty/pdp`) reconnaissance.

Loads a Configure-To-Order PDP URL, scrolls so any lazy sections render,
and captures:

- ``cto_<oc>_before_scroll.html`` / ``..._after_scroll.html``
- ``cto_<oc>_xhr_urls.txt`` — every XHR/fetch/document URL
- prints a quick on-page inventory: option-card count guesses, category
  label candidates, embedded JSON islands worth a look.

Run from repo root::

    .venv/Scripts/python.exe scripts/dell/recon_configurator.py
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from scrapers_lib.core.playwright_base import stealth_context

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "tier2" / "fixtures" / "dell"
PROFILES = REPO / ".profiles"

HOME = "https://www.dell.com/en-us/"
CTO_URL = (
    "https://www.dell.com/en-us/shop/cty/pdp/spd/"
    "alienware-aurora-ac16250-gaming-laptop/useac16250hbtshtgb"
)
OC = "useac16250hbtshtgb"


def probe(page, url: str, label: str) -> dict:
    xhr: list[tuple[str, int, str]] = []

    def _on_response(r):
        rt = r.request.resource_type
        if rt in ("xhr", "fetch", "document"):
            try:
                xhr.append((rt, r.status, r.url))
            except Exception:
                pass

    page.on("response", _on_response)

    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    time.sleep(4)
    pre_html = page.content()

    last_h = 0
    for _ in range(30):
        h = page.evaluate("document.body.scrollHeight")
        if h == last_h:
            break
        last_h = h
        y = 0
        step = 700
        while y < h:
            page.evaluate(f"window.scrollTo(0, {y})")
            time.sleep(0.25)
            y += step
        time.sleep(1.5)

    time.sleep(2)
    post_html = page.content()

    FIX.mkdir(parents=True, exist_ok=True)
    (FIX / f"{label}_before_scroll.html").write_text(pre_html, encoding="utf-8")
    (FIX / f"{label}_after_scroll.html").write_text(post_html, encoding="utf-8")
    (FIX / f"{label}_xhr_urls.txt").write_text(
        "\n".join(f"{t:8s} {s:3d} {u}" for t, s, u in xhr),
        encoding="utf-8",
    )

    return {
        "url": url,
        "pre_chars": len(pre_html),
        "post_chars": len(post_html),
        "xhr_total": len(xhr),
    }


# ---------------------------------------------------------------------------
# Lightweight HTML inspection — what does the configurator look like?
# ---------------------------------------------------------------------------

CATEGORY_HINTS = (
    "processor",
    "operating system",
    "graphics",
    "memory",
    "storage",
    "display",
    "keyboard",
    "color",
    "warranty",
    "wireless",
    "battery",
    "office",
    "security software",
    "anti-virus",
    "power",
)


def inspect_html(html: str) -> dict:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    info: dict = {
        "total_chars": len(html),
        "data_oc_distinct": len(set(re.findall(r'data-oc="([^"]+)"', html))),
    }

    # Build-your-own / configurator heading
    info["has_build_your_own_text"] = "build your own" in html.lower()
    info["has_view_other_configurations"] = "view other configurations" in html.lower()

    # Candidate option-card containers — try several class-token patterns.
    selector_candidates = [
        "[data-component='configOption']",
        "[data-testid*='option']",
        "[data-testid*='module']",
        ".option-card",
        ".config-option",
        ".commodity-card",
        ".cfg-option",
        "label[for*='module']",
        "label[for*='option']",
        "[role='radio']",
        "input[type='radio']",
    ]
    sel_counts = {}
    for s in selector_candidates:
        try:
            sel_counts[s] = len(soup.select(s))
        except Exception:
            sel_counts[s] = -1
    info["selector_counts"] = sel_counts

    # Category-label scan: which CATEGORY_HINTS appear as headings/labels?
    cat_hits: dict[str, int] = {}
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "legend", "label", "div", "span"]):
        text = tag.get_text(" ", strip=True).lower()
        if not text or len(text) > 60:
            continue
        for hint in CATEGORY_HINTS:
            if hint in text and text.startswith(hint):
                cat_hits[hint] = cat_hits.get(hint, 0) + 1
                break
    info["category_label_hits"] = cat_hits

    # JSON islands: <script type="application/json"> blocks. Show ids/sizes.
    json_islands = []
    for s in soup.find_all("script", attrs={"type": "application/json"}):
        sid = s.get("id") or s.get("data-component") or "<no-id>"
        body = s.string or ""
        json_islands.append((sid, len(body)))
    info["json_islands"] = sorted(json_islands, key=lambda t: -t[1])[:15]

    # window.__INITIAL_STATE__ / __NUXT__ / __NEXT_DATA__ presence
    info["has_initial_state"] = "__INITIAL_STATE__" in html
    info["has_next_data"] = "__NEXT_DATA__" in html
    info["has_nuxt"] = "window.__NUXT__" in html

    return info


def interesting_xhrs(path: Path) -> list[str]:
    hits = []
    keywords = (
        "/cto",
        "/configurator",
        "/config",
        "/anav",
        "/csbapi",
        "/modules",
        "/option",
        "/sku",
        "/spec",
        "/price",
        "pns/",
        "techspecs",
    )
    if not path.exists():
        return hits
    for line in path.read_text(encoding="utf-8").splitlines():
        low = line.lower()
        if any(kw in low for kw in keywords):
            hits.append(line)
    return hits


def main() -> int:
    with stealth_context(profiles_dir=str(PROFILES), domain="www.dell.com") as page:
        # Warm
        page.goto(HOME, wait_until="domcontentloaded", timeout=60_000)
        time.sleep(3)

        label = f"cto_{OC}"
        print(f"[probe] CTO configurator {CTO_URL}")
        result = probe(page, CTO_URL, label)
        print(f"  {result}")

    # Analysis
    print("\n=== analysis (after scroll) ===")
    path = FIX / f"cto_{OC}_after_scroll.html"
    if path.exists():
        info = inspect_html(path.read_text(encoding="utf-8"))
        # Pretty-print
        for k, v in info.items():
            if isinstance(v, (dict, list)):
                print(f"  {k}:")
                print("    " + json.dumps(v, indent=2, default=str).replace("\n", "\n    "))
            else:
                print(f"  {k}: {v}")
    else:
        print(f"  missing: {path}")

    print("\n=== interesting XHRs ===")
    for line in interesting_xhrs(FIX / f"cto_{OC}_xhr_urls.txt"):
        print(f"  {line}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
