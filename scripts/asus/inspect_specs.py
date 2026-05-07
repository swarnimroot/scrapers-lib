"""Drill into PDTechSpecM2 + cross-check against rendered DOM.

For each saved fixture under tests/tier2/fixtures/asus_www/:
  * Re-extract the IIFE.
  * Eval via MiniRacer.
  * Pull state.PDPage.PDTechSpecM2.SpecList (or the M2List variant).
  * List all {Title} category names + Content sample sizes.
  * Parse the rendered HTML with BeautifulSoup, count TechSpec__sectionTitle__*
    sections, list their text, compare to JSON titles.
"""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path
from typing import Any

# Force UTF-8 stdout so the printed spec values (which contain trademark
# superscripts, etc.) don't crash on Windows cp1252.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from bs4 import BeautifulSoup
from py_mini_racer import MiniRacer

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "tier2" / "fixtures" / "asus_www"

ANCHOR_RE = re.compile(r"(?:window\.)?__NUXT__\s*=\s*\(function\(")
SECTION_TITLE_CLASS_PREFIX = "TechSpec__rowTableTitle__"
ITEM_NAME_CLASS_PREFIX = "TechSpec__itemName__"
ITEM_CONTENT_CLASS_PREFIX = "TechSpec__itemContent__"


def find_iife(html: str) -> str:
    m = ANCHOR_RE.search(html)
    if not m:
        raise SystemExit("anchor not found")
    eq_idx = html.index("=", m.start())
    i = eq_idx + 1
    while i < len(html) and html[i].isspace():
        i += 1
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
                return html[start : j + 1]
        j += 1
    raise SystemExit("unbalanced parens")


def extract_state(html: str) -> dict:
    js = "var __NUXT__ = " + find_iife(html) + ";"
    ctx = MiniRacer()
    ctx.eval(js)
    return json.loads(ctx.eval("JSON.stringify(__NUXT__)"))


def json_categories(state: dict) -> list[tuple[str, str]]:
    """Return list of (Title, Content_truncated)."""
    pd = state.get("state", {}).get("PDPage", {})
    m2 = pd.get("PDTechSpecM2", {}) or {}
    spec_list = m2.get("SpecList") or []
    out: list[tuple[str, str]] = []
    for entry in spec_list:
        title = entry.get("Title") or ""
        content = entry.get("Content") or ""
        if isinstance(content, list):
            content_text = " | ".join(str(c) for c in content)
        else:
            content_text = str(content)
        out.append((title, content_text))
    return out


def dom_section_titles(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    titles: list[str] = []
    for el in soup.find_all(True):
        cls = el.get("class") or []
        if any(c.startswith(SECTION_TITLE_CLASS_PREFIX) for c in cls):
            t = el.get_text(strip=True)
            if t:
                titles.append(t)
    return titles


def dom_item_pairs(html: str) -> list[tuple[str, str]]:
    """Find pairs of (itemName, itemContent) across the rendered HTML."""
    soup = BeautifulSoup(html, "html.parser")
    pairs: list[tuple[str, str]] = []
    name_nodes = []
    for el in soup.find_all(True):
        cls = el.get("class") or []
        if any(c.startswith(ITEM_NAME_CLASS_PREFIX) for c in cls):
            name_nodes.append(el)
    for nm in name_nodes:
        # find sibling itemContent within same parent (typical layout)
        parent = nm.parent
        if parent is None:
            continue
        content_el = None
        for sib in parent.find_all(True):
            sib_cls = sib.get("class") or []
            if any(c.startswith(ITEM_CONTENT_CLASS_PREFIX) for c in sib_cls):
                content_el = sib
                break
        if content_el is not None:
            pairs.append((nm.get_text(" ", strip=True), content_el.get_text(" ", strip=True)))
    return pairs


HP_GAP_AXES = ("Dimensions", "Weight", "Ports", "I/O Ports", "Audio")


def hp_gap_check(titles: list[str]) -> dict[str, bool]:
    return {
        axis: any(axis.lower() in t.lower() for t in titles) for axis in HP_GAP_AXES
    }


def main() -> int:
    fixtures = sorted(FIX.glob("*.html"))
    if not fixtures:
        print("no fixtures found", file=sys.stderr)
        return 1
    for fx in fixtures:
        print(f"\n========== {fx.name} ==========")
        html = fx.read_text(encoding="utf-8")
        print(f"  size: {len(html):,} chars")

        try:
            state = extract_state(html)
        except Exception as e:
            print(f"  extract_state FAILED: {type(e).__name__}: {e}")
            continue

        cats = json_categories(state)
        print(f"\n  [JSON state] PDTechSpecM2.SpecList: {len(cats)} entries")
        for i, (t, c) in enumerate(cats):
            cshow = c.replace("\n", " ")[:100]
            print(f"    {i:>2}. {t!r:<40}  -> {cshow!r}")

        dom_titles = dom_section_titles(html)
        print(f"\n  [DOM] sectionTitle entries: {len(dom_titles)}")
        for t in dom_titles:
            print(f"    - {t}")

        dom_pairs = dom_item_pairs(html)
        print(f"\n  [DOM] (itemName, itemContent) pairs: {len(dom_pairs)}")
        for nm, ct in dom_pairs[:6]:
            print(f"    * {nm!r:<30} : {ct[:80]!r}")
        if len(dom_pairs) > 6:
            print(f"    ... ({len(dom_pairs) - 6} more)")

        json_titles = [t for t, _ in cats]
        print("\n  [HP gap axes — JSON titles]:")
        for axis, present in hp_gap_check(json_titles).items():
            print(f"    {axis:<14}: {'YES' if present else 'no'}")

        # Cross-check JSON vs DOM titles
        json_lc = {t.lower() for t in json_titles}
        dom_lc = {t.lower() for t in dom_titles}
        only_json = sorted(json_lc - dom_lc)
        only_dom = sorted(dom_lc - json_lc)
        print(f"\n  [Diff] JSON-only titles: {only_json}")
        print(f"  [Diff] DOM-only titles : {only_dom}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
