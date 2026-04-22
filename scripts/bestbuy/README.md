# scripts/bestbuy/

BestBuy PDP reconnaissance scripts. These are the actual probes run
during Wave 2c to discover how to get past BestBuy's Akamai protection
on retail PDPs — a three-step escalation story.

They remain here as:

1. **Fixture-refresh tooling.** Re-run when BestBuy redesigns the PDP
   and the committed fixtures need updating.
2. **A worked example of Tier 3 reconnaissance against a site with
   layered bot protection** where each escalation level revealed the
   next wall. The step-by-step negative-and-positive results trail is
   worth keeping for the next stubborn target. See
   [`docs/ADDING_A_SOURCE.md`](../../docs/ADDING_A_SOURCE.md) for the
   methodology these probes implement.

## The escalation story

| Step | Method | Result |
|---|---|---|
| 1 | Plain `httpx.get` with a current Chrome UA (see `probe_posture.py`) | Search surface 200 OK (SPA shell, products XHR-hydrated). PDP: `RemoteProtocolError: Server disconnected` at the transport layer — classic Akamai JA3/TLS-fingerprint drop. |
| 2 | Stealth Playwright + homepage warming + persistent profile (`probe_pdp_stealth.py`) | `net::ERR_HTTP2_PROTOCOL_ERROR` at navigation — **same signature as HP's `/shop/pdp/` wall.** Akamai's Bot Manager is doing deeper HTTP/2 frame fingerprinting that Chrome-in-automation fails. |
| 3 | `curl_cffi` with Chrome TLS impersonation on HTTP/2 | `HTTP/2 stream N was not closed cleanly: INTERNAL_ERROR` RST_STREAM — same HTTP/2-fingerprint gate. Multiple Chrome versions (`chrome`, `chrome124`, `chrome120`, `chrome116`, `chrome110`) all blocked identically. |
| 4 | `curl_cffi` with Chrome impersonation **forced to HTTP/1.1** + homepage warming | **200 OK, 830–900 KB of real HTML, 5 JSON-LD `reviewBody` blocks inline.** Bypasses the HTTP/2 gate by not using HTTP/2. |

Wall #3 → #4 was the key insight: Akamai's BestBuy deployment ties its
bot-gate logic to HTTP/2 frame analysis. Negotiating HTTP/1.1 at the
transport avoids the gate entirely. This escalation pattern is the
top-ranked upgrade in the HP coverage-gap memory (`curl_cffi` Chrome
impersonation), extended here with the HTTP/1.1 forcing needed for
BestBuy specifically.

## The scripts

| Script | What it does | Network |
|---|---|---|
| `probe_posture.py` | §3.8 bot-protection check + §3.3–§3.5 structural signals on any BestBuy URL. Plain `httpx.get` with a current Chrome UA. Saves the response body to `tests/tier3/fixtures/bestbuy/`. Defaults to a gaming-laptop search URL. Confirmed `search` surface is open but returns a Next.js SPA shell with no product tiles in the initial HTML; confirmed PDPs drop at the transport layer on plain httpx. | yes |
| `probe_pdp_stealth.py` | Stealth Playwright (via `core.playwright_base.stealth_context`) + homepage warming. Kept as insurance documentation of the negative result: even stealth Chromium gets `ERR_HTTP2_PROTOCOL_ERROR` on BestBuy PDPs. | yes — but BestBuy rejects the navigation |

The successful path (curl_cffi + HTTP/1.1 + Chrome impersonation) is
the production I/O primitive inside `scrapers_lib/tier3/bestbuy.py`
and does not have its own probe script — the fetcher itself is the
probe. Reproduce by running the gated integration test
(`tests/tier3/test_bestbuy_integration.py`) with
`SCRAPERSLIB_LIVE_TESTS=1`.

## Running

From the repo root:

```bash
# 1. Plain-httpx posture against search (expected: search works, PDP fails).
.venv/Scripts/python.exe scripts/bestbuy/probe_posture.py

# 2. Plain-httpx posture against a specific PDP.
.venv/Scripts/python.exe scripts/bestbuy/probe_posture.py https://www.bestbuy.com/site/alienware/6628371.p?skuId=6628371 pdp_6628371

# 3. Stealth Playwright escalation (expected: fails with ERR_HTTP2_PROTOCOL_ERROR).
.venv/Scripts/python.exe scripts/bestbuy/probe_pdp_stealth.py
```

All scripts assume the package is installed editable (`pip install -e .`).

## Output locations

Network probes write into `tests/tier3/fixtures/bestbuy/`. The committed
fixtures used by unit tests are:

- `pdp_6628371.html` — Alienware Area-51 18" Gaming Laptop (captured
  via curl_cffi + HTTP/1.1; 5 inline JSON-LD reviews).
- `pdp_6630638.html` — Alienware 16X Aurora 16" Gaming Laptop (same
  capture path, different SKU for §5.7 generality).

The `search_alienware_gaming_laptop.html` fixture is the plain-httpx
capture of the SPA search surface — kept as a negative-result reference
documenting that initial search HTML does not carry product tile
listings (they are XHR-hydrated client-side).

## Coverage caveats on the reviews fetcher

- Only the ~5 reviews BestBuy embeds in the PDP's JSON-LD are
  reachable. Full pagination lives at
  `bestbuy.com/site/reviews/name/<SKU>` — likely same HTTP/2 gate
  (not probed). Future wave: traverse `/site/reviews/name/<SKU>` with
  the same curl_cffi + HTTP/1.1 primitive and paginate via
  `?page=N&sort=most-helpful`.
- `published_at` is `None` on every review — BestBuy's PDP JSON-LD
  does not carry `datePublished`. The `/site/reviews/name/<SKU>`
  surface does, so this is the main motivation for paginating there
  in a future wave.

## Why curl_cffi earns its dependency slot

`curl_cffi` is the only dependency added in Wave 2c. It is:

- Free, open-source, no paid API layer (satisfies the
  `feedback_no_paid_services` constraint).
- The memory-documented "highest leverage, ~30 min probe" upgrade
  path for HP's coverage gap (`project_hp_coverage_gap` memory,
  path #1). Wave 2c confirms the path works for both BestBuy and,
  presumptively, HP — a future wave can wire HP's `/shop/pdp/`
  retrieval over the same primitive to close its 20-spec gap.
- A drop-in replacement for `httpx` at the call site — Session /
  `.get` / `.post` API, no wider refactor needed.

Versioned at `>=0.7` in `pyproject.toml`.
