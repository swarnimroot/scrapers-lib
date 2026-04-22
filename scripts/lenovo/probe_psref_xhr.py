"""Lenovo PSREF reconnaissance — probe 2: XHR trace of the hydrated SPA.

Probe 1 (``probe_psref.py``) established that PSREF returns a React SPA shell
to plain httpx with no bot gate. This probe hydrates the page in a vanilla
headless Chromium (no stealth, no persistent profile — probe 1 proved those
aren't needed) and captures every XHR/fetch/document response so we can find
the data endpoint the bundle calls.

Output (under ``tests/tier2/fixtures/lenovo/``):

- ``legion_pro_7_16afr10h_rendered.html`` — post-hydration ``page.content()``.
- ``legion_pro_7_16afr10h_xhr_urls.txt`` — full trace (type / status /
  content-type / content-length / URL) of every captured response.
- ``xhr_body_NNN_<slug>.{json,html,bin}`` — response bodies for XHRs whose
  URL mentions ``spec``/``product``/``api``/the model slug, or whose
  content-type is ``application/json``. Capped at 15.

Stdout reports the trace summary, the highlighted subset, a rendered-DOM
structural analysis, and a 1-line verdict pointing at the next recon step.

Run from the repo root::

    .venv/Scripts/python.exe scripts/lenovo/probe_psref_xhr.py

See ``docs/ADDING_A_SOURCE.md`` §3 (technique catalog) and §5 (decision tree).
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from scrapers_lib.tier2._base import parse_inline_json, parse_product_jsonld

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "tier2" / "fixtures" / "lenovo"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

URL = "https://psref.lenovo.com/l/Product/Legion/Legion_Pro_7_16AFR10H?tab=spec"
LABEL = "legion_pro_7_16afr10h"
MODEL_SLUG = "Legion_Pro_7_16AFR10H"

HIGHLIGHT_KEYWORDS = ("spec", "product", "api", MODEL_SLUG.lower())
BODY_LIMIT = 40


def is_interesting(url: str, content_type: str) -> bool:
    u = url.lower()
    if any(k in u for k in HIGHLIGHT_KEYWORDS):
        return True
    if "application/json" in content_type.lower():
        return True
    return False


def short_slug_from_url(url: str) -> str:
    parsed = urlparse(url)
    tail = parsed.path.rstrip("/").split("/")[-1] or "root"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", tail)
    return slug[:50] or "root"


def ext_for(content_type: str) -> str:
    ct = content_type.lower()
    if "json" in ct:
        return "json"
    if "html" in ct:
        return "html"
    return "bin"


def analyze_rendered(html: str) -> None:
    print("\n--- rendered DOM analysis ---")
    print(f"size: {len(html):,} chars")
    m = re.search(r"<title>([^<]+)</title>", html)
    print(f"<title>: {m.group(1).strip() if m else '(none)'}")

    products = parse_product_jsonld(html)
    print(f"[json-ld] Product objects: {len(products)}")
    for i, p in enumerate(products[:3]):
        name = p.get("name") or ""
        if isinstance(name, str):
            name = name[:80]
        print(f"  [{i}] @type={p.get('@type')} name={name} keys={list(p.keys())}")

    nd = parse_inline_json(html, script_id="__NEXT_DATA__")
    print(f"[__NEXT_DATA__]: {'present' if nd else 'absent'}")
    for var in ("__INITIAL_STATE__", "__PRELOADED_STATE__", "__APOLLO_STATE__", "__NUXT__"):
        blob = parse_inline_json(html, window_var=var)
        print(f"[window.{var}]: {'present' if blob else 'absent'}")

    dom = {
        "<table count": html.count("<table"),
        "<dl count": html.count("<dl "),
        "<tr count": html.count("<tr"),
        "<th count": html.count("<th"),
        "'Processor' occurrences": len(re.findall(r"\bprocessor\b", html, re.I)),
        "'Memory' occurrences": len(re.findall(r"\bmemory\b", html, re.I)),
        "'Graphics' occurrences": len(re.findall(r"\bgraphics\b", html, re.I)),
        "'Display' occurrences": len(re.findall(r"\bdisplay\b", html, re.I)),
    }
    for k, v in dom.items():
        print(f"  {k}: {v}")

    headings = re.findall(r"<h([1-3])[^>]*>([^<]{1,120})</h\1>", html, re.I)
    print(f"[headings h1-h3]: {len(headings)} total (showing first 15)")
    for lvl, text in headings[:15]:
        print(f"  h{lvl}  {text.strip()}")


def main() -> int:
    FIX.mkdir(parents=True, exist_ok=True)
    captured: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=UA,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        page = context.new_page()

        def on_response(r):
            rt = r.request.resource_type
            if rt not in ("xhr", "fetch", "document"):
                return
            try:
                headers = r.headers
            except Exception:
                headers = {}
            captured.append(
                {
                    "type": rt,
                    "status": r.status,
                    "url": r.url,
                    "content_type": headers.get("content-type", ""),
                    "content_length": headers.get("content-length", ""),
                    "response": r,
                }
            )

        page.on("response", on_response)

        frame_events: list[tuple[str, str]] = []
        page.on("frameattached", lambda fr: frame_events.append(("attached", fr.url or "")))
        page.on("framenavigated", lambda fr: frame_events.append(("navigated", fr.url or "")))

        print(f"[GET] {URL}")
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:
            print(f"goto failed: {type(exc).__name__}: {exc}")
            browser.close()
            return 2

        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass  # networkidle may flake on pages with polling; fall through.
        time.sleep(3)

        # Gentle scroll in case any section hydrates on visibility.
        last_h = 0
        for _ in range(6):
            h = page.evaluate("document.body.scrollHeight")
            if h == last_h:
                break
            last_h = h
            page.evaluate(f"window.scrollTo(0, {h})")
            time.sleep(0.5)
        time.sleep(2)

        rendered = page.content()
        (FIX / f"{LABEL}_rendered.html").write_text(rendered, encoding="utf-8")

        # Capture live frame state — URLs and content of any non-main frames.
        frame_snapshots: list[dict] = []
        for i, fr in enumerate(page.frames):
            entry: dict = {"index": i, "url": fr.url, "name": fr.name, "is_main": fr == page.main_frame}
            if not entry["is_main"]:
                try:
                    content = fr.content()
                    entry["content_len"] = len(content)
                    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", (fr.name or "frame"))[:30] or "frame"
                    fn = FIX / f"{LABEL}_frame{i}_{slug}.html"
                    fn.write_text(content, encoding="utf-8")
                    entry["saved"] = str(fn.relative_to(REPO))
                except Exception as exc:
                    entry["err"] = f"{type(exc).__name__}: {exc}"
            frame_snapshots.append(entry)

        # Check for the ifr_SpecPage iframe specifically and dump its src attribute.
        try:
            spec_iframe_src = page.evaluate(
                "document.getElementById('ifr_SpecPage')?.getAttribute('src') ?? '<not present>'"
            )
        except Exception as exc:
            spec_iframe_src = f"<eval error: {type(exc).__name__}: {exc}>"

        # Pull bodies for interesting captures while page+browser are still open.
        saved_bodies = 0
        for idx, cap in enumerate(captured):
            if saved_bodies >= BODY_LIMIT:
                break
            if not is_interesting(cap["url"], cap["content_type"]):
                continue
            try:
                body = cap["response"].body()
            except Exception as exc:
                cap["body_err"] = f"{type(exc).__name__}: {exc}"
                continue
            ext = ext_for(cap["content_type"])
            slug = short_slug_from_url(cap["url"])
            fn = FIX / f"xhr_body_{idx:03d}_{slug}.{ext}"
            try:
                fn.write_bytes(body)
                cap["saved_body"] = str(fn.relative_to(REPO))
                saved_bodies += 1
            except Exception as exc:
                cap["body_err"] = f"{type(exc).__name__}: {exc}"

        browser.close()

    # Full trace
    trace_path = FIX / f"{LABEL}_xhr_urls.txt"
    lines = []
    for c in captured:
        lines.append(
            f"{c['type']:8s} {c['status']:>3} "
            f"{c['content_type'][:50]:50s} "
            f"{c['content_length'][:10]:>10s} "
            f"{c['url']}"
        )
    trace_path.write_text("\n".join(lines), encoding="utf-8")

    # Report
    total = len(captured)
    print(f"\ncaptured responses: {total}")
    by_type: dict[str, int] = {}
    for c in captured:
        by_type[c["type"]] = by_type.get(c["type"], 0) + 1
    for t, n in sorted(by_type.items()):
        print(f"  {t}: {n}")

    print(f"\ntrace saved: {trace_path.relative_to(REPO)}")
    print(f"rendered DOM saved: {(FIX / f'{LABEL}_rendered.html').relative_to(REPO)}")

    print("\n=== highlighted responses (URL keyword or JSON content-type) ===")
    hi = [c for c in captured if is_interesting(c["url"], c["content_type"])]
    if not hi:
        print("  (none matched the filter — inspect the trace file manually)")
    for c in hi[:40]:
        tag = ""
        if "saved_body" in c:
            tag = f"  -> {c['saved_body']}"
        elif "body_err" in c:
            tag = f"  (body_err: {c['body_err'][:80]})"
        print(
            f"  {c['type']:6s} {c['status']:>3} "
            f"{c['content_type'][:35]:35s} {c['url']}{tag}"
        )

    # Frame report
    print("\n=== frame snapshots ===")
    for entry in frame_snapshots:
        tag = " (MAIN)" if entry.get("is_main") else ""
        size = f" size={entry['content_len']:,}" if "content_len" in entry else ""
        saved = f" -> {entry['saved']}" if "saved" in entry else ""
        err = f" ERR: {entry['err']}" if "err" in entry else ""
        print(f"  [{entry['index']}]{tag} name={entry['name']!r} url={entry['url']}{size}{saved}{err}")
    print(f"\n#ifr_SpecPage src = {spec_iframe_src}")
    if frame_events:
        print(f"\nframe events ({len(frame_events)} total, last 10):")
        for kind, url in frame_events[-10:]:
            print(f"  {kind}  {url}")

    analyze_rendered(rendered)

    # Verdict
    print("\n=== verdict ===")
    model = MODEL_SLUG.lower()
    json_hits = [
        c for c in hi
        if "application/json" in c["content_type"].lower() and model in c["url"].lower()
    ]
    html_hits_model = [
        c for c in hi
        if model in c["url"].lower() and "html" in c["content_type"].lower()
    ]
    if json_hits:
        print("LIKELY JSON API — at least one JSON response URL contains the model slug.")
        print("  Next: call that endpoint directly with httpx; parse body as JSON.")
    elif html_hits_model:
        print("LIKELY HTML-fragment endpoint — model-specific HTML XHR.")
        print("  Next: call that endpoint with httpx; parse as HTML fragment.")
    elif re.search(r"\bprocessor\b", rendered, re.I) and rendered.count("<table") > 0:
        print("DATA IN RENDERED DOM but no obvious model-specific endpoint.")
        print("  Next: Playwright fetcher that parses rendered DOM via _base.parse_spec_table.")
    else:
        print("UNCLEAR — rendered DOM lacks spec keywords. Extend wait or inspect manually.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
