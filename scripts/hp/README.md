# scripts/hp/

HP shop PDP reconnaissance scripts. These are the actual probes run during
Wave 2b to discover that HP's full per-tile configuration data is embedded
as a JSON-encoded HTML comment in the initial server-rendered response,
and to confirm what's NOT there (detailed Tech Specs — Dimensions, Ports,
Weight, etc. — hydrated client-side behind an aggressive bot gate). They
remain here as:

1. **Fixture-refresh tooling.** Re-run when HP redesigns its shop PDP and
   the committed fixtures need updating.
2. **A worked example of Tier 2 reconnaissance when the site is partially
   SSR'd and partially client-hydrated behind anti-bot protection.** HP
   is a useful reference case distinct from Dell (Akamai-protected HTML
   fragments) and Lenovo (pure JSON API). See
   [`docs/ADDING_A_SOURCE.md`](../../docs/ADDING_A_SOURCE.md) for the
   methodology these probes implement.

## The scripts

| Script | What it does | Network |
|---|---|---|
| `probe_hp_pdp.py` | §3.8 bot-protection check + §3.3–§3.5 structural signals for one known HP Omen shop PDP. Plain `httpx.get` with a current Chrome UA. Confirmed HP is 200-OK on plain httpx (no Akamai challenge) and contains JSON-LD + a tile-like DOM, but a naïve heuristic here misfired as "SPA" because HP's state JSON isn't in the usual `<script>` / `window.X =` containers — it's a hidden `<div id="data"><!-- {JSON} --></div>`. That was uncovered by deeper static inspection of this probe's saved fixture, not by the probe itself. | yes |
| `probe_hp_pdp_scroll.py` | Stealth Playwright (via `core.playwright_base.stealth_context`) + homepage warming + scroll-to-bottom + XHR tracing. Kept as insurance documentation of the negative result: HP rejects vanilla Chromium, stealth Chromium, and stealth+warmed Chromium alike on `/shop/pdp/` URLs with `ERR_HTTP2_PROTOCOL_ERROR`. Full detailed Tech Specs coverage via the shop PDP therefore requires either cracking HP's browser bot gate (fragile) or fetching HP's QuickSpecs PDFs from `h20195.www2.hp.com/v2/GetDocument.aspx?docname=<ID>` (feasible but requires a separate PDP-SKU → doc-ID lookup layer, not yet built). | yes — but HP will reject the navigation |

## Running

From the repo root:

```bash
.venv/Scripts/python.exe scripts/hp/probe_hp_pdp.py
.venv/Scripts/python.exe scripts/hp/probe_hp_pdp_scroll.py
```

All scripts assume the package is installed editable (`pip install -e .`)
so `from scrapers_lib...` resolves.

## Output locations

All network probes write into `tests/tier2/fixtures/hp/`. The committed
fixtures used by unit tests are:

- `omen_max_a4nq6av_1.html` — HP Omen Max Gaming Laptop 16t-ah000
  (gaming, Intel). Three tiles, 12 config-picker categories each.
- `pavilion_16z_94g92av_1.html` — HP Pavilion Laptop 16z-ag000 (consumer,
  AMD). Three tiles, 11 config-picker categories each (Pavilion merges
  Processor/Graphics/Memory into one combined category; Omen splits
  them). Fixtures deliberately chosen from different product lines to
  exercise category-name variation.

The probe scripts save additional diagnostic artefacts (the state-JSON
payload as `datasheet_*.pdf` or post-scroll rendered DOM fragments) when
anything comes through, but these are not referenced by tests.

## Why there's no `tier2/_base` lift

Three Tier 2 sources in, still zero shared helpers:

- **Dell** — parses HTML fragments from a protected API endpoint.
- **Lenovo** — parses nested-JSON API responses (no anti-bot).
- **HP** — extracts a JSON-encoded HTML comment from a hidden div in SSR HTML.

Per `docs/ADDING_A_SOURCE.md` §2, a repeating shape across **two or more**
sites must be observed before anything lifts into `tier2/_base.py`. Each
of these three sites has its own bespoke story; nothing to hoist yet.

## Notes on HP's QuickSpecs datasheets

The `probe_hp_pdp_scroll.py` comment references an out-of-scope upgrade
path for full spec coverage. The relevant URL pattern is
`https://h20195.www2.hp.com/v2/GetDocument.aspx?docname=<ID>` where
`<ID>` is a Commercial Document ID like `c09135016` (verified to be a
4-page PDF with Dimensions, Ports, Warranty, etc. for "OMEN MAX Gaming
Laptop 16-ah0015ne"). HP consumer shop PDPs do NOT cross-reference these
IDs, so a mapping layer would be needed — probably scraping HP's QuickSpecs
library index page at `h20195.www2.hp.com/v2/Library.aspx?doctype=41` and
fuzzy-matching on model name. Also note the `h20195` host requires
explicit CA handling (`certifi` or similar — plain httpx hits
`SSL: CERTIFICATE_VERIFY_FAILED` on the system cert store on Windows).
Deferred to a later wave until a demo needs it.
