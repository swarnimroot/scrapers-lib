"""HP shop PDP reconnaissance — probe 2: stealth browser + scroll + XHR trace.

Probe 1 (``probe_hp_pdp.py``) established:

- HP's shop is NOT bot-gated for plain ``httpx`` (200 OK, no Akamai challenge).
- HP **does** fingerprint vanilla Playwright — the navigator identifies
  itself as a headless browser and HP terminates the HTTP/2 stream with
  ``ERR_HTTP2_PROTOCOL_ERROR``. Stealth Playwright is required.
- A hidden ``<div id="data" style="display:none"><!-- {JSON} --></div>``
  carries a 92 KB state blob with 3 configuration tiles and 12 "config
  picker" spec categories per tile — but the **detailed** spec sheet
  (20+ categories: Dimensions, Weight, Ports, Battery life, Webcam,
  Audio, Wireless, Security, etc.) the user sees further down the page
  is NOT in that initial blob. CSS for ``.pdpTechSpecs`` /
  ``.detailed-specs`` is pre-loaded, but no DOM elements carry those
  classes in the initial HTML — the section is hydrated client-side on
  scroll.

This probe opens the page through ``core.playwright_base.stealth_context``
(the same stealth layer Dell uses), records every XHR/fetch response,
scrolls from top to bottom in increments so any
IntersectionObserver-backed lazy sections fire, and captures bodies for
interesting responses. Phase tracking (``initial`` vs ``scrolling``)
isolates what the scroll itself caused.

Output (under ``tests/tier2/fixtures/hp/``):

- ``omen_max_a4nq6av_1_pre_scroll.html`` — DOM after initial hydration.
- ``omen_max_a4nq6av_1_post_scroll.html`` — DOM after scroll-to-bottom.
- ``omen_max_a4nq6av_1_xhr_urls.txt`` — full trace with phase column.
- ``xhr_body_NNN_<slug>.{json,html,bin}`` — bodies for interesting XHRs.

Run from the repo root::

    .venv/Scripts/python.exe scripts/hp/probe_hp_pdp_scroll.py

See ``docs/ADDING_A_SOURCE.md`` §3.6 (scroll probe) and §5 (decision tree).
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from scrapers_lib.core.playwright_base import stealth_context

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "tier2" / "fixtures" / "hp"
PROFILES = REPO / ".profiles"

# User-supplied URL: Omen Max 16t-ah000, chosen by the user because they
# could visually confirm 20+ specs on it. If probe 1's Omen 16 (a58a5av-1)
# had the same scroll behavior we'd see it too, but we start with the
# user-confirmed case.
URL = "https://www.hp.com/us-en/shop/pdp/omen-max-gaming-laptop-16t-ah000-16-a4nq6av-1"
LABEL = "omen_max_a4nq6av_1"
MODEL_CODE = "A4NQ6AV_1"

HIGHLIGHT_KEYWORDS = (
    "spec",
    "config",
    "tech",
    "detail",
    "product",
    MODEL_CODE.lower(),
    MODEL_CODE.replace("_", "-").lower(),
)
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


def main() -> int:
    FIX.mkdir(parents=True, exist_ok=True)
    captured: list[dict] = []
    current_phase = ["initial"]

    with stealth_context(profiles_dir=PROFILES, domain="www.hp.com") as page:
        # HP fingerprints Playwright stealth on cold-visit too — homepage warming
        # (same technique Dell needs) lets Akamai cookies settle before the PDP hit.
        print("[WARM] https://www.hp.com/us-en/")
        try:
            page.goto(
                "https://www.hp.com/us-en/",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            time.sleep(4)
        except Exception as exc:
            print(f"warm failed: {type(exc).__name__}: {exc}")

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
                    "phase": current_phase[0],
                    "type": rt,
                    "status": r.status,
                    "url": r.url,
                    "content_type": headers.get("content-type", ""),
                    "content_length": headers.get("content-length", ""),
                    "response": r,
                }
            )

        page.on("response", on_response)

        # Phase 1: load
        print(f"[GET] {URL}")
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:
            print(f"goto failed: {type(exc).__name__}: {exc}")
            return 2

        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        time.sleep(3)

        pre_scroll_html = page.content()
        (FIX / f"{LABEL}_pre_scroll.html").write_text(
            pre_scroll_html, encoding="utf-8"
        )
        initial_xhr_n = len(captured)
        print(f"pre-scroll DOM saved: {len(pre_scroll_html):,} chars")
        print(f"initial-load XHRs captured: {initial_xhr_n}")

        # Phase 2: scroll to bottom in increments so IntersectionObservers fire.
        current_phase[0] = "scrolling"
        print("\n[SCROLL] stepping from top to bottom")
        last_h = 0
        for step in range(40):
            h = page.evaluate("document.body.scrollHeight")
            if h == last_h:
                break
            last_h = h
            y = 0
            while y < h:
                page.evaluate(f"window.scrollTo(0, {y})")
                time.sleep(0.25)
                y += 700
            time.sleep(1.2)

        # Final settle — let trailing XHRs complete
        try:
            page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass
        time.sleep(3)

        post_scroll_html = page.content()
        (FIX / f"{LABEL}_post_scroll.html").write_text(
            post_scroll_html, encoding="utf-8"
        )
        scroll_xhrs = len(captured) - initial_xhr_n
        print(f"post-scroll DOM saved: {len(post_scroll_html):,} chars")
        print(f"scroll-phase new XHRs: {scroll_xhrs}")

        # Pull bodies for interesting responses while page+browser still open.
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

    # Write trace
    trace_path = FIX / f"{LABEL}_xhr_urls.txt"
    lines = []
    for c in captured:
        lines.append(
            f"{c['phase']:12s} {c['type']:8s} {c['status']:>3} "
            f"{c['content_type'][:50]:50s} "
            f"{c['content_length'][:10]:>10s} "
            f"{c['url']}"
        )
    trace_path.write_text("\n".join(lines), encoding="utf-8")

    # Report
    total = len(captured)
    print(f"\n=== captured responses: {total} ===")
    by_phase: dict[str, int] = {}
    for c in captured:
        by_phase[c["phase"]] = by_phase.get(c["phase"], 0) + 1
    for phase, n in by_phase.items():
        print(f"  {phase}: {n}")

    print(f"\ntrace saved: {trace_path.relative_to(REPO)}")

    print("\n=== highlighted responses (URL keyword or JSON content-type) ===")
    hi = [c for c in captured if is_interesting(c["url"], c["content_type"])]
    if not hi:
        print("  (none matched)")
    for c in hi[:50]:
        tag = ""
        if "saved_body" in c:
            tag = f"  -> {c['saved_body']}"
        elif "body_err" in c:
            tag = f"  (body_err: {c['body_err'][:60]})"
        print(
            f"  [{c['phase']:10.10s}] {c['type']:6s} {c['status']:>3} "
            f"{c['content_type'][:30]:30s} {c['url'][:130]}{tag}"
        )

    # Phase-isolated: what the scroll caused
    print("\n=== SCROLL-PHASE ONLY responses ===")
    scroll_only = [c for c in captured if c["phase"] == "scrolling"]
    scroll_hi = [c for c in scroll_only if is_interesting(c["url"], c["content_type"])]
    print(f"  total in phase: {len(scroll_only)}  highlighted: {len(scroll_hi)}")
    for c in scroll_hi[:20]:
        print(
            f"    {c['type']:6s} {c['status']:>3} "
            f"{c['content_type'][:35]:35s} {c['url'][:160]}"
        )

    # Also: does the POST-SCROLL DOM now contain tech-spec elements?
    print("\n=== post-scroll DOM check for detailed-specs content ===")
    checks = {
        "class=detailed-specs occurrences": post_scroll_html.count("detailed-specs"),
        "class=pdpTechSpecs occurrences": post_scroll_html.count("pdpTechSpecs"),
        "class=tech-specs-wrapper occurrences": post_scroll_html.count(
            "tech-specs-wrapper"
        ),
        "<table count": post_scroll_html.count("<table"),
        "<dl count": post_scroll_html.count("<dl "),
        "'Dimensions' occurrences": len(re.findall(r"\bDimensions\b", post_scroll_html)),
        "'Weight' occurrences": len(re.findall(r"\bWeight\b", post_scroll_html)),
        "'Ports' occurrences": len(re.findall(r"\bPorts\b", post_scroll_html)),
        "'Webcam' occurrences": len(re.findall(r"\bWebcam\b", post_scroll_html)),
        "'Battery life' occurrences": len(
            re.findall(r"\bBattery life\b", post_scroll_html)
        ),
    }
    for k, v in checks.items():
        print(f"  {k}: {v}")

    # Verdict
    print("\n=== verdict ===")
    scroll_json = [
        c for c in scroll_hi if "application/json" in c["content_type"].lower()
    ]
    scroll_html_frags = [
        c
        for c in scroll_hi
        if "html" in c["content_type"].lower() and c["type"] in ("xhr", "fetch")
    ]
    dom_grew = (
        checks["'Dimensions' occurrences"] > 0
        or checks["'Webcam' occurrences"] > 0
        or checks["class=detailed-specs occurrences"] > 0
    )

    if scroll_json:
        print("LIKELY JSON API — scroll fired JSON XHR(s).")
        print("  Next: call the endpoint with plain httpx (or via stealth if HP")
        print("  rejects httpx on that URL); parse body as JSON.")
    elif scroll_html_frags:
        print("LIKELY HTML fragment — scroll fired HTML XHR(s).")
    elif dom_grew and not scroll_hi:
        print(
            "DOM grew on scroll but no tracked XHR matched our filter — detailed"
        )
        print("  specs may have come from a URL that slipped the highlight keywords.")
        print("  Inspect the trace file manually.")
    elif not dom_grew:
        print("NO DOM growth on scroll. Detailed specs may not render for this URL,")
        print("  or they're gated behind a click (not scroll) trigger.")
    else:
        print("MIXED — inspect post-scroll DOM and XHR trace manually.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
