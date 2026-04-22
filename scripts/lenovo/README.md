# scripts/lenovo/

Lenovo PSREF reconnaissance scripts. These are the actual probes run during
Wave 2b to discover that PSREF hydrates its spec content from a JSON API
(`/api/product/Compare/LoadSpecData`) and to capture the committed fixtures
under `tests/tier2/fixtures/lenovo/`. They remain here as:

1. **Fixture-refresh tooling.** Re-run when Lenovo redesigns PSREF and the
   committed JSON fixtures need updating.
2. **A worked example of Tier 2 reconnaissance when the site is a SPA.**
   Dell's recon (under `scripts/dell/`) is the example for stealth-browser +
   HTML-fragment APIs; this tree is the example for clean JSON-API sites.
   See [`docs/ADDING_A_SOURCE.md`](../../docs/ADDING_A_SOURCE.md) for the
   methodology these probes implement.

## The scripts

| Script | What it does | Network |
|---|---|---|
| `probe_psref.py` | §3.8 bot-protection check + §3.3–§3.5 structural signals. Plain `httpx.get` against one known PSREF URL with a current Chrome UA. Confirmed PSREF is a React SPA shell (5 KB skeleton) with **no bot gate** — the answer to "do we need Playwright + stealth?" was no. | yes |
| `probe_psref_xhr.py` | §3.1 DevTools-equivalent. Vanilla headless Chromium (no stealth, no persistent profile), subscribes to every XHR/fetch/document response, captures iframes and their post-hydration content, saves bodies for interesting URLs. Discovered `LoadSpecData` as the 36 KB JSON payload carrying the full spec tree, and discovered PSREF's nested iframe (legacy `/Product/…` URL loaded inside the React `/l/Product/…` shell). | yes |
| `probe_psref_pdf.py` | §4.1 PDF-datasheet coverage witness. Downloads the per-product PDF at the deterministic URL `/syspool/Sys/PDF/<Line>/<Key>/<Key>_Spec.pdf` and extracts its text with `pdfplumber`, then reports spec-category keyword coverage so we can decide whether the PDF carries *more* than the JSON API. In Wave 2b: PDF and JSON both have full coverage; JSON won because it's already structured. `pdfplumber` was installed into `.venv/` for this probe only — **not** added to `pyproject.toml`. | yes |

## Running

From the repo root:

```bash
.venv/Scripts/python.exe scripts/lenovo/probe_psref.py
.venv/Scripts/python.exe scripts/lenovo/probe_psref_xhr.py
.venv/Scripts/python.exe scripts/lenovo/probe_psref_pdf.py
```

All scripts assume the package is installed editable (`pip install -e .`)
so `from scrapers_lib...` resolves. `probe_psref_pdf.py` additionally
requires `pip install pdfplumber` in `.venv/`.

## Output locations

All network probes write into `tests/tier2/fixtures/lenovo/`. The committed
fixtures used by unit tests are:

- `loadspecdata_legion_pro_7_16afr10h.json` — Legion Pro 7 (AMD, gaming).
- `loadspecdata_loq_15irx10.json` — LOQ 15IRX10 (Intel, entry-level gaming).

The probe scripts save additional diagnostic artefacts (raw page-shell HTML,
full XHR-URL traces, Playwright-rendered iframe content, the spec PDF,
extracted PDF text, etc.) alongside those fixtures. These are not
referenced by tests but are useful when investigating PSREF changes.

## Why there's no `tier2/base` lift

Dell's pattern (`scripts/dell/`) parses HTML fragments returned from a
protected XHR endpoint. Lenovo's pattern parses a nested JSON tree from a
public endpoint. The two implementations share zero helpers today, so no
hoist has happened. Per `docs/ADDING_A_SOURCE.md` §2, a third site must
confirm a repeating shape before anything lifts into `tier2/base.py`.
