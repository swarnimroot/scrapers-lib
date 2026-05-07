"""Evaluate the ASUS www __NUXT__ IIFE via py_mini_racer and inspect state.

Pipeline:

1. Load ``scripts/asus/zenbook_14_ux3405_nuxt.js`` (extracted by
   ``extract_nuxt_iife.py``).
2. Eval it in a fresh ``MiniRacer`` context.
3. Dump the resulting state via ``JSON.stringify(__NUXT__)`` and parse to
   Python.
4. Save the parsed JSON to ``zenbook_14_ux3405_nuxt.json``.
5. Walk top-level + depth-2 keys; recursively look for arrays of objects
   that look like spec rows; print the most likely paths to spec data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from py_mini_racer import MiniRacer

REPO = Path(__file__).resolve().parents[2]
JS_PATH = REPO / "scripts" / "asus" / "zenbook_14_ux3405_nuxt.js"
OUT_JSON = REPO / "scripts" / "asus" / "zenbook_14_ux3405_nuxt.json"


def overview(obj: Any, indent: int = 0, max_depth: int = 2) -> None:
    pad = "  " * indent
    if isinstance(obj, dict):
        keys = list(obj.keys())
        print(f"{pad}<dict, {len(keys)} keys>: {keys[:20]}{' ...' if len(keys) > 20 else ''}")
        if indent < max_depth:
            for k in keys[:30]:
                print(f"{pad}  .{k}:")
                overview(obj[k], indent + 2, max_depth)
    elif isinstance(obj, list):
        print(f"{pad}<list, len={len(obj)}>")
        if obj and indent < max_depth:
            print(f"{pad}  [0]:")
            overview(obj[0], indent + 2, max_depth)
    else:
        s = repr(obj)
        if len(s) > 80:
            s = s[:80] + "..."
        print(f"{pad}{type(obj).__name__}: {s}")


SPEC_KEY_HINTS = (
    "techspec", "techSpec", "TechSpec", "techspecs",
    "specs", "specifications", "spec",
    "specList", "specifications",
)


def find_spec_paths(obj: Any, path: str = "$", hits: list | None = None) -> list:
    if hits is None:
        hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = f"{path}.{k}"
            if any(h.lower() == k.lower() or h.lower() in k.lower() for h in SPEC_KEY_HINTS):
                # Note: include even non-list matches so we can see context.
                if isinstance(v, list):
                    hits.append((new_path, "list", len(v), _list_shape(v)))
                elif isinstance(v, dict):
                    hits.append((new_path, "dict", len(v), list(v.keys())[:8]))
                else:
                    hits.append((new_path, type(v).__name__, None, repr(v)[:60]))
            find_spec_paths(v, new_path, hits)
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:50]):  # cap traversal
            find_spec_paths(item, f"{path}[{i}]", hits)
    return hits


def _list_shape(lst: list) -> Any:
    if not lst:
        return "(empty)"
    sample = lst[0]
    if isinstance(sample, dict):
        return list(sample.keys())[:8]
    return type(sample).__name__


def main() -> int:
    if not JS_PATH.exists():
        print(f"missing {JS_PATH}; run extract_nuxt_iife.py first", file=sys.stderr)
        return 2

    js = JS_PATH.read_text(encoding="utf-8")
    print(f"loaded {JS_PATH.relative_to(REPO)}: {len(js):,} chars")

    ctx = MiniRacer()
    print("evaluating IIFE in MiniRacer...")
    try:
        ctx.eval(js)
    except Exception as e:
        print(f"EVAL FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 3

    print("calling JSON.stringify(__NUXT__)...")
    try:
        dumped = ctx.eval("JSON.stringify(__NUXT__)")
    except Exception as e:
        print(f"STRINGIFY FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 4

    print(f"stringified: {len(dumped):,} chars")
    state = json.loads(dumped)

    OUT_JSON.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(REPO)}: {OUT_JSON.stat().st_size:,} bytes")

    print("\n=== TOP-LEVEL OVERVIEW (depth 2) ===")
    overview(state, max_depth=2)

    print("\n=== SPEC-KEY PATH HITS ===")
    hits = find_spec_paths(state)
    if not hits:
        print("(no spec-key hints matched)")
    else:
        # Dedupe + show.
        seen = set()
        for path, kind, n, shape in hits:
            sig = (path, kind)
            if sig in seen:
                continue
            seen.add(sig)
            print(f"  {path} -> {kind} (n={n})  shape={shape}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
