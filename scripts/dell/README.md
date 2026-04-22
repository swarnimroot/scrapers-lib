# scripts/dell/

Dell-specific reconnaissance scripts. These are the actual probes run during
Wave 2a to discover Dell's `csbapi/unifiedpd/techspecs` endpoint pattern and
capture the test fixtures under `tests/tier2/fixtures/dell/`. They remain
here as:

1. **Fixture-refresh tooling.** Re-run when Dell redesigns a product page
   and the committed HTML fixtures need updating.
2. **A worked example of Tier 2 reconnaissance.** When adding a new
   manufacturer, model the initial recon on these scripts. See
   [`docs/ADDING_A_SOURCE.md`](../../docs/ADDING_A_SOURCE.md) for the
   methodology.

## The scripts

| Script | What it does | Network |
|---|---|---|
| `recon.py` | Fetches Aurora + the first non-Alienware laptop on the category page. Captures pre-scroll HTML, post-scroll HTML, and an XHR/fetch URL trace per product. Used to determine whether scrolling triggers spec hydration (it did not — full specs live behind a secondary API). | yes |
| `inspect_fixture.py` | Offline. Loads the committed Aurora fixture and dumps structural signals: JSON-LD Product, `__NEXT_DATA__`, `data-oc` tile SKUs, `data-url` attributes, top `data-testid` frequencies, heading outline. Useful while tweaking parsers without re-running live fetches. | no |
| `probe_api.py` | Fetches the three Aurora techspecs HTML fragments via the `/csbapi/unifiedpd/techspecs/...` endpoint through a stealth Playwright session. Saves each as a test fixture. | yes |
| `probe_second_product.py` | Generality check: finds a non-Aurora SPD URL via the laptops category page, fetches it, and calls its first tile's techspecs endpoint to verify the pattern. Captures the fixture for XPS 16 (or whatever current product it lands on). | yes |

## Running

From the repo root:

```bash
.venv/Scripts/python.exe scripts/dell/recon.py
.venv/Scripts/python.exe scripts/dell/inspect_fixture.py
.venv/Scripts/python.exe scripts/dell/probe_api.py
.venv/Scripts/python.exe scripts/dell/probe_second_product.py
```

All scripts assume the package is installed editable (`pip install -e .`)
so `from scrapers_lib...` resolves.

## Output locations

All network probes write into `tests/tier2/fixtures/dell/`. The committed
fixtures used by unit tests are:

- `alienware_aurora_16x.html` — the Aurora product page pre-scroll HTML.
- `xps_16_9640.html` — the XPS 16 product page.
- `techspecs_<sku>.txt` — one per tile, HTML fragment from the API.

The recon scripts may save additional diagnostic artifacts (e.g.
`*_after_scroll.html`, `*_xhr_urls.txt`) alongside them; those are not
referenced by tests but are useful when investigating site changes.
