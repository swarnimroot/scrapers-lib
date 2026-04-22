# scripts/amazon/

Amazon PDP reconnaissance scripts. These are the actual probes run
during Wave 2c to discover that Amazon's standard product-detail page
at `amazon.com/dp/<ASIN>` is — contrary to its Tier 3 reputation —
reachable via plain `httpx` with a current Chrome UA and that the
full per-product spec tables (`<table class="prodDetTable">`) plus
the top ~10 reviews (`<li data-hook="review">`) are SSR'd into the
initial response. The dedicated `/product-reviews/<ASIN>/` surface
was verified to redirect unauthenticated clients to a sign-in wall,
so deeper review pagination is out of reach without credentials.

They remain here as:

1. **Fixture-refresh tooling.** Re-run when Amazon redesigns the PDP
   and the committed fixtures need updating.
2. **A worked example of Tier 3 reconnaissance against a site whose
   reputation does not match its current live behavior.** Amazon kept
   its Tier 3 classification because (a) repeated requests from one
   IP get rate-limited / challenged, (b) redesigns are frequent, and
   (c) full review coverage is auth-gated. See
   [`docs/ADDING_A_SOURCE.md`](../../docs/ADDING_A_SOURCE.md) for the
   methodology this probe implements.

## The script

| Script | What it does | Network |
|---|---|---|
| `probe_posture.py` | §3.8 bot-protection check + §3.3–§3.5 structural signals for any Amazon URL. Plain `httpx.get` with a current Chrome UA. Saves the response body to `tests/tier3/fixtures/amazon/` under the caller-chosen label. Defaults to a gaming-laptop search URL (cheapest first probe — no specific ASIN required). | yes |

## Running

From the repo root:

```bash
# 1. Cheap posture check against a search surface.
.venv/Scripts/python.exe scripts/amazon/probe_posture.py

# 2. A specific PDP (used to produce the committed fixtures).
.venv/Scripts/python.exe scripts/amazon/probe_posture.py https://www.amazon.com/dp/B0F8P6MRQT pdp_B0F8P6MRQT

# 3. The auth-walled /product-reviews/ surface (negative-result capture).
.venv/Scripts/python.exe scripts/amazon/probe_posture.py https://www.amazon.com/product-reviews/B0F8P6MRQT/ reviews_B0F8P6MRQT
```

All scripts assume the package is installed editable (`pip install -e .`)
so `from scrapers_lib...` resolves.

## Output locations

All network probes write into `tests/tier3/fixtures/amazon/`. The
committed fixtures used by unit tests are:

- `pdp_B0F8P6MRQT.html` — Alienware 16 Area-51 Gaming Laptop
  (Dell-brand gaming). Standard `#bylineInfo` PDP render.
- `pdp_B0DW1FVPK8.html` — ASUS ROG Strix G16 2025 (different-brand
  gaming). Premium PDP variant — `#bylineInfo` is empty, brand
  renders via `#visitStoreDesktopUrl` + `#brandLogoHiResByline`.
  Fixtures deliberately chosen from different brands to exercise
  both bylineInfo rendering variants.

The two other fixtures saved by probe runs —
`search_alienware_gaming_laptop.html` (search surface, 29 ASINs
harvested for generality-check candidate pool) and
`reviews_B0F8P6MRQT.html` (the sign-in wall that `/product-reviews/`
redirects to) — are recon-only and not referenced by tests. They
stay committed as negative-result documentation for future
maintenance.

## Notes on the `/product-reviews/` sign-in wall

`amazon.com/product-reviews/<ASIN>/` redirects unauthenticated
clients to `amazon.com/ap/signin?openid.return_to=%2Fproduct-reviews%2F<ASIN>%2F...`
(verified during Wave 2c recon — 328 KB sign-in page, status 200).
That means deep review pagination is not reachable without Amazon
account credentials, which we do not have (free-tier-only constraint
rules out paid proxy + account farms).

The fetcher therefore extracts reviews from the PDP itself, which
inlines the top ~8–10 reviews as `<li data-hook="review">` blocks
with full body / rating / date / author / verified-purchase-badge
content — enough for most Demo 2 and Demo 3 consumer needs. If a
future demo needs the long tail (100+ reviews per product),
upgrade paths are: (a) Amazon Product Advertising API (requires
approved Associate account + ≥3 qualifying sales), (b) an
authenticated stealth browser session (brittle; one account is not
enough to sustain scraping), or (c) third-party review-data
aggregators (paid; excluded by current constraints).
