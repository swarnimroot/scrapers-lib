"""Side-by-side: JSON state PDTechSpecM2.SpecList vs DOM TechSpec__rowTable rows.

Confirms whether (a) the JSON Content field already contains a clean,
deduplicated value, and (b) the DOM rendering re-uses the same content
or transforms it. Picks one fixture (Zenbook) and prints 4 spec rows
from each surface.
"""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from bs4 import BeautifulSoup
from py_mini_racer import MiniRacer

REPO = Path(__file__).resolve().parents[2]
FX = REPO / "tests" / "tier2" / "fixtures" / "asus_www" / "zenbook_14_ux3405.html"

ANCHOR_RE = re.compile(r"(?:window\.)?__NUXT__\s*=\s*\(function\(")


def find_iife(html: str) -> str:
    m = ANCHOR_RE.search(html)
    eq_idx = html.index("=", m.start())
    i = eq_idx + 1
    while i < len(html) and html[i].isspace():
        i += 1
    start = i
    depth = 0
    j = start
    in_str = None
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
                return html[start : j + 1]
        j += 1
    raise SystemExit("unbalanced")


def main() -> int:
    html = FX.read_text(encoding="utf-8")
    ctx = MiniRacer()
    ctx.eval("var __NUXT__ = " + find_iife(html) + ";")
    state = json.loads(ctx.eval("JSON.stringify(__NUXT__)"))
    json_specs = state["state"]["PDPage"]["PDTechSpecM2"]["SpecList"]

    soup = BeautifulSoup(html, "html.parser")
    # Each rowTable section has one rowTableTitle and one rowTableScroll
    # (containing the rowTableItems). Walk them in document order.
    sections = []
    for el in soup.find_all(True):
        cls = el.get("class") or []
        if any(c.startswith("TechSpec__rowTable__") for c in cls):
            title_el = None
            for d in el.find_all(True):
                d_cls = d.get("class") or []
                if any(c.startswith("TechSpec__rowTableTitle__") for c in d_cls):
                    title_el = d
                    break
            if title_el is None:
                continue
            title = title_el.get_text(" ", strip=True)
            # All text below the title (excluding nested rowTable bits)
            # gives us the rendered value(s).
            content_text = el.get_text(" ", strip=True)
            if content_text.startswith(title):
                content_text = content_text[len(title) :].strip()
            sections.append((title, content_text))

    print(f"JSON specs: {len(json_specs)}")
    print(f"DOM rowTable sections: {len(sections)}")
    print()

    for which in ["Color", "Display", "I/O Ports", "Weight", "Dimensions (W x D x H)"]:
        print(f"--- {which!r} ---")
        j = next((s for s in json_specs if s.get("Title") == which), None)
        d = next((s for s in sections if s[0] == which), None)
        if j is not None:
            content = j.get("Content")
            if isinstance(content, list):
                content = " | ".join(str(c) for c in content)
            print(f"  JSON Content     : {str(content)[:280]!r}")
        else:
            print("  JSON: not found")
        if d is not None:
            print(f"  DOM rendered text: {d[1][:280]!r}")
        else:
            print("  DOM: not found")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
