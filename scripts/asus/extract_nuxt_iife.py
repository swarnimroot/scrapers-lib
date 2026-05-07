"""Locate and extract the __NUXT__ IIFE from a saved ASUS www fixture.

The Zenbook fixture embeds a single ``window.__NUXT__=(function(...){...}(...))``
expression inside a ``<script>`` tag. This script:

1. Reads the saved HTML.
2. Locates the IIFE via a regex anchored on ``window.__NUXT__=(function(``.
3. Walks the source character-by-character to find the matching close-paren
   (regex can't balance parens reliably across ~200 KB of JS).
4. Writes the extracted JS — prefixed with ``var __NUXT__ = `` — to disk so
   py_mini_racer can eval it in isolation.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC_HTML = REPO / "tests" / "tier2" / "fixtures" / "asus_www" / "zenbook_14_ux3405.html"
OUT_JS = REPO / "scripts" / "asus" / "zenbook_14_ux3405_nuxt.js"

# Anchor pattern. The leading ``window.`` is sometimes elided in Nuxt builds,
# so we accept either form.
ANCHOR_RE = re.compile(r"(?:window\.)?__NUXT__\s*=\s*\(function\(")


def find_iife(html: str) -> tuple[int, int, str]:
    """Return (start, end, expression) where expression is the full IIFE
    text starting at the opening ``(`` of ``(function(`` and ending at the
    matching final ``)`` of the call."""
    m = ANCHOR_RE.search(html)
    if not m:
        raise SystemExit("anchor not found: __NUXT__=(function(")
    # The match ends right after the inner "(" of "(function(". We want the
    # opening "(" that precedes "function". That's at m.end() - len("function(")
    # Actually simpler: walk back from m.end() to the last "(" before "function".
    # The captured shape is: __NUXT__=(function(  -> first "(" is right after "=".
    eq_idx = html.index("=", m.start())
    # Skip whitespace after =
    i = eq_idx + 1
    while i < len(html) and html[i].isspace():
        i += 1
    if html[i] != "(":
        raise SystemExit(f"unexpected char at {i}: {html[i]!r}")
    start = i  # position of opening "("
    # Now balance parens, but be careful with strings, regex literals, and
    # comments. Nuxt's serialized IIFE has zero comments and zero regex
    # literals at this level (it's machine-generated). Strings only.
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
                end = j + 1
                return start, end, html[start:end]
        j += 1
    raise SystemExit("unbalanced parens; never closed")


def main() -> int:
    html = SRC_HTML.read_text(encoding="utf-8")
    print(f"loaded {SRC_HTML.relative_to(REPO)}: {len(html):,} chars")

    m = ANCHOR_RE.search(html)
    print(f"anchor match: pos={m.start()}, snippet={html[m.start():m.start()+60]!r}")

    start, end, expr = find_iife(html)
    print(f"IIFE span: [{start}, {end}); inner length = {end - start:,} chars")
    print(f"first 80 chars: {expr[:80]!r}")
    print(f"last  80 chars: {expr[-80:]!r}")

    OUT_JS.parent.mkdir(parents=True, exist_ok=True)
    OUT_JS.write_text("var __NUXT__ = " + expr + ";\n", encoding="utf-8")
    print(f"wrote {OUT_JS.relative_to(REPO)}: {OUT_JS.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
